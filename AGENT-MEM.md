I NEED TO ADD MEMORY TO MY AGENT
10:27 PM
Identified ambiguity and weighed clarification against reasonable interpretation

Quick clarifying question before I dive in — which agent, and what kind of memory?

Q: Which agent/project is this for?
A: opencode-based agent

Q: What kind of memory do you want?
A: ATM AFTER EVERY COMPACTION, AGENT HAS 100% AMNESIA
10:28 PM
Searched the web

TLDR:

    opencode has no built-in cross-compaction memory; need a plugin
    Best fit for free-tier/self-hosted: opencode-agent-memory (file-based, self-editing, no external API) or opencode-mem (local vector DB)
    Both inject memory into system prompt via experimental.chat.system.transform hook, surviving compaction

Options (pick one):

    opencode-agent-memory — file-based (Letta-style blocks in ~/.config/opencode/memory/ + .opencode/memory/), zero external deps, agent self-edits via tools. Best fit your DIY/free-tier ethos.
    opencode-mem — local vector DB (Xenova/nomic-embed-text-v1), semantic search, web UI on :4747, also fully local/free.
    opencode-working-memory — zero extra API calls, piggybacks on existing compaction request, simplest/cheapest but no semantic search.

Given your setup (Termux/HF Spaces, no spare API budget), I'd lean #1 or #3 — no embedding model overhead, no extra LLM calls.

Want me to set up #1 (opencode-agent-memory) as a diff against your config?

1 VS 3 ? PROS/CONS
10:29 PM
Weighed comparative advantages and disadvantages systematically

TLDR:

    #1 (opencode-agent-memory): structured, self-editing blocks, agent actively curates
    #3 (opencode-working-memory): zero extra calls, auto-extracted, simpler but passive

opencode-agent-memory (#1)
✅ Agent actively writes/edits its own memory via dedicated tools — more deliberate, less noise
✅ Structured blocks (persona, project, etc.) with metadata + size limits — predictable, won't bloat
✅ Global (~/.config/opencode/memory/) + project-scoped blocks — good for your multi-project setup
❌ Experimental, requires opencode ≥v1.0.115
❌ Agent has to remember to use the tools — relies on prompting discipline, can miss things if agent doesn't proactively save
❌ No semantic search — pure flat-file recall

opencode-working-memory (#3)
✅ Zero extra LLM/API calls — memory extraction rides on opencode's existing compaction call (truly free)
✅ Fully automatic — no agent discipline needed, captures durable facts at every compaction
✅ Cache-friendly (frozen prompt layout preserves KV-cache reuse)
❌ "Working memory" only — no semantic search/vector recall, just durable facts list
❌ Passive extraction = less control over what gets kept vs #1's deliberate curation
❌ Newer/smaller project, fewer config knobs

Bottom line: #3 if you want "just works, zero cost, zero babysitting." #1 if you want fine-grained control and don't mind occasionally telling the agent "remember this."

For your amnesia-after-compaction pain specifically — #3 is the more direct fix since it's literally built to survive compaction with no extra overhead. #1 also survives compaction but depends more on the agent proactively calling memory tools beforehand.

Want the diff to wire up #3?

GO AHEAD
10:30 PM
Architected configuration changes using diff-style formatting
diff

--- a/package.json
+++ b/package.json
@@
   "devDependencies": {
+    "opencode-working-memory": "latest"
   }

diff

--- a/opencode.json
+++ b/opencode.json
@@
   "plugin": [
+    "opencode-working-memory"
   ]
 }

Install + verify:
diff

--- /dev/null
+++ b/setup-working-memory.sh
@@
+#!/usr/bin/env bash
+# Run inside your project root
+pnpm add -D opencode-working-memory
+mkdir -p .opencode
+echo "opencode-working-memory installed. Restart opencode session to activate."

Notes:

    No config file needed — it auto-hooks into compaction, zero setup beyond the plugin entry.
    Test it: trigger a compaction (long session or manual /compact), then start a new session and ask the agent something it should "remember" from before.
    Browse saved memory anytime with /memory in the TUI.
    If it conflicts with another compaction/prompt plugin you have installed, drop the name here and I'll check order-of-load issues.

WILL THIS AUTO TRIGGER PRE-COMPACTION Y/N?
10:34 PM
Thought for 1s

Y

It hooks into opencode's existing compaction call itself — extraction happens automatically as part of that request, no manual trigger or separate API call needed.

WHERE DOES IT STORE MEMORIES ON FS?
10:34 PM
Acknowledged uncertainty about filesystem storage specifics

I don't have that explicitly from what I pulled earlier — the README mentioned the layout (frozen prompts, workspace vs hot state) but not the exact storage path. Let me check.
Fetched: GitHub - sdwolf4103/opencode-working-memory: Automatic memory for OpenCode agents: persistent workspace memory, hot session context, and compaction-based memory extraction — with zero extra API calls.

TLDR:

    Hot session state: ~/.local/share/opencode-working-memory/workspaces/{hash}/sessions/{sessionID}.json
    Durable workspace memory: ~/.local/share/opencode-working-memory/workspaces/{hash}/workspace-memory.json

{hash} = derived per-workspace identifier. Inspect anytime with npx --package opencode-working-memory memory-diag status.

WHAT IS OPENCODE CONTEXT EPOCH V2... DOES THIS PLUGIN LEVERAGE THAT?
10:35 PM
Investigated Context Epoch concept and plugin integration, flagged terminology ambiguity

TLDR:

    "Context Epoch" = real opencode core concept — the lifecycle boundary for System Context (resets on model/provider switch or session move, admits updates at "Safe Provider-Turn Boundaries")
    No separate "v2" found in docs — likely just the same mechanism, not a distinct versioned spec
    Yes, the plugin explicitly leverages it

From opencode's own CONTEXT.md: a model/provider switch always starts a new Context Epoch while preserving chronological conversation history. Also moving a session clears its active Context Epoch, so the destination must initialize a complete baseline before another prompt can promote.
GitHub
GitHub

opencode-working-memory ties into this directly — its README states durable workspace memory and hot session state are rendered as separate frozen prompts that share the same epoch lifecycle, and it intentionally avoids invalidating the hot snapshot mid-epoch to preserve KV-cache reuse.

I didn't find any "v2" terminology distinct from this — possible it's just internal shorthand you've seen elsewhere, or a recent rename. If you saw "epoch v2" in a specific changelog/PR, paste the link and I'll check what changed.

AFTER INSTALLING "opencode-working-memory" HOW CAN I TEST IT TO BE SURE THAT IT WORKS? STEPS
10:37 PM

TLDR: Install → trigger compaction → check files exist → verify recall in new session

Steps:

    Install & restart

diff

+ pnpm add -D opencode-working-memory

Add to both .opencode/opencode.json and .opencode/tui.json plugin arrays (see earlier diff), then fully restart opencode.

    Seed a memory explicitly
    In a session, type:

Remember this: this project uses pnpm, never npm.

    Check it landed on disk

bash

cat ~/.local/share/opencode-working-memory/workspaces/*/workspace-memory.json

You should see an entry tagged feedback or decision with your text.

    Check via the diag CLI

bash

npx --package opencode-working-memory memory-diag status

Confirms counts of stored/active memories.

    Force a compaction
    Run /compact manually, or just keep chatting until context fills and it auto-triggers.
    Inspect via TUI

/memory → Current memories

Confirm your seeded fact shows up with an [M#] ref.

    The real test — kill and restart the session

    Close the session entirely (new session, same workspace).
    Ask the agent something that depends on that memory, e.g. "what package manager should I use here?"
    It should answer correctly without you re-explaining it — that's proof it survived compaction + session boundary.

    Optional: verify explain trail

bash

npx --package opencode-working-memory memory-diag explain <memory-id>

Shows whether it was promoted, reinforced, or rejected — useful if step 7 fails.

If step 7 doesn't work, check memory-diag rejected first — quality guards may have filtered it.

THE PROBLEM IS IT NEVER READS AGENTS.MD WHEN IT IS THINKING THROUGH THINGS.... IF IT IS STUCK/CORNERED, OBV MD FILES ARE NOT READ... INSTEAD THERE IS A TOKEN STORM
10:39 PM
Searched the web

TLDR:

    This is a known opencode bug, not specific to your plugin: AGENTS.md is loaded once at session start, but not re-consulted once the agent enters a stuck/repeat loop — there's an open issue matching your exact symptom (compaction loop, AGENTS.md ignored, huge log growth = your "token storm")

There's a GitHub issue titled "Stuck in compaction loop, no matter what i do it doesn't read AGENTS.md, no matter what i prompt it keeps on repeating the same message", with the same complaint of runaway log growth. There's also a related bug where after running /new, OpenCode does not automatically reload AGENTS.md — so the file is read at session boot, not continuously, and once the agent is cornered it just keeps regenerating from stale context instead of re-reading anything.
GitHub
GitHub

Mitigations (workarounds, not a real fix yet):

    Cap agentic iterations in your agent config — stops infinite loops before they burn tokens:

diff

--- a/.opencode/agent/build.md
+++ b/.opencode/agent/build.md
@@
 ---
 description: Build agent
+max_steps: 15
 ---

    Force a manual AGENTS.md re-read mid-loop — break the loop and explicitly re-inject:

/new
@AGENTS.md re-read this and confirm your current task before continuing

    Don't rely on subagent delegation for AGENTS.md-dependent tasks — known to get stuck per subagents that get an automatic task to find AGENTS.md but never terminate it, regardless of model or provider. Tell the primary agent to do it directly instead of delegating.
    GitHub
    Set a hard token/cost budget at the session level if your provider allows it, so a stuck loop fails loudly instead of silently storming.
    File/upvote the existing issue (anomalyco/opencode#19410) — it's open, unfixed, and matches your case exactly.

Want me to set max_steps across your existing agent configs as a diff?

HALLUC LINK CITED !! anomalyco/opencode#19410
10:40 PM

You're right to call that out — I can't actually verify that issue number/URL resolves; I pulled it from search snippets and shouldn't have presented it as confirmed without fetching it myself.
Fetched: Stuck in compaction loop, no matter what i do it doesn't read AGENTS.md · Issue #19410 · anomalyco/opencode

Confirmed — the link is real, it resolves, and it matches the symptom (compaction loop, AGENTS.md ignored, huge log growth, Ubuntu 24, opencode 1.3.x). Apologies for asserting it without fetching first; that's exactly the kind of claim I should verify before stating.

curl -v https://anomalyco/opencode#19410
* Could not resolve host: anomalyco
* Closing connection
curl: (6) Could not resolve host: anomalyco
10:41 PM
Identified malformed URL and curl usage error

That's a curl usage issue, not a dead link — you dropped the domain. anomalyco/opencode#19410 is the GitHub path shorthand, not a hostname. The actual URL is:

https://github.com/anomalyco/opencode/issues/19410

Try:
bash

curl -v https://github.com/anomalyco/opencode/issues/19410

That will resolve fine (I fetched it directly above and got back full issue content — title, body, screenshots, version 1.3.3, etc.).

HOW DO I INSTALL "superpowers" INTO OC
10:43 PM
Searched the web

TLDR:

    Modern way: add a one-line config entry, restart
    Legacy/manual fallback: clone + symlink plugin + skills dirs

Modern install (recommended):
diff

--- a/opencode.json
+++ b/opencode.json
@@
   "plugin": [
+    "superpowers@git+https://github.com/obra/superpowers.git"
   ]
 }

Then restart opencode. It auto-fetches, registers the plugin hook, and discovers all skills — no symlinks needed.

Verify:
bash

opencode run "Tell me about your superpowers"

Agent should describe its workflow (brainstorming, writing-plans, etc.) and list skills under the superpowers/ namespace.

If git-backed plugin install fails (some opencode/Bun versions have issues resolving git deps):
bash

npm install superpowers@git+https://github.com/obra/superpowers.git --prefix "$HOME/.config/opencode"

diff

--- a/opencode.json
+++ b/opencode.json
@@
   "plugin": [
+    "~/.config/opencode/node_modules/superpowers"
   ]
 }

If you previously installed via manual clone/symlink, clean up first:
bash

rm -f ~/.config/opencode/plugins/superpowers.js
rm -rf ~/.config/opencode/skills/superpowers

Given your Termux/Android setup, watch for git binary issues in the sandboxed environment — if the plugin can't shell out to git, fall back to the npm-prefix method above.

DOES IT DO MEMORY PRE-POST COMPACTION?
10:55 PM
Distinguished skills framework from memory persistence system

TLDR: No — superpowers isn't a memory system. It's a skills/workflow framework.

It uses experimental.chat.system.transform to inject its bootstrap (the using-superpowers skill content) into the system prompt on every request, not stored conversation history. So the bootstrap itself trivially "survives" compaction — it's re-added fresh each turn regardless — but it's not recalling facts, decisions, or project context the way opencode-working-memory does.

Distinction:

    superpowers = re-injects workflow instructions (brainstorm → plan → execute → review) every turn
    opencode-working-memory = persists durable facts/decisions across sessions and compaction boundaries

They're complementary, not competing — install both:
diff

--- a/opencode.json
+++ b/opencode.json
@@
   "plugin": [
+    "superpowers@git+https://github.com/obra/superpowers.git",
+    "opencode-working-memory"
   ]
 }

One Pi-specific note from docs: superpowers does add a post-compaction re-injection of its bootstrap on the Pi harness specifically — but that's Pi, not opencode. On opencode it's purely the per-turn system-prompt hook, no special compaction handling.

