# PK-less Table CDC Solution — Oracle → Postgres Migration

## Problem

Several Oracle source tables (mostly audit log tables) lack a primary key or unique
constraint. Striim's CDC apply logic needs a deterministic way to identify a row on
UPDATE/DELETE; without a key, it falls back to matching on all remaining columns,
which is non-deterministic whenever duplicate rows exist. This produces duplicate
rows on the Postgres target for these specific tables.

## Constraints

- **Faithful migration**: the target must mirror the source as-is. A missing PK is
  accepted as inherited source tech debt — it is not "fixed" by adding a permanent
  PK to the real schema on either side.
- **One-way cutover**: writes to Oracle stop permanently at cutover. Striim CDC
  exists only to serve the migration; there is no future/ongoing CDC requirement
  once cutover completes.
- **Single pipeline**: a split into two Striim apps (PK-backed vs PK-less tables)
  was considered and rejected — several PK-less tables are audit logs written by
  triggers inside the same transaction as their parent (PK-backed) table, so
  splitting risks breaking cross-table commit ordering on the target.

## Options considered

| Option | Verdict |
|---|---|
| ROWID as CDC key | Rejected — not stable across row migration/shrink/partition move; no Postgres equivalent, so the raw ROWID would need storing as a column anyway with none of the upside |
| Full supplemental logging (match on full row) | Rejected as primary fix — only resolves ambiguity for non-identical rows; true duplicates still collide |
| Composite natural key from existing columns | Viable only if an existing column combination is provably unique — worth a `GROUP BY … HAVING COUNT(*) > 1` audit before relying on it |
| **Sequence-backed invisible surrogate key** | **Selected** |

## Solution: sequence-backed invisible surrogate key

For each PK-less table:

1. **New dedicated sequence**, one per table, not shared/reused from any existing
   sequence on that table.
2. **New invisible NUMBER column**, added with a `DEFAULT ... NEXTVAL` so existing
   rows are backfilled automatically in the same DDL statement (no separate UPDATE
   pass needed).
3. **PK constraint on the new column** in Oracle — this is a scaffolding constraint
   on a scaffolding column, not a PK on the table's real/original columns, so it
   does not violate the faithful-migration constraint.
4. **Supplemental log group** on the new column, so LogMiner captures its
   before/after image.

Column/object naming used throughout this doc: `mig_srg_id` (column),
`seq_<table>_srg` (sequence), `pk_<table>_srg` / `grp_<table>_srg` (constraint /
log group) — one consistent pattern per table.

### Postgres target

The invisible property does **not** carry over — **Postgres has no invisible/hidden
column feature at all**. The surrogate column lands as an ordinary, fully visible
column on the target. Add it with a plain `ALTER TABLE ADD COLUMN` before Striim's
initial load/resume runs for that table, so it exists to receive data from the
start rather than needing a backfill/reconciliation pass.

### Striim configuration

- Set `oracle.jdbc.showInvisibleColumns=true` on the Oracle source connection
  (connection-level; applies to all tables read by that connection).
- Override `KeyColumns` to `mig_srg_id` for each affected table (tables that
  already have a real PK/unique key do not need this override).

## Why this table needs to exist on both sides

- **INSERT**: works even without the key on the target — Striim reads the full row
  image from redo and inserts only the real columns if desired.
- **UPDATE / DELETE**: break without the key on the target. Striim's apply
  statement needs a `WHERE` clause matching a column that exists in the target
  table. With no key column target-side, it falls back to matching on all
  remaining columns — reproducing the original non-determinism problem.

Conclusion: `mig_srg_id` must exist in Postgres, not just Oracle, for the duration
CDC is active.

## Sequencing

This is a **pre-CDC-start** activity — earlier in the timeline than routine
pre-cutover checks (sequence reconciliation, grants, row counts), which validate
steady-state CDC health *while it's running*.

```
Maintenance window                  Live CDC                 Cutover window
───────────────────────       ──────────────────────    ─────────────────────
Add mig_srg_id + seq +   -->  Striim runs (initial   -->  Final switch,
supplemental log group        load + ongoing               stop Striim,
to all PK-less tables         replication)                 drop mig_srg_id
on Oracle. Add matching                                    from Postgres,
column on Postgres.                                        no replacement PK
```

### Maintenance-window cost

Because the column default is `.NEXTVAL` (non-deterministic), Oracle cannot use
the fast metadata-only path available for constant defaults — it must visit and
rewrite every row to assign a unique value. This is a locking, full-table-scan
operation proportional to row count on larger tables, so it must be scheduled and
run **before** Striim CDC starts, not attempted live.

### If CDC is already live when this is needed

Adding the surrogate key to tables under an already-running Striim app requires:

1. **STOP** the Striim app (or the flow covering the affected tables). Striim
   checkpoints its position; on restart it resumes from that checkpoint rather
   than re-running the initial load — no full reinitialization needed.
2. Run the Oracle `ALTER TABLE ADD` (surrogate key + supplemental log group)
   while stopped.
3. Add the matching column on Postgres (plain `ALTER TABLE ADD COLUMN` — not a
   full ora2pg schema regeneration; ora2pg's role was initial full-schema DDL,
   not incremental single-column changes).
4. Update the Striim source config (`KeyColumns` override, refresh table
   metadata so the reader picks up the now-JDBC-visible column).
5. **START** the app — resumes from the checkpointed SCN, replaying only changes
   since the stop.

**Note on scope of the stop**: the `Tables` property (and any per-table key
override) is static app configuration, not a live runtime toggle. Any table-level
config change — including this one — requires the full stop → edit → redeploy →
start cycle for the app as a whole. There is no lighter-weight way to reconfigure
only the affected tables' CDC without pausing the rest of the app in the same
window (unless tables are already split across multiple apps, which was
considered and rejected above for transaction-ordering reasons).

## Post-cutover cleanup

Once cutover has occurred and Oracle is permanently retired (no future writes,
no future CDC need):

1. Run the sequence/PK reconciliation check **before** dropping the surrogate
   column, using `mig_srg_id` as the join key for a final source/target
   consistency pass — this is the last point at which that join is possible.
2. `ALTER TABLE <table> DROP COLUMN mig_srg_id;` on Postgres.
3. **No replacement PK is added.** Per the faithful-migration constraint, the
   table remains PK-less in Postgres, matching Oracle's original state.
4. Check for dependents (views, FKs, indexes, or manual scripts referencing
   `mig_srg_id`) before dropping — a dependent FK will fail the drop loudly; a
   dependent script will fail silently, later.

## Known forward-looking implication (accepted, out of scope)

Once `mig_srg_id` is dropped and the table has no PK in Postgres, any *future*
CDC or replication reading off this Postgres table (e.g., an OLAP pipeline) will
hit the same non-determinism problem, one hop downstream. This is accepted as
inherited-forward tech debt, consistent with the faithful-migration decision — it
is not solved by this migration and is out of scope here.
