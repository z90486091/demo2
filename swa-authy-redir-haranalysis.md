# BLANK PAGE ANALYSIS STEPS

## SOURCE CODE FOR IIFE
```bash
# Self-referencing named function expressions (the a(){a()} pattern) — likely minified, single-letter names
rg -n '\(function\s+\w\s*\(\s*\)\s*\{' index.html apps/webapp1/src/**/*.ts

# Any function calling itself by name — broader net, catches unminified too
rg -n 'function\s+(\w+)\s*\([^)]*\)\s*\{[^}]*\b\1\s*\(' --pcre2

# state param handling — redirect/callback logic
rg -n '\bstate\b' apps/webapp1/src --type ts -g '!*.spec.ts'
rg -n 'searchParams.get\(.state.\)|params\[.state.\]|queryParams\[.state.\]' apps/webapp1/src

# Authy/OAuth redirect-back logic specifically
rg -n 'redirect_uri|redirectUri|authy|oauth|callback' apps/webapp1/src --type ts -i

# window.location reassignment inside a function (common in redirect-retry loops)
rg -n 'window\.location\.(href|replace|assign)\s*=' apps/webapp1/src

# setTimeout/setInterval self-recursion (retry-loop pattern, not just direct recursion)
rg -n 'setTimeout\(.*\barguments\.callee\b|function\s+retry' apps/webapp1/src -i
```

Priority order: 

- Run the state/callback/redirect_uri ones first — that's the direct path to the actual guard condition, since you already suspect it's redirect-retry related. 
- The function a(){a()} patterns are for index.html specifically (where you actually saw it), since that file likely isn't minified/bundled the same way as the TS source.

## HAR ANALYSIS

> [!IMPORTANT]
Run: python analyze_wsod_har.py incident.har
Single pass, no follow-up needed — outputs: 

document navigation chain in order (with redirects), 

all anomalous requests (zero-byte/error/blocked/slow), 

timing stalls >1s, and

a summary verdict on whether the blank happened on the first (Authy login) or last (post-login redirect-back) document load. 

Optional --out report.txt to save instead of printing.

```python
#!/usr/bin/env python3
"""
WSOD HAR Analyzer — comprehensive single-pass RCA report.

Usage:
    python analyze_wsod_har.py incident.har [--out report.txt]

Analyzes a captured HAR file for the Authy-login-blank-page incident and
produces a full report covering:
  1. Document navigation chain (which HTML pages loaded, in order, incl. redirects)
  2. Flagged requests (zero-byte 200s, HTTP errors, blocked/no-response, slow requests)
  3. Timing gaps between requests (stalls that could explain a blank render window)
  4. Summary verdict: which stage (pre-login page vs. post-login redirect-back page)
     was most likely the blank one, based on document sizes/status/timing

No external dependencies — stdlib only.
"""
import json
import sys
import argparse
from datetime import datetime


def load_har(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def section(title):
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")


def analyze(har_path, out=None):
    if out:
        sys.stdout = open(out, 'w', encoding='utf-8')

    har = load_har(har_path)
    entries = har['log']['entries']
    entries.sort(key=lambda e: e.get('startedDateTime', ''))

    print(f"WSOD HAR Analysis — {har_path}")
    print(f"Total requests: {len(entries)}")
    if entries:
        print(f"Capture window: {entries[0]['startedDateTime']} -> {entries[-1]['startedDateTime']}")

    # ---------------------------------------------------------------
    # 1. Document navigation chain — top-level HTML loads only
    # ---------------------------------------------------------------
    section("1. DOCUMENT NAVIGATION CHAIN (top-level HTML loads, in order)")
    doc_entries = []
    for e in entries:
        mime = e['response']['content'].get('mimeType', '')
        status = e['response']['status']
        # top-level nav: text/html responses, or 3xx redirects (no body mime yet)
        if 'text/html' in mime or (300 <= status < 400):
            doc_entries.append(e)

    if not doc_entries:
        print("No HTML document entries found — HAR may only contain subresources "
              "(check if 'Preserve log' / full page capture was used).")
    else:
        for i, e in enumerate(doc_entries, 1):
            req, res = e['request'], e['response']
            size = res['content'].get('size', -1)
            status = res['status']
            redirect = res.get('redirectURL', '')
            time_ms = e.get('time', 0)
            flag = ''
            if status == 200 and size == 0:
                flag = '  <-- ZERO-BYTE 200 (likely blank render point)'
            elif status >= 400 or status == 0:
                flag = f'  <-- ERROR/BLOCKED'
            print(f"[{i}] {e['startedDateTime']}")
            print(f"    {req['method']} {req['url']}")
            print(f"    -> status={status} size={size}b time={int(time_ms)}ms{flag}")
            if redirect:
                print(f"    -> redirects to: {redirect}")
            print()

    # ---------------------------------------------------------------
    # 2. Flagged requests — anomalies across ALL requests, not just docs
    # ---------------------------------------------------------------
    section("2. FLAGGED REQUESTS (all types — zero-byte, errors, blocked, slow)")
    flagged = []
    for e in entries:
        req, res = e['request'], e['response']
        status = res['status']
        size = res['content'].get('size', -1)
        time_ms = e.get('time', 0)
        url = req['url']
        flags = []
        if status == 0:
            flags.append('NO_RESPONSE/BLOCKED')
        if status >= 400:
            flags.append(f'HTTP_ERROR_{status}')
        if status == 200 and size == 0:
            flags.append('ZERO_BYTE_200')
        if time_ms > 3000:
            flags.append(f'SLOW_{int(time_ms)}ms')
        if flags:
            flagged.append((e, flags))
            print(f"[{e['startedDateTime']}] {status} {size}b {int(time_ms)}ms  {' '.join(flags)}")
            print(f"    {url}\n")

    if not flagged:
        print("No anomalous requests found (no zero-byte 200s, errors, or requests >3s).")
        print("If the page was still blank, the cause may be client-side rendering "
              "(JS execution/hang) rather than a network-level failure — HAR alone "
              "won't show that; check the browser console log if captured separately.")

    # ---------------------------------------------------------------
    # 3. Timing gaps between consecutive requests
    # ---------------------------------------------------------------
    section("3. TIMING GAPS (stalls between consecutive requests, >1s)")
    prev_end = None
    gap_found = False
    for e in entries:
        start = parse_time(e['startedDateTime'])
        dur_ms = e.get('time', 0)
        if start is None:
            continue
        if prev_end is not None:
            gap = (start - prev_end).total_seconds()
            if gap > 1.0:
                gap_found = True
                print(f"Gap of {gap:.2f}s before: {e['request']['url']}")
        try:
            prev_end = start.replace() if dur_ms is None else start + \
                       __import__('datetime').timedelta(milliseconds=dur_ms)
        except Exception:
            prev_end = start
    if not gap_found:
        print("No significant stalls (>1s) found between requests.")

    # ---------------------------------------------------------------
    # 4. Summary verdict
    # ---------------------------------------------------------------
    section("4. SUMMARY / WHERE TO LOOK NEXT")
    if doc_entries:
        first_doc = doc_entries[0]
        last_doc = doc_entries[-1]
        print(f"First document request : {first_doc['request']['url']}")
        print(f"  status={first_doc['response']['status']} "
              f"size={first_doc['response']['content'].get('size')}b")
        print(f"Last document request  : {last_doc['request']['url']}")
        print(f"  status={last_doc['response']['status']} "
              f"size={last_doc['response']['content'].get('size')}b")
        print()
        first_bad = first_doc['response']['status'] == 200 and \
                    first_doc['response']['content'].get('size', -1) == 0
        last_bad = last_doc['response']['status'] == 200 and \
                   last_doc['response']['content'].get('size', -1) == 0
        if first_bad and not last_bad:
            print("VERDICT: Blank page likely occurred on the FIRST document load "
                  "(pre-login / Authy page itself) — zero-byte response on initial navigation.")
        elif last_bad and not first_bad:
            print("VERDICT: Blank page likely occurred on the LAST document load "
                  "(post-login redirect-back page) — zero-byte response after auth completed.")
        elif first_bad and last_bad:
            print("VERDICT: Both first and last document loads show zero-byte responses — "
                  "inspect the full chain above for exactly where content stopped.")
        else:
            print("VERDICT: No zero-byte document response detected in the chain. "
                  "The failure may be client-side (JS render/hang) rather than "
                  "network-level — HAR won't capture that directly. Cross-check any "
                  "console log or screen recording captured alongside this HAR.")
    else:
        print("No document entries to summarize — see note in section 1.")

    if out:
        sys.stdout.close()
        sys.stdout = sys.__stdout__
        print(f"Report written to {out}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('har_path')
    parser.add_argument('--out', default=None, help='Write report to file instead of stdout')
    args = parser.parse_args()
    analyze(args.har_path, args.out)
```

- Section 1 (nav chain): read top to bottom — each [N] is one HTML page load in the order they happened. Watch for redirects to: lines (Authy → back to SWA) and any ZERO-BYTE 200 flag — that's the page that rendered blank.
- Section 2 (flagged): anomalies across every request (not just pages) — assets/API calls that errored, returned empty, or were slow. Cross-reference timestamps against Section 1 to see if a flagged subresource happened during one of the document loads.
- Section 3 (gaps): a large stall (>1s) right before or during the blank page's load = something hung (Function App cold start, network stall) rather than errored outright.
- Section 4 (verdict): auto-computed answer to your open question — first doc = Authy page blank, last doc = post-login redirect-back page blank, both, or neither (meaning client-side JS issue, not visible in HAR at all).

> [!NOTE]
Start at Section 4 — it's the direct answer. Only dig into 1-3 if you need to see why that verdict came out the way it did, or if the verdict says "neither" and you need to hunt for other clues.

# CLARITY PARSER

> [!NOTE]
Run: python parse_stack_trace.py --stdin then paste the raw trace, or python parse_stack_trace.py trace.txt.<br/><br/>
Output: <br/>repeat count per file:line:col (the recursion signature, works without sourcemaps), <br/>repeat count per minified function name, <br/>a verdict on which call site dominates, and <br/>detection of an alternating A↔B pattern — matching the X↔Y mutual recursion you suspect. <br/>The dominant line:col is what you look up directly in the deployed prod bundle to find the actual code, no sourcemap needed.

```python
#!/usr/bin/env python3
"""
Stack trace parser for "Maximum call stack size exceeded" recursion analysis.

Works on minified traces (no sourcemap needed) — it can't tell you the
original function NAME, but it identifies the repeating minified
function/line:col pattern, which is the recursion signature.

Usage:
    python parse_stack_trace.py trace.txt
    or paste directly:
    python parse_stack_trace.py --stdin   (then paste, Ctrl+D / Ctrl+Z to end)
"""
import re
import sys
import argparse
from collections import Counter

# Matches common V8/Chrome stack frame formats, e.g.:
#   at a (https://fqdn/main.abc123.js:1:2345)
#   at https://fqdn/main.abc123.js:1:2345
#   at Object.a [as b] (main.abc123.js:1:2345)
FRAME_RE = re.compile(
    r'at\s+(?:(?P<func>[^\s(]+)\s+)?\(?(?P<file>[^\s():]+):(?P<line>\d+):(?P<col>\d+)\)?'
)


def parse_frames(text):
    frames = []
    for raw_line in text.splitlines():
        m = FRAME_RE.search(raw_line)
        if m:
            frames.append({
                'func': m.group('func') or '<anonymous>',
                'file': m.group('file'),
                'line': int(m.group('line')),
                'col': int(m.group('col')),
                'raw': raw_line.strip(),
            })
    return frames


def analyze(text):
    frames = parse_frames(text)
    print(f"Total frames parsed: {len(frames)}\n")

    if not frames:
        print("No frames matched. Paste the raw 'at ...' lines from the stack trace.")
        print("If Clarity's format differs, share one example raw line and the regex can be adjusted.")
        return

    # Signature = file:line:col — the minified-safe identity of a call site
    sig_counter = Counter((f['file'], f['line'], f['col']) for f in frames)
    func_counter = Counter(f['func'] for f in frames)

    print("=" * 80)
    print("TOP REPEATING CALL SITES (file:line:col) — the recursion signature")
    print("=" * 80)
    for (file, line, col), count in sig_counter.most_common(10):
        print(f"  {count:4d}x  {file}:{line}:{col}")

    print()
    print("=" * 80)
    print("TOP REPEATING FUNCTION NAMES (minified — 'a', 'b' etc. expected)")
    print("=" * 80)
    for func, count in func_counter.most_common(10):
        print(f"  {count:4d}x  {func}")

    print()
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    top_sig, top_count = sig_counter.most_common(1)[0]
    ratio = top_count / len(frames)
    if ratio > 0.5:
        print(f"Dominant call site: {top_sig[0]}:{top_sig[1]}:{top_sig[2]} "
              f"appears {top_count}/{len(frames)} times ({ratio:.0%}).")
        print("This is almost certainly the recursive call — this exact minified")
        print("file:line:col is what to locate in the deployed prod bundle. Open")
        print("that exact file and jump to that line/col directly — no sourcemap needed.")
    else:
        print("No single call site dominates — trace may be truncated, or the ")
        print("recursion may alternate between 2+ functions (mutual X<->Y recursion,")
        print("matching what you described earlier). Check the top 2-3 signatures")
        print("above together — they likely form the A->B->A->B loop.")

    # Detect alternating pattern (A,B,A,B,...) specifically
    sig_sequence = [(f['file'], f['line'], f['col']) for f in frames]
    if len(set(sig_sequence[-6:])) == 2:
        print()
        print("ALTERNATING PATTERN DETECTED in the last frames — consistent with")
        print("mutual X<->Y recursion (two functions calling each other), not a")
        print("single function calling itself directly.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('trace_file', nargs='?', default=None)
    parser.add_argument('--stdin', action='store_true')
    args = parser.parse_args()

    if args.stdin or args.trace_file is None:
        print("Paste the stack trace, then press Ctrl+D (Linux/Mac) or Ctrl+Z+Enter (Windows):")
        text = sys.stdin.read()
    else:
        with open(args.trace_file, encoding='utf-8') as f:
            text = f.read()

    analyze(text)
```

> [!IMPORTANT]
Get the actual deployed prod index.html (or the deployed bundle if the IIFE got inlined/minified into a build artifact) — not the raw source repo file — since that's what the line:col in the trace refers to
<br/>Use the trace's line:col position on that deployed file to locate the exact minified statement
<br/>From there, manually map that code back to the corresponding raw source function by matching logic/structure (what it calls, what params it takes) — not by name, since names won't match
<br/>Once you've identified the real source function(s) behind g1/k2, read the actual exit condition there

Rest of the checklist (state param correlation, parse_stack_trace.py confirmation, QA AFA repro, AzureDiagnostics query) stays the same — only step 2 needed this correction.
