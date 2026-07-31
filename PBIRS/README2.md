## Executive Compliance & Data Residency Summary

Connecting a **US On-Premises Power BI Report Server (PBIRS)** to **Azure Database for PostgreSQL in the EU** initiates cross-border data flows under GDPR (Chapter V) and EU data sovereignty regulations.

* **Data Transfer Trigger:** Any query executed by US PBIRS pulls data across the Atlantic. Even with **DirectQuery** (where data is not persistently saved to disk in the US), processing and transient caching in-memory on US servers constitutes a **legal cross-border transfer**.
* **Legal Mechanisms Required:** Standard Contractual Clauses (SCCs), EU-US Data Privacy Framework (DPF) certification, or pre-transfer anonymization/pseudonymization (Supplementary Measures under Schrems II).

---

## Architectural Options

### Option 1: DirectQuery over Secure Transit (Zero Persistent US Storage)

* **Mechanism:** PBIRS executes DirectQuery over an Azure ExpressRoute or Site-to-Site IPsec VPN using Private Endpoints to the EU PostgreSQL database.
* **Data Residency Impact:** Source data remains at rest in the EU. Transient processing occurs in-memory in the US during active user sessions.
* **Compliance Requirements:** Must sign Standard Contractual Clauses (SCCs) between US and EU entities and apply Dynamic Data Masking (DDM) on PostgreSQL for sensitive columns.
* **Technical Considerations:** Subject to cross-Atlantic latency (~100–140 ms roundtrip per query block). Requires report query optimization (e.g., aggregations, minimal visual count).

### Option 2: EU-Based Tokenization Pipeline (Aggregated/Anonymized Replication)

* **Mechanism:** An ETL/ELT pipeline (Azure Data Factory in EU) extracts data from PostgreSQL, runs it through an EU-hosted Tokenization/Anonymization engine, and pushes non-PII metrics to a US staging store or read-replica consumed by PBIRS.
* **Data Residency Impact:** Raw PII and sensitive data **never leave the EU**. Only depersonalized or aggregated datasets reside in the US.
* **Compliance Requirements:** Out of scope for GDPR Chapter V transfer restrictions once data is irreversibly anonymized according to EDPB guidelines.
* **Technical Considerations:** Near-zero query latency for US PBIRS users; added infrastructure complexity for ETL and key management.

### Option 3: Localized EU Gateway / Regional Instance

* **Mechanism:** Deploy PBIRS on an Azure VM within an EU region (e.g., West Europe) alongside PostgreSQL. US users connect via HTTPS using Entra ID (Azure AD) SSO.
* **Data Residency Impact:** 100% of data at rest and processing remain strictly within the EU boundary.
* **Compliance Requirements:** Complete data localization compliance; highest sovereignty posture.
* **Technical Considerations:** US end-users experience web UI latency, but report rendering and database queries occur entirely over high-speed intra-EU Azure backbones.

---

## Architecture Comparison & Options Matrix

| Dimension | Option 1: DirectQuery (Cross-Border) | Option 2: EU Tokenized Pipeline | Option 3: Localized EU Instance |
| --- | --- | --- | --- |
| **Data at Rest** | EU (Azure Postgres) | EU (Raw PII) + US (Anonymized) | EU (Azure VM + Postgres) |
| **Data in Transit** | EU to US (Encrypted in-memory) | EU to US (Anonymized metrics) | Intra-EU only (HTTPS display to US) |
| **GDPR Chapter V Scope** | **In Scope** (Requires SCCs/DPF) | **Out of Scope** (If fully anonymized) | **Fully Compliant** (No transfer) |
| **Query Latency** | High (100ms+ network delay) | Low (Local US queries) | Low (Intra-datacenter queries) |

---

## Licensing & Cost Impact

```
                          ┌───────────────────────────┐
                          │    US On-Premises Core    │
                          │   PBIRS (SQL Enterprise)  │
                          └─────────────┬─────────────┘
                                        │
                         Azure ExpressRoute / S2S VPN
                         (Inter-Region Egress Costs)
                                        │
                          ┌─────────────▼─────────────┐
                          │   EU Azure PostgreSQL     │
                          │   (Flexible Server Cost)  │
                          └───────────────────────────┘

```

1. **Power BI Report Server (PBIRS) Licensing:**
* **SQL Server Enterprise Edition with Software Assurance (SA):** Covers PBIRS cores on-premises without per-user licensing for view-only users.
* **Power BI Premium Capacity (P / FFT SKUs):** Grants rights to run PBIRS on-premises with equivalent core allocation.
* *Impact:* Deploying a second PBIRS instance in Azure EU (Option 3) requires allocating additional core licenses or utilizing passive failover/multi-instance rights under Software Assurance.


2. **Azure Egress & Bandwidth Pricing:**
* Cross-region data egress from Azure EU to US On-Premises over VPN/ExpressRoute incurs **Inter-Region / Inbound-Outbound Egress charges** (~$0.087/GB). High-volume DirectQuery models can rapidly elevate bandwidth costs.


3. **Database Costs:**
* Azure Database for PostgreSQL (Flexible Server) requires standard compute/storage allocation. Compute costs remain identical regardless of consumer location, but high concurrent cross-Atlantic query bursts may mandate higher vCore SKUs to handle TLS handshake overhead and long-lived connection pools.
