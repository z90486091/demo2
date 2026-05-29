# QNA Test Suite — REDRAFTED
## Focus: Causal Patterns, Remediation, Anomaly Detection

> Updated test cases emphasize analytical questions over simple retrieval.
> Categories: root cause clustering, fix effectiveness, incident outliers.

---

## SECTION A: CAUSAL PATTERNS & ROOT CAUSES

### Q1: Root Cause Frequency
**Query:** What are the top 3 most common root causes across all incidents?
**Expected:** (1) Resource exhaustion (pool, disk, memory): 8/20. (2) Deployment/config error: 6/20. (3) Load spike / capacity mismatch: 4/20.
**Tests:** Clustering by cause type, count aggregation, ranking.

### Q2: Cascading Failures
**Query:** Which incidents had upstream dependencies (i.e., one service failure triggering another)?
**Expected:** PBMGT-101 (payment) → PBMGT-109 (checkout 502s, timeout). OPS-110 (ETL fails) → stale dashboards → downstream alerts fail.
**Tests:** Dependency chain detection, temporal correlation.

### Q3: Infrastructure vs Application
**Query:** What percentage of incidents were infrastructure-related vs app code bugs?
**Expected:** Type="Bug" indicates app-level (OPS-108, PBMGT-110). Type="Incident" covers infrastructure & config. From DB: 18 Incidents, 2 Bugs = 10% code-level. Infrastructure/config accounts for 90%. Note: Classification based on Type field + root cause from chunks.
**Tests:** Type field filtering, root cause categorization from chunks, arithmetic.

### Q4: Geographic or Regional Patterns
**Query:** Were any incidents region-specific, and did they repeat?
**Expected:** OPS-105 (EU payment gateway). PBMGT-107 (US-EAST-1 ELB). No repeats in same region, suggesting isolated AWS events.
**Tests:** Location extraction, temporal uniqueness.

### Q5: Service Layer Clustering
**Query:** Which service had the most incidents, and were they caused by similar root causes?
**Expected:** Payment (PBMGT-101, OPS-105, PBMGT-109): DB exhaustion, load surge, timeout. Implies systemic payment-path fragility.
**Tests:** Service grouping, root cause co-occurrence.

---

## SECTION B: REMEDIATION & FIX PATTERNS

### Q6: Permanent vs Temporary Fixes
**Query:** List incidents where a temporary workaround was used instead of a permanent fix.
**Expected:** OPS-106 (Status: Done, P3 → scaled workers workaround + HPA fix). OPS-108 (Status: Open, P3 → scale workers workaround, refactor locking proposed). PBMGT-110 (Status: Resolved, P3 → workaround in place). OPS-107, PBMGT-109 (Status: Open → investigation ongoing, no fix deployed).
**Tests:** Status ≠ "Resolved"/"Done" + chunk content for workaround indicators. Type="Bug" may indicate systemic vs incident.

### Q7: Most Effective Remediation Type
**Query:** What fix type (rollback, scaling, config, query kill) had the fastest MTTR?
**Expected:** Rollbacks (v2.4.1, JWT v3.2.0): ~40 min. Scaling (OPS-106): ~15 min. Config (CDN): ~5 min. Kill query: ~30 min.
**Tests:** Timeline analysis, fix type classification.

### Q8: Recurrence Prevention
**Query:** Which incidents introduced monitoring or automation to prevent recurrence?
**Expected:** OPS-102 (log rotation, disk alerts). PBMGT-103 (RTO automation, failover). OPS-103 (payload validation). PBMGT-105 (cache rule CI validation).
**Tests:** Follow-up action extraction, prevention mechanism detection.

### Q9: Incomplete Remediations
**Query:** Which incidents have proposed fixes but are NOT yet Done or Resolved?
**Expected:** Status ∈ {Open, In Progress, To Do} with chunk content indicating fix proposed but not deployed. Examples: OPS-107 (Status: Open, chunk mentions "under investigation"). OPS-108 (Status: Open, "refactor proposed"). PBMGT-109 (Status: Open, "suspected causes listed"). PBMGT-104 (Status: In Progress, fix pending). OPS-105 (Status: To Do).
**Tests:** Status filtering, chunk content scan for "proposed", "under investigation", "pending".

### Q10: Deployment-Related Incidents
**Query:** How many incidents were triggered by code/config deployment, and what was the typical fix?
**Expected:** PBMGT-101 (v2.4.1 rollback), PBMGT-102 (JWT v3.2.0 downgrade), PBMGT-105 (CDN config revert), PBMGT-104 (ES reindex from mapping change). Total: ~4/20. All Type="Incident". Typical fix: rollback or config revert (5–40 min MTTR). Note: Chunk content required to confirm deployment trigger.
**Tests:** Chunk content scan for "deploy", "rollback", "config change"; MTTR extraction from timelines.

---

## SECTION C: ANOMALY DETECTION & OUTLIERS

### Q11: Longest Incident Duration
**Query:** What was the longest-lasting incident, and why was MTTR so high?
**Expected:** PBMGT-103 (47 min RTO): slow manual failover. Target <5 min. Root cause: poor automation, replica lag, fencing issues.
**Tests:** Duration ranking, RTO vs target comparison.

### Q12: Largest Impact by User Count
**Query:** Which incidents affected the most users, and were they prioritized correctly?
**Expected:** PBMGT-101 (all payment users, ~P1 correct). PBMGT-102 (~12K sessions dropped, P1 correct). OPS-110 (analytics delay, P2 reasonable).
**Tests:** Impact quantification, priority validation.

### Q13: Priority Misalignment
**Query:** Are there incidents marked Medium (P3) that had high user impact or long-lived issues?
**Expected:** OPS-106 (Medium/P3, Status: Done → 12K users delayed 10–20 min). PBMGT-110 (Medium/P3, Status: Resolved → memory leak causing POD restart every ~72h). OPS-108 (Medium/P3, Status: Open → slow jobs with unbounded queue backlog). All suggest P3 rating may underestimate operational impact.
**Tests:** Priority vs user-count/impact correlation, chunk content for severity indicators.

### Q14: Outlier Incident Clusters
**Query:** Are there any incidents that don't fit a common pattern?
**Expected:** PBMGT-104 (Elasticsearch GC/reindex, not outage). PBMGT-105 (cache rule, not infrastructure). OPS-109 (429s, rate limit inconsistency). These are config/optimization rather than traditional failures.
**Tests:** Anomaly classification, outlier detection.

### Q15: False Negatives (Missing Incidents)
**Query:** Were there any days with unusually low incident counts, or gaps in the timeline?
**Expected:** Dates in 2023 (PBMGT-102, PBMGT-103, PBMGT-108, PBMGT-110, OPS-106) suggest historical data. Sparse 2026 data. No obvious detection gap.
**Tests:** Timeline analysis, coverage validation.

---

## SECTION D: SYSTEMIC INSIGHTS

### Q16: Common Failure Modes by Service
**Query:** For payment service, list all incidents and identify a systemic weakness.
**Expected:** Payment failures: (1) PBMGT-101 – DB connection exhaustion. (2) OPS-105 – regional gateway overload. (3) PBMGT-109 – downstream timeout. **Systemic issue:** No request queuing, no circuit breaker, no load shedding.
**Tests:** Service-level analysis, cross-incident synthesis.

### Q17: Root Cause Chains
**Query:** Identify any incidents where the root cause was itself caused by a previous incident or missing monitoring.
**Expected:** PBMGT-103 (I/O saturation from unthrottled query) → could have been caught by query alerts. OPS-102 (disk full from unrotated logs) → missing rotation config. These suggest monitoring gaps.
**Tests:** Causal chain detection, second-order root cause analysis.

### Q18: MTTR by Priority vs Actual Severity
**Query:** Did P1 incidents resolve significantly faster than P2/P3?
**Expected:** P1: avg 40–47 min (PBMGT-101, OPS-101, OPS-102 ~45 min each). P2: avg 30–90 min (OPS-110 90 min). P3: ongoing or workaround. Correlation unclear; automation matters more.
**Tests:** Statistical aggregation by priority, MTTR ranking.

### Q19: Correlation: Incident Type → Automation Need
**Query:** Which incident categories most urgently need automation or alerts?
**Expected:** (1) Disk/storage exhaustion (OPS-101, OPS-102, PBMGT-103) → **disk alerts + auto-scaling/rotation**. (2) Query/load issues → **query monitoring + rate limit**. (3) Deployments → **canary + rollback automation**.
**Tests:** Pattern-to-action mapping, prescriptive analysis.

### Q20: Test Coverage Gaps
**Query:** What scenarios are NOT covered by the incident backlog?
**Expected:** No memory exhaustion (except PBMGT-102 JWT, PBMGT-110 worker). No network partition. No security/auth bypass. No data loss. Suggests good reliability practices but potential blind spots in test scenarios.
**Tests:** Absence detection, risk assessment.

---

---

## DB SCHEMA REFERENCE

**Status values:** `In Progress`, `To Do`, `Open`, `Resolved`, `Done`
**Type values:** `Incident` (18), `Bug` (2)
**Priority mapping:** `Highest` (P1), `High` (P2), `Medium` (P3)

For incomplete remediation Q's: look for Status ∈ {Open, In Progress, To Do}.
For app-level bugs: Type="Bug" (OPS-108, PBMGT-110).
For resolved issues: Status ∈ {Resolved, Done}.

---

## EXPECTED ANSWER STRUCTURE

Each answer should include:
- **Data table** (issue key, metric, value)
- **Aggregation or ranking** (top N, percentages, counts)
- **Insight statement** (1–2 sentences on implication)
- **Chart or visualization** (where applicable)

---

## VALIDATION CRITERIA

✓ **Causal patterns:** Can the bot extract root cause, categorize it, and relate it to other incidents?
✓ **Remediation:** Can it distinguish permanent fix from workaround, extract MTTR, and identify follow-ups?
✓ **Anomaly detection:** Can it rank by outlier metric (duration, impact, priority mismatch)?
✓ **Synthesis:** Can it combine multiple incidents to identify systemic issues?
