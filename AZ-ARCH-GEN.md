# Automating Architecture Diagrams for Hub-Spoke (AFD → Firewall → AGW → APIM → SWA)

## Topology in scope
```
HUB (RG: rg-hub-network)  → AFD → Azure Firewall → App Gateway → APIM
SPOKE (RG: rg-spoke-swa)  → Static Web App
```
Hub and spoke live in **separate resource groups**.

---

## Option 1: Diagram-as-code (manual/scripted)
- **Mermaid.js** — hand-write or script-generate. **Grayscale only, per standing constraint.**
- **Python `diagrams` library** — code-as-diagram, has native Azure icon set (AFD, Firewall, AGW, APIM, SWA).
- **Structurizr / C4-PlantUML** — versionable, good for hub-spoke layering.

## Option 2: Azure Portal native — Resource Visualizer
- Resource Group → **"Resource Visualizer"** in left nav → auto-renders live diagram of resources + connections, no setup.
- **Limitation confirmed:** scoped per Resource Group. Since hub and spoke are in different RGs, this produces **two disconnected diagrams** — no built-in way to bridge them in one view.
- Cross-RG topology instead: **Network Watcher → Topology** view shows VNet peering across RG boundaries.

## Option 3: Azure Resource Graph (ARG) + manual Mermaid conversion
- ARG can query resources across both RGs, but **only returns JSON/table — it does not output Mermaid syntax**.
- You must script the conversion yourself. Example script (`generate-arch-diagram.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

# Query resources across both hub and spoke RGs via Azure Resource Graph
RESOURCES=$(az graph query -q "
  Resources
  | where resourceGroup in ('rg-hub-network', 'rg-spoke-swa')
  | project name, type, resourceGroup, id
" -o json | jq -r '.data')

echo "$RESOURCES" > resources.json

# Generate Mermaid (grayscale only, per standing constraint)
cat > arch.mmd << 'EOF'
flowchart LR
    classDef node fill:#eee,stroke:#333,color:#000;

    subgraph HUB[Hub RG]
        AFD[Azure Front Door]
        FW[Firewall]
        AGW[App Gateway]
        APIM[APIM]
        AFD --> FW --> AGW --> APIM
    end

    subgraph SPOKE[Spoke RG]
        SWA[Static Web App]
    end

    APIM --> SWA

    class AFD,FW,AGW,APIM,SWA node;
EOF

echo "Wrote arch.mmd"
```
- **Caveat:** cross-RG edges (e.g. `APIM --> SWA`) are **manually encoded** — ARG gives inventory, not topology. Real connection data (peerings, private endpoints) requires a separate query and pattern-matching against resource IDs.

## Option 4: GitHub Copilot (Agent Mode) + Azure MCP Server — recommended for real Mermaid output
**Prerequisite:** GitHub Copilot Agent Mode + Azure MCP Server extension installed, `az login` completed. This unlocks the documented `azure-resource-visualizer` skill (also works in VS Code, Claude Code, or any compatible MCP client).

Prompt to use:
```
Using Azure MCP tools, query all resources in resource groups
"rg-hub-network" and "rg-spoke-swa", including their network
connections (VNet peerings, private endpoints, service endpoints).

Generate a single Mermaid flowchart (graph LR) showing both resource
groups as subgraphs, with the actual dependency edges between them
(not assumed ones — only what the queried data confirms).

Constraints:
- Grayscale only, no colors (fill:#eee, stroke:#333, color:#000)
- Group nodes under subgraph HUB and subgraph SPOKE
- Label each node with its Azure resource type
- Output only the .mmd code block, no explanation
```
- Swap RG names for yours.
- Copilot calls the MCP tools **live** against the subscription, confirming actual links rather than guessing.
- If the skill isn't auto-invoked, explicitly say "use the azure-resource-visualizer skill."

## Option 5: Microsoft Copilot *inside the Azure Portal* (chat icon, top bar)
- Confirmed capability: can author and run **Azure Resource Graph queries** via natural language.
- **Not confirmed:** reliable Mermaid-formatted output. The `azure-resource-visualizer` skill is documented only for GitHub Copilot Agent Mode / VS Code / Claude Code + Azure MCP — **not** for the in-portal chat assistant.
- Practical prompt to try in-portal:
```
Query Azure Resource Graph for all resources in resource groups
"rg-hub-network" and "rg-spoke-swa", including type and connections.
Output as Mermaid flowchart LR syntax, grayscale, two subgraphs
(HUB and SPOKE), no explanation.
```
- If it balks or returns partial/non-Mermaid output, paste the raw JSON into a tool that has the documented skill (Copilot Agent Mode, Claude Code) to convert.
- **Bottom line:** for guaranteed Mermaid output, Option 4 (Copilot Agent Mode + Azure MCP) remains the reliable route; the in-portal assistant is not confirmed to support this specific output format.

---

## Summary comparison

| Method | Auto-detects resources? | Bridges cross-RG? | Outputs Mermaid? | Reliability |
|---|---|---|---|---|
| Resource Visualizer (Portal) | ✅ | ❌ (per-RG only) | ❌ | High, but scope-limited |
| Network Watcher Topology | ✅ (network layer) | ✅ (peering only) | ❌ | High |
| ARG + manual script | ✅ (inventory) | ⚠️ manual edges | ✅ (self-authored) | Medium — no auto topology |
| Copilot Agent Mode + Azure MCP | ✅ | ✅ | ✅ (documented skill) | High |
| Portal Copilot (chat icon) | ✅ (via ARG) | ✅ (query-level) | ⚠️ unconfirmed | Unverified for this use case |
