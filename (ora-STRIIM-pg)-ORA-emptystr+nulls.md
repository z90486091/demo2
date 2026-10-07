# `''` vs `NULL` Fidelity Loss in A → B → C Replication Pipeline

## Pipeline

```
A) Oracle OLTP  --[Striim CDC]-->  B) Postgres OLTP  --[Debezium / ADF+Databricks]-->  C) Oracle OLAP
```

LOB/CLOB columns are excluded from replication — this issue applies to VARCHAR2/CHAR columns only.

## Problem

- A has rows where a given column is a genuine `NULL`, and other rows where the same column is logically "empty" — these are treated as two distinct, meaningful states.
- The A → B Striim job lands **both** as `NULL` in Postgres. The distinction is lost.
- C requires the distinction to be reconstructed, but by the time data reaches C the information is already gone — this cannot be fixed on the B → C leg. It must be fixed on the A → B leg.

## Root cause

- **Oracle cannot store a true `''` in a VARCHAR2 column.** `INSERT INTO t (col) VALUES ('')` on VARCHAR2 stores `NULL` — `col = ''` and `col IS NULL` are equivalent for VARCHAR2. This is documented, longstanding Oracle behavior (kept for backward compatibility), not a bug.
- **CHAR(n) behaves differently but doesn't help either** — `''` inserted into `CHAR(n)` is space-padded to `n` characters and stored as a non-NULL string of spaces (`'   '`), not `''`.
- Since LOB is excluded and VARCHAR2 can't hold `''`, whatever A's "empty" rows actually contain is **not a literal `''`** at the storage layer — it's some other distinguishable value (a single-space sentinel, an app-layer convention, etc.).
- **Action needed before building the fix:** confirm the actual stored representation with:

```sql
SELECT col, LENGTH(col), DUMP(col)
FROM t
WHERE ROWID = '<rowid_of_a_supposed_empty_row>';
```

  `LENGTH(col)` returns `NULL` for both true `NULL` and any VARCHAR2 value that collapsed to `NULL` on insert, so it alone won't distinguish the cases. `DUMP()` shows the actual byte representation and will confirm whether it's a space-pad, a literal single space, or something else.

- Separately, Striim's default WAEvent → target column mapping does not reliably preserve empty-vs-null distinctions on write to Postgres — there's no first-class "preserve empty vs null" toggle in most Striim target adapters, so even a distinguishable source value can still collapse during the write.

## Fix: shadow boolean flag per affected column

Add a Striim CQ that emits a companion `_is_empty` flag alongside each real column, computed from whatever the actual "empty" representation is confirmed to be in A. Example assumes a single-space sentinel — **adjust the condition once confirmed via `DUMP()`**.

### A → B leg (Striim TQL)

```diff
+ -- Striim CQ (TQL) inserted before the target WriteConfig
+ CREATE CQ emit_empty_flag
+ INSERT INTO EnrichedStream
+ SELECT
+     ...,
+     col,
+     CASE
+       WHEN col IS NOT NULL AND TRIM(col) = '' THEN 1  -- adjust to actual sentinel condition
+       ELSE 0
+     END AS col_is_empty
+ FROM SourceStream;
```

`col` writes through to B unchanged (NULL stays NULL, sentinel value writes through as-is — doesn't matter). `col_is_empty` is the source of truth for reconstruction, so B doesn't depend on the sentinel surviving intact.

### B → C leg (Debezium SMT or ADF/Databricks derived column)

```diff
+ -- Debezium SMT / ADF derived column expression
+ CASE
+   WHEN col_is_empty = 1 THEN ''
+   ELSE col
+ END AS col
```

## Trade-offs

- No collision risk with real data — unlike a sentinel-string approach (e.g. `'\u0001EMPTY\u0001'`), the flag decouples "is this logically empty" from the actual value in `col`.
- Doubles the column count in B for every affected field, and requires a schema change in B plus a matching mapping change on the C-bound leg.
- Only apply to columns confirmed (via `DUMP()`) to actually carry the `''` vs `NULL` distinction in A — not a blanket rule for every VARCHAR2 column.
- If the confirmed sentinel turns out to be an exact value (e.g. a literal single space) rather than "any whitespace," tighten the CQ condition to an exact match (`col = ' '`) instead of `TRIM(col) = ''`, to avoid misclassifying legitimate whitespace-only data.

## Open item

Run the `DUMP()` query above against a known "empty" row to confirm the actual stored representation before finalizing the CQ condition.
