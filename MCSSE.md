# MCSSE RCA

## KQL (App Insights `exceptions` table, aliased to script's expected headers)

```kql
exceptions
| where timestamp between (datetime(2026-08-19T00:00:00Z) .. datetime(2026-08-20T00:00:00Z))
| where outerMessage contains "call stack"
   or type == "RangeError"
   or outerType == "RangeError"
| project TimeGenerated=timestamp, Message=outerMessage, ExceptionType=type,
          OuterMessage=outerMessage, OuterType=outerType,
          OperationId=operation_Id, SessionId=session_Id, Details=details
| order by TimeGenerated desc
```

Export → CSV from the Logs grid.

## mcsse_rca.py

```python
#!/usr/bin/env python3
"""
Single-file MCSSE RCA tool.
Input:  AppExceptions CSV export (Application Insights / Log Analytics)
Output: classification + root cause + fix suggestion, printed to stdout

Usage:
  python mcsse_rca.py export.csv
  python mcsse_rca.py export.csv --row 0
"""

import csv
import json
import sys
import argparse
from collections import Counter
from dataclasses import dataclass


# ---------- Parse ----------

def load_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


def parse_details(details_raw):
    if not details_raw or not details_raw.strip():
        return []
    text = details_raw.strip()
    attempts = [text]
    if text.startswith('"') and text.endswith('"'):
        attempts.append(text[1:-1].replace('""', '"'))
    attempts.append(text.replace('""', '"'))
    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, dict):
                parsed = [parsed]
            return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def extract_frames(details_list):
    frames = []
    for detail in details_list or []:
        stack = detail.get("parsedStack") or detail.get("parsed_stack") or []
        for frame in stack:
            frames.append({
                "level": frame.get("level"),
                "method": frame.get("method") or frame.get("Method"),
                "fileName": frame.get("fileName") or frame.get("FileName"),
                "line": frame.get("line") or frame.get("Line"),
            })
    return frames


# ---------- Understand ----------

def analyze_frames(frames):
    if not frames:
        return None
    methods_seq = [f["method"] for f in frames if f["method"]]
    method_counts = Counter(methods_seq)
    line_counts = Counter(f'{f["method"]}:{f["line"]}' for f in frames if f["method"])

    alternating = False
    distinct = set(methods_seq)
    if len(distinct) == 2 and len(methods_seq) >= 4:
        a, b = list(distinct)
        pattern_ab = all(methods_seq[i] == (a if i % 2 == 0 else b) for i in range(len(methods_seq)))
        pattern_ba = all(methods_seq[i] == (b if i % 2 == 0 else a) for i in range(len(methods_seq)))
        alternating = pattern_ab or pattern_ba

    return {
        "total_frames": len(frames),
        "top_methods": method_counts.most_common(5),
        "top_lines": line_counts.most_common(5),
        "alternating_pattern": alternating,
        "distinct_methods": len(distinct),
    }


REACT_INTERNALS = {"performUnitOfWork", "commitRoot", "beginWork", "completeWork"}
SERIALIZER_METHODS = {"JSON.stringify", "structuredClone", "stringify"}


@dataclass
class Classification:
    pattern: str
    evidence: str
    root_cause: str
    fix_suggestion: str
    verification: str


def classify(analysis, frames):
    methods_seq = [f["method"] for f in frames if f.get("method")]
    method_set = set(methods_seq)

    if method_set & SERIALIZER_METHODS:
        hit = next(m for m in methods_seq if m in SERIALIZER_METHODS)
        return Classification(
            "circular_reference_serialization",
            f"serializer method '{hit}' repeats {methods_seq.count(hit)}x in trace",
            "Object graph passed to the serializer contains a cycle",
            "Use a WeakSet-based replacer for JSON.stringify to break cycles, "
            "or restructure the data to remove the back-reference before serializing.",
            "Serialize the same object with the guarded replacer; confirm no MCSSE and valid output",
        )

    if method_set & REACT_INTERNALS:
        hit = next(m for m in methods_seq if m in REACT_INTERNALS)
        return Classification(
            "infinite_rerender_loop",
            f"React internal '{hit}' repeats in trace, framework-level recursion",
            "A state update inside render/effect re-triggers itself",
            "Check the useEffect/watcher dependency array against what it sets internally. "
            "Remove the self-triggering dependency or add a guard comparing next vs current state before setting.",
            "Add a render-count log; confirm it stabilizes instead of climbing unbounded",
        )

    if analysis["distinct_methods"] == 1 and analysis["total_frames"] > 10:
        top_method, count = analysis["top_methods"][0]
        top_line, _ = analysis["top_lines"][0]
        return Classification(
            "self_recursion",
            f"'{top_method}' appears {count}x consecutively at {top_line}",
            f"Missing or broken base case in '{top_method}'",
            f"Open '{top_method}' at {top_line}. Verify the base-case condition actually "
            "terminates for the failing input; if recursion depth is input-dependent and "
            "unbounded, convert to an explicit iterative loop/stack.",
            "Re-run with the same input shape that triggered the failing session; confirm bounded depth",
        )

    if analysis["distinct_methods"] == 2 and analysis["alternating_pattern"]:
        (m1, c1), (m2, c2) = analysis["top_methods"][:2]
        return Classification(
            "mutual_recursion",
            f"Alternating pattern: '{m1}' ({c1}x) <-> '{m2}' ({c2}x)",
            f"'{m1}' and '{m2}' call each other; the shared exit condition is "
            f"satisfied on one side but never on the other",
            f"Compare the exit/guard condition inside '{m1}' vs '{m2}'. "
            "Align them to check the same state, or add a shared depth counter/guard "
            "that both functions respect.",
            "Trigger both call paths independently with a depth-limited guard; confirm both terminate",
        )

    if analysis["distinct_methods"] >= 3:
        cycle_order, seen = [], set()
        for m in methods_seq:
            if m in seen and cycle_order and cycle_order[0] == m:
                break
            if m not in seen:
                cycle_order.append(m)
                seen.add(m)
        return Classification(
            "recursive_cycle",
            f"Cycle across {analysis['distinct_methods']} functions: {' -> '.join(cycle_order)} -> ...",
            "Call graph loops back on itself across multiple functions, often via shared state/event propagation",
            "Add a 'visited'/'processing' guard (Set or flag) passed through the call chain "
            "to break the loop, or make one edge in the cycle conditional/one-directional.",
            "Log entry/exit of each function in the cycle; confirm no function is entered twice for the same input",
        )

    return Classification(
        "legitimate_deep_recursion",
        f"{analysis['total_frames']} frames, {analysis['distinct_methods']} distinct methods, no dominant repeat",
        "Not a logic bug -- an unusually large/deep input exceeded the call stack",
        "Convert the recursive traversal to iterative using an explicit stack "
        "(array-based, not the call stack) to remove the depth ceiling entirely.",
        "Test with the same deep input against the iterative version; confirm it completes without MCSSE",
    )


# ---------- Report ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--filter", default="call stack")
    ap.add_argument("--row", type=int, default=None)
    args = ap.parse_args()

    rows = load_rows(args.csv_path)
    if not rows:
        print("No rows found.", file=sys.stderr)
        sys.exit(1)

    matches = [
        r for r in rows
        if args.filter.lower() in (r.get("Message") or r.get("OuterMessage") or "").lower()
        or "rangeerror" in (r.get("ExceptionType") or r.get("OuterType") or "").lower()
    ] or rows

    target_rows = [matches[args.row]] if args.row is not None else matches

    for idx, row in enumerate(target_rows):
        real_idx = args.row if args.row is not None else idx
        print(f"\n{'='*70}\nRow {real_idx} | {row.get('TimeGenerated')} | {row.get('Message') or row.get('OuterMessage')}")

        details = parse_details(row.get("Details") or "")
        if details is None:
            print("[!] Unparseable Details JSON — inspect raw column manually.")
            continue

        frames = extract_frames(details)
        analysis = analyze_frames(frames)
        if not analysis:
            print("[!] No parsedStack frames found in Details.")
            continue

        c = classify(analysis, frames)
        print(f"\nClassification : {c.pattern}")
        print(f"Evidence       : {c.evidence}")
        print(f"Root cause     : {c.root_cause}")
        print(f"Fix suggestion : {c.fix_suggestion}")
        print(f"Verification   : {c.verification}")


if __name__ == "__main__":
    main()
```

## Run

```
python3 mcsse_rca.py export.csv
```
