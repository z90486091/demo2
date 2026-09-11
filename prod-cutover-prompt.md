# Prompt: Extract Prod Cutover Runbook from Meeting Transcript

You are extracting a **production cutover runbook** from the transcript of this Teams meeting. Precision matters more than polish — this runbook will be executed live during cutover.

### Extraction rules
- Capture **every discrete action/step** mentioned, even if discussed out of order — reconstruct the actual execution sequence, not the conversation order.
- Preserve **exact timing** as stated: absolute times ("2:00 AM EST"), relative offsets ("T+15 min"), durations ("~20 min window"). Only include a field if it was actually stated — do not derive or estimate it.
- Preserve **exact dependencies**: if a step is stated as blocking another, record the blocking step's number.
- Capture the **owner** (person/team/role) per step, only where the transcript states one.
- Capture **rollback/abort criteria** and rollback steps as a fully separate numbered sequence — never merge into forward steps.
- Capture **go/no-go checkpoints**: where in the sequence, decision criteria, and who has authority to call it.
- Capture **validation/verification steps**, tied by step number to the action they validate.
- Flag **conflicting statements** between speakers (different timing/order/ownership for the same step) with `[CONFLICT]` — surface both versions, never silently pick one.
- **Never invent or infer** steps, tools, timing, or owners not present in the transcript.
- If a step in the Cutover Sequence has no stated Owner, Timing, or Dependency, do not put a placeholder in that cell — instead add a row to the Open Items sheet naming the missing field for that step number. The Cutover Sequence only contains what was actually said.
- Ignore small talk and tangents unrelated to the cutover sequence.

### Output format
Generate **one Excel workbook**, one row per item (use Copilot's table → Export to Excel action). Sheets/tabs:

1. **Pre-Cutover Checklist** — Item, Prerequisite/Freeze/Sign-off, Owner (if stated).
2. **Cutover Sequence** — Step #, Action, Owner (if stated), Timing (if stated), Dependencies (step #s, if stated), Validation Check (if stated), Status (Not Started / In Progress / Done / Skipped — default "Not Started" at generation time).
3. **Go-No-Go Checkpoints** — Checkpoint, Occurs After Step #, Decision Criteria, Decision-Maker.
4. **Rollback Plan** — Trigger Condition, Rollback Step #, Action, Owner.
5. **Post-Cutover Validation** — Check, Expected Result, Owner.
6. **Open Items** — Step #, Missing Field (Owner / Timing / Dependency / Validation), Flag Type (`GAP` / `CONFLICT`), Detail.

Only include a column value where the transcript actually supports it — omit rather than pad. If Excel/table export isn't available in this context, output each sheet as a markdown table in the same column order instead.

When writing an Action's text, preserve exact values (thresholds, commands, error codes) verbatim rather than paraphrasing them loosely; paraphrase the surrounding description. Do not include speaker names in the Action text — names only ever go in the Owner column.
