

Deploy the Azure Migrate Appliance on-premise. It automatically discovers inventory, dependencies, and hardware/software specs, then exports a complete assessment report.

To compile a comprehensive Hardware and Software Bill of Materials (HBOM/SBOM) and execute a migration, the standard path forward relies on the Azure Migrate appliance. This lightweight VM automates the discovery of workload components, dependencies, and configuration data across your on-premises environment.  
Azure Migrate Appliance Architecture. Source: Microsoft Learn
Azure Migrate Solution Strategy

The migration process requires executing the following phases in strict order to ensure no undocumented dependencies are left behind.

1
Deploy the Azure Migrate Appliance
VMware, Hyper-V, or Physical

Download the appliance OVA/VHD from the Azure portal and deploy it in your on-premises datacenter. Connect it to your vCenter Server or Hyper-V hosts using read-only credentials. The appliance operates agentlessly and communicates securely with Azure over outbound port 443.
2
Run Agentless Discovery and Software Inventory

Once connected, the appliance continuously profiles your on-premises servers. It captures the exact metadata needed for your HBOM and SBOM:

    Hardware (HBOM): CPU cores, memory utilization, disk IOPS, network throughput, and hardware specs.

    Software (SBOM): Installed applications, roles, SQL server instances, and active network connections.

3
Export the BOM and Run Assessments

With discovery complete, navigate to the Azure Migrate hub and export the application inventory list. This serves as your foundational SBOM/HBOM. Next, create an Azure Assessment. The assessment analyzes your inventory against Azure support policies to identify migration blockers, right-size Azure VM SKUs based on actual performance data, and estimate monthly costs.
4
Perform Dependency Analysis and Wave Planning

Enable dependency analysis to visualize cross-server communication. This identifies which servers must migrate together to prevent application breakage. Group these interdependent servers into high-confidence "Migration Waves".
5
Execute Replication and Cutover

Use the Azure Migrate: Server Migration tool to begin replicating the servers in your first wave. Perform a test migration in an isolated Azure VNet to validate functionality, then execute the final cutover during a scheduled maintenance window.



If you are running bare-metal physical servers—or an unsupported hypervisor like KVM or Xen—the hypervisor-level appliance won't work. You must use the Physical Server deployment model instead.

Here is how you extract your HBOM and SBOM directly from the OS level:

1
Provision an Appliance Host

Spin up a single Windows Server 2022 (or 2019) machine in your environment. This dedicated machine will act as your local Azure Migrate appliance.
2
Run the Installer Script

Download the compressed installer file from the Azure Portal, extract it on your new Windows Server, and run the AzureMigrateInstaller.ps1 script to install the discovery tools natively.
3
Provide IPs and Credentials

Instead of connecting to a hypervisor, log into the appliance's web interface and input the IP addresses (or subnets) of your target servers. You must also supply WMI credentials for Windows targets and SSH credentials for Linux targets.
4
Execute OS-Level Discovery

The appliance logs directly into the OS of each server to pull the data. It maps installed software (SBOM), active dependencies, performance metrics, and hardware specs (HBOM) from the inside out, which you can then export from the Azure Portal.

Need the specific port and firewall requirements to allow this OS-level discovery?

Not strictly. The deployment is dictated by network boundaries and capacity limits, not physical locations.

You can use a single appliance to scan multiple datacenters as long as you meet these constraints:

    Line-of-Sight: The appliance must be able to route to the target OS in every datacenter. For physical server discovery, this means opening WMI (Port 5985/5986 for Windows) and SSH (Port 22 for Linux) across your WAN or VPN.

    Scale Limits: A single appliance can discover a maximum of 1,000 physical servers. If your total estate across all datacenters exceeds this, you must deploy additional appliances.

    Latency: High latency between the appliance and the target servers can cause discovery timeouts.

Best Practice

Despite being able to span datacenters, deploying one appliance per datacenter is the standard solution strategy.

It prevents you from having to open sensitive management ports (WMI/SSH) across your WAN links, avoids timeout issues, and crucially, keeps the heavy data replication traffic localized to that specific datacenter when you move from the discovery phase to the actual migration phase.

I HAVE A MIX OF LINUX AND WINDOWS SERVERS IN THE ONE/SINGLE DATACENTER THAT I AM DEFINING AS "ON-PREM"

A single appliance is all you need. The Windows-based Azure Migrate appliance natively handles both Windows and Linux targets simultaneously from that one location.

Here is how it processes a mixed-OS environment:

1
Input All Credentials

In the appliance configuration manager, add both your Windows credentials (Domain or Local Admin for WMI access) and your Linux credentials (SSH account with sudo privileges). You can add multiple credential sets if you have different passwords or SSH keys across the estate.
2
Provide the Datacenter IPs

Feed the appliance your datacenter's IP subnets, ranges, or upload a CSV of specific IP addresses.
3
Automatic Mapping and Discovery

You do not need to manually specify which IP corresponds to which OS. The appliance automatically tests the IP addresses against the provided credential sets via WMI (Port 5985/5986) and SSH (Port 22) until it successfully authenticates.
4
Unified BOM Generation

Once authenticated, the appliance executes OS-specific commands internally to extract the hardware and software data, rolling both Windows and Linux servers into a single, unified HBOM/SBOM inventory in the Azure Portal.

AUTOMATION SCRIPT WITH COMMANDS TO DEPLOY INTO MY ON-PREM DATACENTER

Run this PowerShell script as Administrator on your designated Windows Server 2019/2022 appliance host to download, extract, and execute the Azure Migrate setup for physical/bare-metal environments.
PowerShell

# ==============================================================================
# Azure Migrate Physical Appliance Installer Automation
# Run this on a dedicated Windows Server 2019/2022 with Internet Connectivity
# ==============================================================================

# 1. Set Execution Policy
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Force

# 2. Define Work Directory and Download URI
$WorkDir = "C:\AzureMigrateAppliance"
$ZipPath = "$WorkDir\AzureMigrateInstaller.zip"
# Official Microsoft Direct Link for Azure Migrate Physical Installer
$DownloadUrl = "https://go.microsoft.com/fwlink/?linkid=2140156" 

# 3. Create Working Directory
if (-not (Test-Path -Path $WorkDir)) {
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
}
Set-Location -Path $WorkDir

# 4. Download Azure Migrate Installer Package
Write-Host "Downloading Azure Migrate Installer..." -ForegroundColor Green
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath -UseBasicParsing

# 5. Extract Zip Package
Write-Host "Extracting files to $WorkDir..." -ForegroundColor Green
Expand-Archive -Path $ZipPath -DestinationPath $WorkDir -Force

# 6. Execute Installer for Physical/Bare-Metal Discovery
Write-Host "Starting Azure Migrate Installer..." -ForegroundColor Green
Set-Location -Path $WorkDir
.\AzureMigrateInstaller.ps1 -Scenario Physical

Deployment Workflow

    Copy & Run: Execute the script above on the host machine.

    Access Configuration UI: Once the script completes, open a browser on the host machine and go to:
    https://localhost:44368

    Register Appliance:

        Complete the automated prerequisite check (NTP time sync, Azure connectivity, PowerShell utility validation).

        Log into your Azure account and paste your Azure Migrate Project Key generated from the Azure Portal.

    Add Target Credentials:

        Windows Credentials: Add Domain or Local Admin user (Username, Password).

        Linux Credentials: Add SSH user with sudo access or SSH key (Username, Password or Private Key).

    Start Discovery: Input your target server IP addresses or upload a CSV containing the IP ranges, then hit Start Discovery.

HOW WILL IT DISCOVER APP SERVER, DB SERVERS, MIDDLEWARE SERVERS ETC? ANY SPECIFIC FIREWALL PORTS TO OPEN?

The Azure Migrate appliance discovers specialized workloads agentlessly from the OS layer up. Once authenticated, it runs native scripts to query installed software, web servers, databases, and network sockets.  
1. How Workloads are Discovered

    Software Inventory (SBOM): The appliance executes remote commands (PowerShell/WMI on Windows; SSH shell scripts on Linux) to scan system registries (HKLM\Software), package managers (rpm, dpkg, yum), and running services.

    DB Servers (SQL Server): The appliance automatically detects installed SQL instances. Using the SQL or Windows credentials provided in the configuration manager, it queries SQL metadata to inventory database names, configurations, and performance metrics.  

    Middleware & Web Servers (IIS, Tomcat): It scans for web roles. For Windows, it reads applicationHost.config via WinRM to discover IIS web apps. For Linux, it checks Tomcat/Java installations and directory structures via SSH.  

    Dependency Analysis (App-to-DB Mapping): The appliance polls TCP connection data from each server's OS socket table every 5 minutes. This maps active network connections, process names, and destination ports to visually connect App servers to their backend DB servers.  

2. Firewall Port Requirements

For discovery to work, open the following network ports from the Azure Migrate Appliance host to your target servers and Azure:  
Source	Destination	Protocol / Port	Purpose
Appliance	Windows Servers	TCP 5986 (HTTPS) or 5985 (HTTP)	WinRM (Default method for PowerShell remoting & WMI discovery)
Appliance	Windows Servers	TCP 135 + Dynamic RPC (49152–65535)	RPC / WMI (Fallback for legacy Windows discovery)
Appliance	SQL Servers	TCP 1433 (SQL) & UDP 1434 (Browser)	Direct connection for deep SQL instance and DB metadata discovery
Appliance	Linux Servers	TCP 22	SSH connection for shell queries, inventory, and dependency polling
Appliance	Azure Cloud	TCP 443 (Outbound)	Encrypted HTTPS data transmission to the Azure Migrate project

    Key OS Prerequisites:

        Windows Targets: WinRM must be running (Enable-PSRemoting) and account must be part of Remote Management Users and Performance Monitor Users (or Local Admin).

        Linux Targets: Password or SSH key authentication must be enabled in /etc/ssh/sshd_config, and the account must have sudo or root privileges.  

Want the specific SQL credential and permission setup needed for database discovery?

WTFDYM

In plain English: You do not need to install agents or software on any of your target servers.

The appliance works like a remote admin:

    It Logs In Remotely: You give the appliance an admin login. It uses WinRM for Windows and SSH for Linux to sign into your servers over the local network.

    It Reads the OS: Once logged in, it runs basic system queries to check installed software, database instances, and running services (generating your SBOM).

    It Maps Connections: It checks active network sockets on each server to see who is talking to whom. If Server A is sending traffic to Server B on port 1433, it flags Server B as Server A's database.

The firewall rules listed simply allow the appliance to make those remote management connections to your servers.

I NEED THE DETAILED FIREWALL RULES FOR INGRESS/EGRESS

Here are the complete ingress and egress firewall rules required for the Azure Migrate Physical Appliance.
1. Ingress (Inbound) Rules to Appliance Host

Traffic coming into the Azure Migrate Appliance host:
Source	Target	Protocol / Port	Purpose
Admin Workstation	Appliance Host	TCP 44368	Local Web Appliance Configuration Manager UI
Admin Workstation	Appliance Host	TCP 3389	Remote Desktop (RDP) for host administration
2. Egress (Outbound) Rules: Appliance → On-Prem Target Servers

Traffic from the Appliance Host to your Internal Server Subnets:
Source	Target	Protocol / Port	Purpose
Appliance Host	Windows Servers	TCP 5985 (HTTP) / 5986 (HTTPS)	WinRM (PowerShell remoting, software inventory, IIS apps)
Appliance Host	Windows Servers	TCP 135 + Dynamic 49152–65535	RPC / WMI fallback for legacy Windows discovery
Appliance Host	Linux Servers	TCP 22	SSH for shell queries, Linux SBOM, and web/middleware discovery
Appliance Host	SQL Servers	TCP 1433 (SQL)	SQL Server default instance discovery and metadata collection
Appliance Host	SQL Servers	UDP 1434 (Browser)	SQL Server named instances resolution
3. Egress (Outbound) Rules: Appliance → Azure Cloud (Internet)

All outbound Internet traffic from the Appliance Host uses TCP Port 443 (HTTPS). Allow access to the following domain endpoints (or use wildcards on your firewall/proxy):
Core Appliance & Azure Migrate Communication

    management.azure.com (Azure Resource Manager)  

    *.discoverysrv.windowsazure.com (Azure Migrate Discovery Service)  

    *.migration.windowsazure.com (Azure Migrate Migration Service)  

    *.servicebus.windows.net (Appliance to Azure Service Bus messaging)  

Authentication & Identity (Entra ID)

    *.portal.azure.com  

    login.microsoftonline.com / *.microsoftonline-p.com

    *.msftauth.net / *.msauth.net / *.microsoftazuread-sso.com

Keys & Updates

    *.vault.azure.net (Azure Key Vault secret management)  

    aka.ms/* (Appliance component auto-updates)  

    [download.microsoft.com/download](https://download.microsoft.com/download) (Download center binaries)

    *.services.visualstudio.com (Telemetry & diagnostic logs)  

Need a PowerShell script to test all these target server port connections automatically?

UPDATED AUTOMATION SCRIPT WITH ALL DETAILS !

Here is the updated, production-ready PowerShell automation script. It handles administrative elevation checks, enables TLS 1.2, configures local Windows Firewall rules, sets the registry for auto-dependency mapping, and deploys the Azure Migrate Physical appliance installer.  
PowerShell

<#
.SYNOPSIS
    Automated Deployment Script for Azure Migrate Physical Server Appliance Host.
.NOTES
    Run on dedicated Windows Server 2019/2022/2025 as Administrator.
#>

# 1. Ensure Administrative Elevation
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Script must be run as Administrator! Relaunching in elevated context..."
    Start-Process powershell -Verb RunAs -ArgumentList "-File `"$PSCommandPath`""
    exit
}

Write-Host "=== Starting Azure Migrate Appliance Host Setup ===" -ForegroundColor Cipher

# 2. Force TLS 1.2 Protocol & System Prerequisites
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Force

# 3. Configure Appliance Registry Settings (Auto-Enable Dependency Mapping)
$RegistryPath = "HKLM:\SOFTWARE\Microsoft\AzureAppliance"
if (-not (Test-Path $RegistryPath)) {
    New-Item -Path $RegistryPath -Force | Out-Null
}
Set-ItemProperty -Path $RegistryPath -Name "DepMapAutoEnable" -Value "true" -Type String

# 4. Open Local Inbound Firewall Ports on Appliance Host
Write-Host "Configuring Local Firewall Inbound Rules..." -ForegroundColor Cyan
New-NetFirewallRule -DisplayName "Azure Migrate Appliance Web UI" -Direction Inbound -Protocol TCP -LocalPort 44368 -Action Allow -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -DisplayName "Azure Migrate Appliance WinRM Inbound" -Direction Inbound -Protocol TCP -LocalPort 5985, 5986 -Action Allow -ErrorAction SilentlyContinue | Out-Null

# 5. Enable WinRM Service for Management
Enable-PSRemoting -Force -ErrorAction SilentlyContinue
Set-Service -Name WinRM -StartupType Automatic
Start-Service -Name WinRM -ErrorAction SilentlyContinue

# 6. Download and Prepare Azure Migrate Appliance Installer Package
$WorkDir   = "C:\AzureMigrateAppliance"
$ZipPath   = "$WorkDir\AzureMigrateInstaller.zip"
$SourceUrl = "https://go.microsoft.com/fwlink/?linkid=2140156" # Official Direct Link

if (-not (Test-Path -Path $WorkDir)) {
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
}

Write-Host "Downloading Azure Migrate Installer Zip Package..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $SourceUrl -OutFile $ZipPath -UseBasicParsing

Write-Host "Extracting Azure Migrate Package to $WorkDir..." -ForegroundColor Cyan
Expand-Archive -Path $ZipPath -DestinationPath $WorkDir -Force

# 7. Execute Appliance Installation Script
Set-Location -Path $WorkDir
if (Test-Path ".\AzureMigrateInstaller.ps1") {
    Write-Host "Executing AzureMigrateInstaller.ps1 for Physical Scenario..." -ForegroundColor Green
    # Runs the script for Physical/Bare-metal discovery scenario
    .\AzureMigrateInstaller.ps1 -Scenario Physical
} else {
    Write-Error "Installer script AzureMigrateInstaller.ps1 was not found in $WorkDir!"
    exit
}

# 8. Post-Install Instructions
Write-Host "`n=======================================================" -ForegroundColor Green
Write-Host "Appliance installation completed successfully." -ForegroundColor Green
Write-Host "Launch browser to configure: https://localhost:44368" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Green

STEPS TO RUN THIS

Here is the step-by-step process to execute the automation script and launch your appliance:

1
Log into Host Server as Administrator
Prerequisite

Log into your designated Windows Server 2019/2022 appliance host using an account with local administrative privileges.
2
Open Elevated PowerShell

Click Start, search for PowerShell, right-click Windows PowerShell, and select Run as administrator.
3
Execute the Script

Copy the PowerShell script, paste it directly into the elevated PowerShell prompt, and press Enter.

(Alternatively, save the code to C:\Deploy-Appliance.ps1 and run .\Deploy-Appliance.ps1)
4
Launch the Appliance Configuration Manager

Once the script finishes downloading and extracting components, open Chrome or Edge on the host machine and navigate to:

https://localhost:44368
5
Register Project and Add Credentials

    Complete the automated prerequisite check.

    Paste your Azure Migrate Project Key (generated from Azure Portal → Azure Migrate → Discover).

    Authenticate to your Azure account using the device code provided.

    Enter your Windows WMI and Linux SSH credential sets, add target IP ranges, and click Start Discovery.
