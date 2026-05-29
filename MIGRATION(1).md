# MIGRATION.md
> Breaking changes to ingestion pipeline, embedding model, and pgvector schema.
> Full re-ingest required after applying all changes.

---

## Overview

| Component | Before | After | Breaking |
|---|---|---|---|
| Chunker | Hand-rolled, broken | Hand-rolled RCTS, fixed | No |
| `chunk_text` format | `Issue: X \| Summary: Y \| chunk` | `summary\nchunk` | Yes — re-ingest |
| Jira markup stripping | Several wrong regexes | Fixed | No |
| Embedder | fastembed local ONNX | HTTP → Nomic HF Space | Yes — re-ingest |
| Embedding model | `all-MiniLM-L6-v2` | `nomic-embed-text-v1` | Yes — re-ingest |
| Vector dimensions | 384 | 768 | Yes — schema change |
| VSS index | None (sequential scan) | HNSW cosine | Yes — schema change |
| Metadata | All JSONB | All JSONB (for now) | No |

---

## 1. Chunker (`chunker.py`)

### 1.1 Jira Markup Fixes

| Regex | Bug | Fix |
|---|---|---|
| `\*\*(.+?)\*\*` | Markdown bold, not Jira | `\*(.+?)\*` |
| `_(.+?)_` | Breaks `snake_case` identifiers | `(?<!\w)_(.+?)_(?!\w)` |
| `\{\{.+?\}\}` | Drops monospace content entirely | `\{\{(.+?)\}\}` → keep text |

### 1.2 Sentence Splitter

Removed naive regex splitter `(?<=[.!?])\s+` — causes broken sentence boundaries (e.g. `ceeded` instead of `Exceeded`) because it does not handle:
- Abbreviations (`Mr.`, `e.g.`, `vs.`)
- Section headers immediately followed by content
- Jira-style structured text

### 1.3 Chunking Strategy

Replaced broken two-pass overlap logic with a hand-rolled `RecursiveCharacterTextSplitter` (RCTS).

**Why RCTS over semantic chunking:**
- Jira incident descriptions are already structurally sectioned (`Impact`, `Root Cause`, `Resolution`)
- Semantic chunking (cosine similarity between sentences) is designed for dense unstructured prose
- `nomic-embed-text-v1` at 768-dim cannot meaningfully discriminate semantic boundaries at sentence level for short technical text
- RCTS respects natural section breaks first, falls back to sentence then word boundaries

**Why not `langchain-text-splitters`:**
- LangChain breaks backwards compatibility every minor version
- RCTS logic is ~20 lines — no external dependency justified

**Separator priority:**
```python
separators = ["\n\n", "\n", ". ", " "]
```
Tries double-newline (section break) first, then single newline, then sentence boundary, then word.

**Chunk size:** 500 characters (unchanged — appropriate for 768-dim model input).

**Overlap:** Removed. Overlap was a crutch for the broken splitter. RCTS with structural separators produces coherent self-contained chunks that do not need overlap for context continuity. Overlap also caused duplicate content in pgvector, inflating chunk counts and degrading VSS precision.

### 1.4 `chunk_text` Format

This is the most impactful change for retrieval quality.

**Before:**
```
Issue: OPS-105 | Summary: [P2] Partial outage: EU region — payment processing delayed | ceeded regional gateway capacity...
```

**After:**
```
[P2] Partial outage: EU region — payment processing delayed
Exceeded regional gateway capacity. Resolution: Scaled EU payment gateway nodes...
```

**Why this matters:**
- `Issue: OPS-105` has zero semantic signal — it pollutes the embedding with noise tokens
- `Summary:` and `Issue:` string prefixes are structural markers the model does not understand
- The embedding model encodes token co-occurrence — noise tokens shift the vector away from the true semantic meaning
- Query vectors at retrieval time have no such prefixes, creating an asymmetry that degrades cosine similarity scores
- `summary` is already stored in its own column — no information is lost by removing it from the prefix

**Tradeoff:** `summary` is now redundant (own column + prepended to `chunk_text`). This is intentional — the column is used for SQL filtering and display, the prepended copy improves embedding quality. Worth the minor storage cost.

### 1.5 Empty Description Guard

```python
if not description or not description.strip():
    return []
```
Previously would produce a chunk containing only the summary with no description content.

---

## 2. Embedder (`embedder.py`)

### 2.1 Model Change

| | Before | After |
|---|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` | `nomic-embed-text-v1` |
| Params | 22M | 137M |
| Dimensions | 384 | 768 |
| MTEB retrieval score | ~49 | ~62 |
| Optimised for | Sentence similarity | **Retrieval (RAG)** |
| Inference | Local ONNX via fastembed | HTTP → HF Space |

**Why MiniLM was wrong for this use case:**
MiniLM-L6-v2 is a sentence similarity model, not a retrieval model. It was never benchmarked or trained for asymmetric search (short query vs longer document chunk). For RAG the query and document are semantically related but structurally different — MiniLM handles this poorly.

**Why not Gemini embedding-001:**
- Higher MTEB score (~72) but double-hop latency (app → HF Space → Google)
- Subject to Google API rate limits
- External cloud dependency for a core pipeline component
- Quality delta over Nomic is marginal for technical incident text
- Nomic is already a massive upgrade from MiniLM

**Tradeoff — HTTP vs local ONNX:**
- Local ONNX: zero latency overhead, no network dependency, fast ingest
- HTTP Nomic endpoint: ~10-50ms per batch call, network dependency
- Acceptable because ingest speed is not a requirement (async queue worker)
- Retrieval quality gain far outweighs latency cost

**`search_query:` vs `search_document:` prefix — known issue:**

Nomic-embed-text-v1 uses task prefixes to place vectors in the correct embedding subspace:
- `search_document:` — for chunks being ingested
- `search_query:` — for queries at retrieval time

The HF Space endpoint adds `search_query:` to **all inputs automatically**, including ingest batches. This means document chunks are embedded with the wrong prefix — they land in query space rather than document space, creating a systematic asymmetry that degrades cosine similarity scores at retrieval time.

**Mitigation options (in priority order):**
1. Fix the HF Space to accept an optional `prefix` param — caller passes `search_document:` for ingest, `search_query:` for retrieval
2. Prepend the correct prefix manually in `embedder.py` before the HTTP call and disable auto-prefix on the server
3. Accept the degradation — still a large quality improvement over MiniLM, fix in a follow-up

For now option 3 is acceptable given the overall quality delta. Flagged for next iteration.

### 2.2 HTTP Client

Replaced `fastembed` + `run_in_executor` with native `aiohttp` async calls. No thread pool needed.

**Endpoint:**
- Single: `POST /embed` → `{ "text": "..." }` → `{ "embedding": [...] }`
- Batch: `POST /embed-batch` → `{ "texts": [...] }` → `{ "embeddings": [[...], ...] }`

---

## 3. pgvector Schema (`db.py`)

### 3.1 Dimension Change

```sql
-- Before
embedding vector(384)

-- After
embedding vector(768)
```

Cannot `ALTER COLUMN` in place for vector type change — requires dropping and recreating the column or full table migration.

**Recommended migration path:**
```sql
-- 1. Drop old index first
DROP INDEX IF EXISTS idx_jira_chunks_embedding;

-- 2. Change column type
ALTER TABLE jira_chunks 
ALTER COLUMN embedding TYPE vector(768) 
USING NULL;  -- wipe existing embeddings, re-ingest will repopulate

-- 3. Create HNSW index (see below)
```

### 3.2 HNSW Index

**Before:** No index on `embedding` column — every VSS query is a full sequential scan across all rows.

**After:**
```sql
CREATE INDEX ON jira_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**Why HNSW over IVFFlat:**
- IVFFlat requires `VACUUM ANALYZE` and `lists` tuning based on row count
- HNSW builds incrementally — no minimum row count required
- HNSW has better recall at equivalent query speed for datasets under ~1M rows
- No maintenance required as data grows

**Parameter rationale:**
| Param | Value | Meaning |
|---|---|---|
| `m` | 16 | Connections per node per layer. Higher = better recall, more memory. 16 is the sweet spot for most RAG workloads |
| `ef_construction` | 64 | Build-time search width. Higher = better index quality, slower build. 64 is pgvector default |
| `ef_search` | 100 | Query-time search width. Set per session. Higher = better recall, slower query |

**At query time — per connection via asyncpg:**
```python
async with pool.acquire() as conn:
    await conn.execute("SET LOCAL hnsw.ef_search = 100")
    rows = await conn.fetch(...)
```

`SET LOCAL` scopes the setting to the current transaction. `SET` without `LOCAL` would persist for the connection lifetime which is unsafe in a connection pool — a returned connection carries the setting into the next caller's query.

**Why `vector_cosine_ops`:**
Nomic embeddings are L2-normalised. On normalised vectors cosine similarity and dot product are mathematically equivalent, but `vector_cosine_ops` makes the intent explicit and ensures correct behaviour if normalisation ever changes.

### 3.3 Metadata Columns (Deferred)

`priority`, `status`, `issue_type`, `updated_at`, `labels` remain in JSONB for now. Promoting them to first-class columns is the next incremental migration after re-ingest stabilises.

Known issues with current JSONB approach:
- `updated_at` stored as string, cast at query time — no index benefit
- All filter routing goes through JSONB operators — slower than B-tree column lookups
- `labels` array overlap queries (`&&`) not optimally indexed in JSONB vs `TEXT[]` with GIN

---

## 4. Config Changes (`config.py`)

```python
# Remove
EMBED_MODEL = ...
INGEST_CHUNK_OVERLAP = ...  # overlap removed

# Add
EMBED_URL = os.getenv("EMBED_URL", "https://ins0mn1a-nomic-v1.hf.space")
EMBED_DIM = 768
```

---

## 5. Re-ingest Procedure

All changes are co-dependent — `chunk_text` format, embedding model, and vector dimensions must be consistent across all rows. Partial migration is not viable.

```bash
# 1. Apply schema changes
psql $PGVECTOR_URL -c "ALTER TABLE jira_chunks ALTER COLUMN embedding TYPE vector(768) USING NULL"
psql $PGVECTOR_URL -c "DROP INDEX IF EXISTS idx_jira_chunks_embedding"
psql $PGVECTOR_URL -c "CREATE INDEX ON jira_chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)"

# 2. Clear SQLite tracker to force re-ingest of all issues
rm tracker.db

# 3. Re-ingest all issues via webhook replay or seed script
uv run python seed_incidents.py
```

**Why clear the tracker:** `is_duplicate()` checks `updated_at + content_hash`. Existing hashes match existing issues — without clearing the tracker, re-ingest is skipped for all previously ingested issues.

---

## 6. Files Changed

| File | Type of change |
|---|---|
| `chunker.py` | Rewrite — fixed markup, RCTS, clean output format |
| `embedder.py` | Rewrite — HTTP client replacing fastembed |
| `db.py` | Schema change — `vector(768)`, HNSW index, `ef_search` per connection |
| `ingest.py` | Targeted fix — `chunk_text` assembly, remove overlap config |
| `config.py` | Remove `EMBED_MODEL`, add `EMBED_URL`, update `EMBED_DIM`, remove `INGEST_CHUNK_OVERLAP` |
| `test_webhook_ingest.py` | Fix — add missing `status` field with `random.choice` |
| `architecture.md` | Update all references to model, dim, chunking strategy |

---

## 7. What This Does Not Fix (Next Migration)

- JSONB metadata fields not promoted to first-class columns
- No hybrid search (pgvector + `pg_trgm` full-text)
- No query-time reranking (cross-encoder)
- No SQL→VSS or VSS→SQL routing logic
- `hnsw.ef_search = 100` uniform across all query types — not tuned per use case (analytical vs latency-sensitive)
- Nomic HF Space prefix issue (`search_query:` used for all inputs instead of `search_document:` at ingest)
