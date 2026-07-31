Three structurally different patterns, ranked by exposure. Here's how they map to actual build options:

### Option A — Direct connection (what you likely have today)
PBIRS queries Postgres straight across the Atlantic. Two submodes with different risk profiles:
- **Import (scheduled refresh):** raw rows land in PBIRS's own SQL Server cache in the US → a persistent copy of EU data at rest outside the EU. Full GDPR Art. 44 exposure, every refresh cycle.
- **DirectQuery / live connection:** no persistent copy — but every report view is still a live query result crossing the border. Lighter footprint, worse latency, no offline capability.
Both submodes need a transfer mechanism (below). Licensing is unaffected either way.

### Option B — EU-side aggregation or anonymization layer
Build a materialized view, semantic model, or scheduled job that runs inside the EU (in Postgres itself, or an EU-region Fabric/Analysis Services capacity), and let PBIRS only ever query the reduced output.
- If the output is genuinely **anonymized** (re-identification not reasonably likely by any means) it falls outside GDPR's territorial-transfer rules entirely — the cleanest possible outcome.
- If it's only **pseudonymized**, it's still personal data — all of Option A's transfer-mechanism requirements still apply, just to a smaller dataset. This distinction is where most orgs accidentally think they've solved the problem and haven't.
- Costs: EU compute for the aggregation layer; loses row-level drill-through unless combined with C/D.

### Option C — Relocate PBIRS itself into Azure EU
Run the report server on an Azure VM in an EU region. Microsoft's SQL Server 2025 licensing terms explicitly permit running PBIRS on Azure, using the same core-based entitlement as on-prem. Postgres never leaves the EU; US-based staff only receive rendered report output over HTTPS.
- One nuance worth flagging directly: Microsoft's EU Data Boundary keeps Customer Data and pseudonymized personal data stored and processed within the EU/EFTA for in-scope Azure services — but that commitment covers Microsoft's own handling of your Postgres instance, not what *your* application does with the data it retrieves. A flow you build yourself that sends data to a non-Microsoft (or non-Azure) destination is explicitly outside that boundary and yours to manage. On-prem-USA PBIRS pulling from Azure-EU Postgres is exactly that case — the EU Data Boundary gives you zero cover for Option A. It's the actual argument *for* Option C if a contract requires data to stay on EU infrastructure, not just "have a legal transfer basis."
- Trade-off: real re-platforming effort, and it only works if "on-prem" is a preference rather than a hard requirement.

### Option D — Hybrid, classify and route
Keep the existing US PBIRS for aggregate/non-personal reports; send only row-level or personal-data reports through a small EU-hosted tier (Option C, scoped narrowly). The pragmatic 80/20 — smallest new footprint, but adds ongoing report-classification governance.

### Cross-cutting legal nuance
- **Transfer mechanism:** the EU-US Data Privacy Framework remains valid law as of mid-2026 and survived its first General Court challenge, but a second challenge is now pending before the CJEU, and a July 2026 US Supreme Court ruling has raised fresh doubts about the framework because it bears on the independence of the FTC, which enforces the DPF's commercial-sector commitments. Treat DPF self-certification as a secondary layer, not your sole basis — Standard Contractual Clauses plus supplementary technical measures (encryption in transit, access logging, minimization) are the sturdier primary mechanism right now.
- **Transfer Impact Assessment:** required under EDPB 01/2020 regardless of which mechanism you pick — it's a separate, additional step, not a substitute for DPF/SCCs.
- **Controller vs. processor:** whoever bears the Art. 44 obligation depends on your org's role relative to this data — worth pinning down explicitly.
- **Contract vs. law:** client DPAs often require EU-only storage/processing, which is stricter than GDPR itself — check this before assuming SCCs make Option A sufficient.
- **Scope gate:** all of the above only bites if the Postgres content is personal or otherwise regulated data. If it isn't, this is a contractual residency question, not a GDPR one.

### Licensing (recap + what changes per option)
A November 2025 rule change lets you license PBIRS via SQL Server Standard edition without requiring active Software Assurance, alongside the existing SQL Server Enterprise+SA and Fabric F64+ capacity paths — all core-based, all unaffected by where the source database lives. Relocating PBIRS to Azure EU (Option C) doesn't change which entitlement you need, only where the licensed cores run. Any new EU compute (Option B's aggregation job, or a second instance for C/D) is incremental Azure spend, separate from the PBIRS license itself.

### Comparison

| Option | What crosses the border | Transfer mechanism | Rebuild effort |
|---|---|---|---|
| A — Import | Raw rows, persistent | Full TIA + SCC (DPF as backup) | None |
| A — DirectQuery | Raw rows, transient | Same, lighter footprint | None |
| B — EU aggregation | Aggregated/anonymized | None if truly anonymized | Medium |
| C — Relocate to EU | Rendered views only | Minimal (viewer disclosure) | High |
| D — Hybrid | Depends on report | Split by classification | Medium |

**A defensible path:** ship Option A/DirectQuery today with SCCs + a TIA for anything already in flight (fastest, legally coverable), while building Option B for any dataset that can genuinely be anonymized, and reserving Option C for whatever can't — that's Option D in practice, and it avoids betting the whole architecture on DPF while it's under live litigation.
