# SPEC: Business KPI Remediation Routing System

**For:** coding agent implementation
**Stack assumption:** Node.js/TypeScript, pnpm (no npm), pgvector, existing Nomic embed endpoint (768-dim, reused via env var — not hardcoded)
**Compute:** Azure Container Apps — persistent app for webhook receiver + retrieval API, Container Apps Jobs for scheduled harvesters. No Azure Functions.
**Detection:** AppDynamics Health Rules + Policy Action webhook (current). Azure Monitor Action Group is a drop-in replacement at the same interface — see §8.

---

## 1. Non-Goals (do not implement)

- No auto-execution of remediation scripts. Read/notify only.
- No LLM in the detection trigger or retrieval matching path.
- No on-the-fly script/fix generation.
- No write-back to source systems (Confluence/SharePoint/Git/Jira). Harvest is read-only.
- No Slack/email notification channel. Teams only.
- Never a single forced match — retrieval always returns ranked top-3 to top-5.

---

## 2. Repo Structure

```
remediation-router/
├── pnpm-workspace.yaml
├── package.json
├── db/
│   └── migrations/
│       └── 0001_init.sql
├── packages/
│   ├── shared/
│   │   ├── schemas/          # zod schemas, source of truth for §3 types
│   │   └── db/                # pg client, query helpers
│   ├── webhook-receiver/      # §5.1
│   ├── harvesters/
│   │   ├── confluence/        # §5.2
│   │   ├── sharepoint/        # §5.2
│   │   ├── git-docs/          # §5.2
│   │   └── jira-jsm/          # §5.2, gated — see §9 risk 1
│   ├── retrieval/             # §5.3
│   └── notifier/              # §5.4
```

---

## 3. Data Contracts

### 3.1 AnomalySignature

```json
{
  "signature_id": "uuid",
  "source": "appdynamics | azure_monitor",
  "metric_name": "string",
  "metric_path": "string",
  "application": "string",
  "tier": "string | null",
  "business_transaction": "string | null",
  "value": "number",
  "baseline_value": "number | null",
  "deviation_pct": "number | null",
  "severity": "warning | critical",
  "triggered_at": "ISO8601",
  "raw_payload": "object"
}
```

### 3.2 HarvestedDocument / chunk

```json
{
  "canonical_id": "uuid",
  "source_system": "confluence | sharepoint | git | jira",
  "source_ref": "string",
  "source_url": "string",
  "title": "string",
  "content_hash": "sha256 string",
  "chunks": [
    { "chunk_id": "uuid", "summary": "string", "text": "string",
      "metric_keywords": ["string"], "tier_keywords": ["string"], "error_keywords": ["string"] }
  ]
}
```

Chunk format follows the existing `"summary\nchunk"` convention from the Jira RAG project — reuse, don't reinvent.

### 3.3 RetrievalRequest / RetrievalResponse

```json
// Request
{
  "signature_id": "uuid",
  "metric_name": "string",
  "tier": "string | null",
  "application": "string",
  "error_keywords": ["string"],
  "free_text_context": "string | null"
}

// Response
{
  "signature_id": "uuid",
  "matches": [
    { "canonical_id": "uuid", "title": "string", "source_url": "string",
      "match_type": "structured | semantic", "score": "number", "snippet": "string" }
  ],
  "similar_incidents": [
    { "canonical_id": "uuid", "issue_key": "string",
      "resolution_summary": "string", "outcome": "resolved | false_positive | escalated | unknown" }
  ]
}
```

### 3.4 OutcomeLog

```json
{ "outcome_id": "uuid", "signature_id": "uuid", "canonical_id": "uuid | null",
  "resolution_summary": "string", "outcome_status": "resolved | false_positive | escalated | unknown",
  "logged_by": "string", "logged_at": "ISO8601" }
```

---

## 4. Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE documents (
  canonical_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_url TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_ref)
);

CREATE TABLE document_chunks (
  chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_id UUID NOT NULL REFERENCES documents(canonical_id) ON DELETE CASCADE,
  chunk_text TEXT NOT NULL,
  chunk_summary TEXT,
  metric_keywords TEXT[],
  tier_keywords TEXT[],
  error_keywords TEXT[],
  embedding VECTOR(768),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_chunks_hnsw ON document_chunks
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_metric_kw ON document_chunks USING GIN (metric_keywords);
CREATE INDEX idx_chunks_tier_kw ON document_chunks USING GIN (tier_keywords);
CREATE INDEX idx_chunks_error_kw ON document_chunks USING GIN (error_keywords);

CREATE TABLE anomalies (
  signature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_path TEXT,
  application TEXT NOT NULL,
  tier TEXT,
  business_transaction TEXT,
  value DOUBLE PRECISION,
  baseline_value DOUBLE PRECISION,
  deviation_pct DOUBLE PRECISION,
  severity TEXT NOT NULL,
  triggered_at TIMESTAMPTZ NOT NULL,
  raw_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outcomes (
  outcome_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signature_id UUID REFERENCES anomalies(signature_id),
  canonical_id UUID REFERENCES documents(canonical_id),
  resolution_summary TEXT,
  outcome_status TEXT NOT NULL,
  logged_by TEXT,
  logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Query-time: `SET LOCAL hnsw.ef_search = 100;` before semantic-pass queries (matches existing Jira project setting).

---

## 5. Components

### 5.1 webhook-receiver

- **In:** raw AppD Policy Action HTTP POST body
- **Out:** `AnomalySignature` row in `anomalies`; calls `retrieval`; forwards response to `notifier`
- **Acceptance criteria:**
  - [ ] Valid payload → `AnomalySignature` persisted with all required fields populated
  - [ ] Malformed payload → HTTP 400, raw body logged, no crash
  - [ ] Valid payload → retrieval called within 2s, response forwarded to notifier
  - [ ] No code path calls any execution/remediation endpoint
  - [ ] Validates `APPD_WEBHOOK_SHARED_SECRET` on inbound request

### 5.2 harvesters (one package per source, shared interface)

- **In:** source-specific credentials/scope config
- **Out:** upserts to `documents` + `document_chunks`
- **Acceptance criteria (applies to each harvester):**
  - [ ] New source doc → exactly one new `documents` row, new `canonical_id`
  - [ ] Unchanged `content_hash` → skip re-chunk/re-embed
  - [ ] Changed content → update only affected chunks, regenerate their embeddings
  - [ ] No write/update calls to the source API — read scope only, enforced at credential level
  - [ ] Chunking uses hand-rolled splitter consistent with existing Jira project (no LangChain/LlamaIndex/semchunk)

`jira-jsm` harvester is gated: do not implement until the Phase 0 quality audit (§9) confirms resolution notes are usable.

### 5.3 retrieval

- **In:** `RetrievalRequest`
- **Out:** `RetrievalResponse`, ranked
- **Logic:** Pass 1 — ILIKE/exact/GIN match on `metric_keywords`/`tier_keywords`/`error_keywords`. Pass 2 — HNSW cosine VSS on `document_chunks.embedding`, free-text context only. Merge, dedupe by `canonical_id`, structured matches ranked above semantic-only.
- **Acceptance criteria:**
  - [ ] Exact `metric_keywords` match → appears in results with `match_type: structured`
  - [ ] Results capped at 5, minimum 1 if corpus non-empty
  - [ ] No LLM call anywhere in this service
  - [ ] p95 latency < 3s at 10k chunks

### 5.4 notifier

- **In:** `RetrievalResponse`
- **Out:** MS Teams Adaptive Card via `TEAMS_WEBHOOK_URL`
- **Acceptance criteria:**
  - [ ] 3 matches → 3 clickable runbook links + anomaly summary rendered
  - [ ] 0 matches → card explicitly states no match found, not empty/blank
  - [ ] Card includes an outcome-logging action (button or reply prompt) wired to an `outcomes` insert

---

## 6. Config

| Var | Purpose |
|---|---|
| `PG_CONNECTION_STRING` | pgvector-enabled Postgres |
| `EMBEDDING_ENDPOINT_URL` | existing Nomic embed service |
| `APPD_WEBHOOK_SHARED_SECRET` | validates inbound AppD webhook |
| `TEAMS_WEBHOOK_URL` | Adaptive Card delivery |
| `CONFLUENCE_API_TOKEN`, `CONFLUENCE_BASE_URL` | harvester |
| `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`, `SHAREPOINT_TENANT_ID` | Graph API, client_credentials |
| `GIT_DOCS_REPO_URL` | git-docs harvester |
| `JIRA_BASE_URL`, `JIRA_API_TOKEN` | Jira/JSM harvester (gated) |

---

## 7. Tickets

**Epic 1 — Foundation**
T1.1 DB migrations (§4) · T1.2 shared zod schemas (§3) · T1.3 pnpm workspace scaffold

**Epic 2 — Harvesting**
T2.1 confluence · T2.2 sharepoint · T2.3 git-docs · T2.4 jira-jsm (gated, §9) · T2.5 chunk+embed pipeline

**Epic 3 — Detection bridge**
T3.1 webhook-receiver + AnomalySignature normalization · T3.2 AppD Policy Action config (ops task, not code — confirm payload schema first, open question §9)

**Epic 4 — Retrieval**
T4.1 structured pass · T4.2 semantic pass · T4.3 ranking/merge · T4.4 API endpoint

**Epic 5 — Notification & feedback**
T5.1 Teams Adaptive Card template + sender · T5.2 outcome-logging endpoint + Teams action wiring

**Epic 6 — Azure off-ramp (parallel, deferred)**
T6.1 `source: azure_monitor` support in AnomalySignature · T6.2 Azure Monitor Action Group → webhook-receiver compatibility validation

---

## 8. Detection Layer Swap Contract

`webhook-receiver` must accept payloads from either source and normalize both to the same `AnomalySignature`. Azure Monitor Action Group webhook payload maps to the same schema — implement as a second parser behind a `source` discriminator, not a second service.

---

## 9. Open Questions (resolve before Epic 3/T2.4)

1. Exact AppD Policy Action payload schema — HTTP Request action body format
2. AppD API Client (OAuth2) provisioned? Needed only if any REST polling is added later — webhook path doesn't require it
3. Confluence spaces / SharePoint libraries in scope, and owners
4. Jira/JSM resolution-note quality — sample 50 tickets, decide go/no-go on T2.4
5. Teams channel structure — single channel vs per-team vs DM
