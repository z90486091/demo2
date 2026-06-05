#Mermaidjs for Oracle ZDM on Azure DBAS

### Oracle ZDM Physical Online Migration Architecture (Direct Data Transfer)

This comprehensive Mermaid diagram illustrates the comprehensive structural architecture and procedural flow of an Oracle Zero Downtime Migration (ZDM) Physical Online Migration using Direct Data Transfer. It details the compute environments, network communication pathways (protocols and ports), storage layers, and the complete 8-step execution lifecycle.

```mermaid
flowchart TB
    %% Class Definitions for Styling
    classDef compute fill:#e3f2fd,stroke:#0d47a1,stroke-width:2px,color:#000;
    classDef storage fill:#efebe9,stroke:#4e342e,stroke-width:2px,color:#000;
    classDef network fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px,color:#000;
    classDef zdm fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#000;
    classDef step fill:#f3e5f5,stroke:#4a148c,stroke-width:1px,color:#000;

    %% ZDM Management Tier
    subgraph ZDM_TIER ["ZDM Control Plane (Management Tier)"]
        ZDM_NODE["ZDM Service Host\n(Compute Instance / Linux VM)"]:::zdm
        ZDM_CLI["ZDMCLI Software & Engine\n(Orchestration Layer)"]:::zdm
        ZDM_RESP["zdm_template.rsp\n(Migration Response File)"]:::zdm
        
        ZDM_NODE --- ZDM_CLI
        ZDM_CLI --- ZDM_RESP
    end

    %% Source Infrastructure Tier
    subgraph SRC_TIER ["Source Infrastructure (On-Premises / Source Cloud)"]
        subgraph SRC_COMPUTE ["Source Compute Layer"]
            SRC_HOST["Primary Database Host Node\n(Bare Metal / VM / OVM)"]:::compute
            SRC_DB["Oracle Primary Database\n(Single Instance / RAC\nArchivelog & Force Logging)"]:::compute
            SRC_LST["Oracle Net Listener\n(Port 1521 / TNS Service)"]:::network
        end
        
        subgraph SRC_STORAGE ["Source Storage Layer"]
            SRC_DATA["Production Data Files\nRedo Logs, Control Files\n(SAN / NAS / Local ASM)"]:::storage
        end
        
        SRC_HOST --- SRC_DB
        SRC_DB <-->|I/O Read/Write| SRC_DATA
        SRC_HOST --- SRC_LST
    end

    %% Target Infrastructure Tier
    subgraph TGT_TIER ["Target Infrastructure (OCI Cloud / Exadata / Azure)"]
        subgraph TGT_COMPUTE ["Target Compute Layer"]
            TGT_HOST["Target Database Host Node\n(ExaDB-D / ExaDB-C@Azure / BaseDB)"]:::compute
            TGT_DB["Oracle Standby Database\n(Instantiated via Migration\nBecomes Primary on Switchover)"]:::compute
            TGT_LST["Oracle Net Listener\n(Port 1521 / Cloud TNS)"]:::network
        end
        
        subgraph TGT_STORAGE ["Target Storage Layer"]
            TGT_ASM["Oracle ASM Disk Groups\n(+DATA / +RECO / +GRID\nCloud Storage Grid)"]:::storage
        end
        
        TGT_HOST --- TGT_DB
        TGT_DB <-->|I/O Read/Write| TGT_ASM
        TGT_HOST --- TGT_LST
    end

    %% Control Plane Orchestration (Network Pathways)
    ZDM_CLI ==>|"[Step 1 & 2] Control & Prechecks&#10;SSH Port 22"| SRC_HOST
    ZDM_CLI ==>|"[Step 1 & 2] Control & Target Prep&#10;SSH Port 22"| TGT_HOST

    %% Data Plane Interactions (Network & Streaming)
    SRC_DB ===>|"[Step 3 & 4] Direct Data Transfer&#10;RMAN Active Duplicate (No Object Storage Backup)&#10;SQL*Net Port 1521"| TGT_DB
    
    SRC_DB <=>|"[Step 5] Continuous Data Sync&#10;Data Guard Redo Transport / Real-Time Apply&#10;SQL*Net Port 1521"| TGT_DB

    %% Migration Workflow Lifecycle Sequence Box
    subgraph LIFECYCLE ["ZDM Physical Online Sequence Lifecycle"]
        direction LR
        S1["1. Download & Config ZDM"]:::step --> 
        S2["2. Start Migration / Prechecks"]:::step --> 
        S3["3. Restore from Service (RMAN)"]:::step --> 
        S4["4. Instantiate Target Standby"]:::step --> 
        S5["5. Synchronize via Data Guard"]:::step --> 
        S6["6. Switchover & Swap Roles"]:::step --> 
        S7["7. Post-Migration Validations"]:::step --> 
        S8["8. Finalize & Cleanup State"]:::step
    end

    %% Tying lifecycle events to the architecture components
    S6 -.->|Orchestrates Role Swap| ZDM_CLI
    S6 -.->|Primary Target Swap| SRC_DB
    S6 -.->|Standby Primary Swap| TGT_DB

```

---

### Architectural Components and Technical Details

#### 1. Compute Layer Breakdown

* **ZDM Service Host:** A dedicated Linux instance running the Oracle ZDM software (`zdmcli`). It handles execution logic, certificate handling, SSH orchestration, and execution status checking. It does not ingest or store database payload data.
* **Source Host:** Contains the live production database. It must be running in `ARCHIVELOG` and `FORCE LOGGING` modes to support physical replication.
* **Target Host:** Configured in the target ecosystem (such as Oracle Cloud Infrastructure, Exadata Database Service on Dedicated Infrastructure, or Exadata Database Service on Cloud@Customer/Azure). It contains a bare skeleton database environment matching the database version and patch level of the source before instantiation.

#### 2. Network Connectivity Requirements

* **Control Plane Routing (Port 22):** The ZDM Node requires direct, unhindered biographical SSH access (via SSH public key exchange) to the `opc`/`grid`/`oracle` OS users on both the source and target database hosts.
* **Data Plane Transfer Routing (Port 1521):** Because this is a **Direct Data Transfer** configuration, data bypasses intermediate Cloud Object Storage buckets. Source and Target environments must have open bidirectional communication over SQL*Net TCP port 1521. This handles the direct active RMAN database cloning procedure and subsequent Oracle Data Guard traffic.

#### 3. Storage Infrastructure

* **Source End:** Standard production layout utilizing local filesystems, SAN/NAS layouts, or Oracle Automatic Storage Management (ASM).
* **Target End:** Standardized Oracle Cloud Infrastructure storage layouts, utilizing high-performance **Oracle ASM Disk Groups** (`+DATA` for database blocks and data files, `+RECO` for fast recovery area logs, archiving, and flashback structures).

#### 4. The Data Flow Execution Mechanics

1. **Instantiation (RMAN Active Duplicate):** ZDM triggers RMAN on the target host to pull files directly over the network from the primary source database instance. The target environment builds its filesystem out of this stream, initiating the standby instance.
2. **Online Synchronization (Oracle Data Guard):** Once the standby framework is established, Oracle Data Guard takes over. Redo data streams over port 1521 in real-time. The target remains in a mounting or read-only `Active Standby` status, continuously catching up to production transformations.
3. **Switchover Integration:** When synchronization lag hits zero, ZDM performs a controlled switchover. Applications are temporarily drained, the source database transitions to a standby role, and the target infrastructure is promoted to the master primary production role with zero data loss.

By the way, to unlock the full functionality of all Apps, enable [Gemini Apps Activity](https://myactivity.google.com/product/gemini).
