## ZDM Physical Migration to ExaDB-D on Oracle Database@Azure

Two migration paths exist — the choice is driven entirely by whether production downtime is acceptable.

**ONLINE** leverages Data Guard as the transport mechanism. The source stays live throughout; ZDM pulls data directly over SQL*Net using `RESTORE_FROM_SERVICE`, instantiates the target as a physical standby, and lets redo shipping close the gap before switchover. The optional `pauseafter ZDM_CONFIGURE_DG_SRC` holdpoint is critical in practice — it lets teams validate the standby, coordinate application cutover windows, and resume only when ready. Net downtime is effectively the switchover duration.

**OFFLINE** trades downtime for simplicity. RMAN backs up the source to a shared NFS mount, the backup is restored at the target, and the target opens as primary — no standby, no redo shipping. The NVA is the key network dependency here; without it, NFS traffic cannot route between the on-premises network and the OCI delegated subnet inside the Azure VNet.

**The NVA** sits in the Azure VNet for both modes but serves different purposes — primary routing for OFFLINE NFS traffic, backup path for ONLINE. It is not optional for OFFLINE.

**The delegated subnet boundary** is where OCI and Azure meet. NSG controls access into the cluster; UDR controls how traffic is routed within the VNet before it reaches the subnet. VNICs are the attachment point between the Azure network plane and the OCI compute instances.

**TDE is mandatory** in both modes regardless of whether the source is encrypted — a wallet must exist and be open. OFFLINE drops the additional requirement for `FORCE LOGGING` and `ARCHIVELOG` mode since there is no standby to feed.

```mermaid
graph TD
    subgraph CDC["Customer Data Center (on-premises)"]
        ZDM["ZDM Service Host\nOracle/RHEL Linux 8\n100 GB storage · RSA PEM SSH key"]
        subgraph SRC["Source Database"]
            SD["19.21 EE CDB · single-instance\nDB_NAME: oradb\nFORCE LOGGING · ARCHIVELOG · TDE · SPFILE"]
            SS["ASM / local FS · TDE wallet"]
        end
        SD --> SS
        NFS["NFS File Share\nAzure Files · Oracle ACFS · Azure NetApp\nmounted on src + tgt · OFFLINE only"]
    end

    subgraph NET["Network — both modes"]
        UDR["Azure Route Table · UDR"]
        NSG["OCI Network Security Group · NSG"]
        NVA["Network Virtual Appliance · NVA\nOFFLINE: primary NFS routing\nONLINE: backup path"]
        DSUB["Azure Delegated Subnet\nOCI-managed · PLATFORM_TYPE=EXACS"]
        VNIC1["VNIC · Node 1"]
        VNIC2["VNIC · Node 2"]
        UDR --> NVA
        UDR --> DSUB
        NSG --> DSUB
        DSUB --> VNIC1
        DSUB --> VNIC2
    end

    subgraph AZ["Oracle Database@Azure · OCI co-located in Azure DC"]
        subgraph VMCL["ExaDB-D VM Cluster · 2-node RAC 19.22"]
            N1["Node 1"]
            N2["Node 2"]
        end
        TD["Target DB · oradb / oradb_exa\nSPFILE · TDE · SCAN :1521"]
        TS["Exadata ASM · TDE wallet"]
        VNIC1 --> N1
        VNIC2 --> N2
        N1 & N2 --> TD --> TS
    end

    subgraph ONLINE["ONLINE — Production · zero/negligible downtime"]
        direction TB
        OC1["MIGRATION_METHOD=ONLINE_PHYSICAL\nDATA_TRANSFER_MEDIUM=DIRECT\nRESTORE_FROM_SERVICE · no NFS required"]
        OC2["Prechecks · Setup · Validate\nDiscover · CopyFiles · Prepare TGT · Setup TDE"]
        OC3["ZDM_RESTORE_TGT\ndirect pull over SQL*Net · source stays UP"]
        OC4["ZDM_RECOVER_TGT · ZDM_FINALIZE_TGT"]
        OC5["ZDM_CONFIGURE_DG_SRC\nData Guard standby · redo shipping · MRP apply\n⏸ pauseafter available here"]
        OC6["ZDM_SWITCHOVER_SRC · ZDM_SWITCHOVER_TGT\nsrc to PHYSICAL STANDBY · tgt to PRIMARY"]
        OC7["Datapatch · Post-migrate · Cleanup"]
        OC1 --> OC2 --> OC3 --> OC4 --> OC5 --> OC6 --> OC7
    end

    subgraph OFFLINE["OFFLINE — Non-Production · downtime required"]
        direction TB
        FC1["MIGRATION_METHOD=OFFLINE_PHYSICAL\nDATA_TRANSFER_MEDIUM=NFS\nNFS share mounted on src + tgt"]
        FC2["Prechecks · Setup · Validate"]
        FC3["ZDM_BACKUP_SRC\nRMAN backup written to NFS"]
        FC4["ZDM_TRANSFER_BACKUP\nbackup transferred via NFS · routed via NVA"]
        FC5["ZDM_RESTORE_TGT\nRMAN restore from NFS · no Data Guard"]
        FC6["ZDM_RECOVER_TGT · ZDM_FINALIZE_TGT"]
        FC7["ZDM_SWITCHOVER_SRC · ZDM_SWITCHOVER_TGT\ntgt becomes PRIMARY"]
        FC8["Datapatch · Post-migrate · Cleanup"]
        FC1 --> FC2 --> FC3 --> FC4 --> FC5 --> FC6 --> FC7 --> FC8
    end

    ZDM -->|"SSH :22 · ONLINE control plane"| ONLINE
    ZDM -->|"SSH :22 · OFFLINE control plane"| OFFLINE
    ZDM -->|"SSH :22 · ONLINE to src"| SD
    ZDM -->|"SSH :22 · OFFLINE to src"| SD
    ZDM -->|"SSH :22 · ONLINE to tgt nodes"| N1
    ZDM -->|"SSH :22 · ONLINE to tgt nodes"| N2
    ZDM -->|"SSH :22 · OFFLINE to tgt nodes"| N1
    ZDM -->|"SSH :22 · OFFLINE to tgt nodes"| N2

    SD -->|"SQL*Net :1521 · ONLINE"| NET
    SD -->|"SQL*Net :1521 · OFFLINE"| NET

    SD -->|"OFFLINE: RMAN backup to NFS"| NFS
    NFS -->|"OFFLINE: NFS traffic via NVA"| NVA

    OC3 -->|"ONLINE: direct pull SQL*Net"| TD
    OC5 -->|"ONLINE: redo shipping"| TD
    OC6 -->|"ONLINE: cutover"| AZ
    FC4 -->|"OFFLINE: NFS restore"| TD
    FC7 -->|"OFFLINE: cutover"| AZ
```
