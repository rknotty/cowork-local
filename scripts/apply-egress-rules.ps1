<#
.SYNOPSIS
    Blocks outbound network for the orchestrator and the sandbox (plan section 13, control 3).

.DESCRIPTION
    Run from an ELEVATED PowerShell. On an SCC-managed device, firewall changes
    may be overridden by policy; confirm with IT.

    1. A Windows Firewall outbound block rule for the virtual environment's
       python.exe, which runs the orchestrator. Loopback traffic to Foundry
       Local on 127.0.0.1 is not affected by outbound rules.
    2. A Hyper-V firewall outbound block for WSL, covering the sandbox
       distribution.

    Model downloads are the one legitimate network use. Foundry Local runs as
    its own process and is not blocked here: download models as a separate,
    deliberate step, then go offline.

    UNVERIFIED ON THIS DEVICE: the Hyper-V firewall cmdlets for WSL are
    documented for x64 Windows 11. Their behaviour on Arm64 has not been
    confirmed. Always run scripts/test-sandbox-egress.ps1 afterwards and keep
    its output as evidence.
#>
[CmdletBinding()]
param(
    [string] $RuleGroup = "Local Cowork egress block"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$orchestratorPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

# A venv python.exe is a launcher; the real interpreter is the base install.
$basePython = & $orchestratorPython -c "import sys; print(sys._base_executable)"

foreach ($program in @($orchestratorPython, $basePython) | Select-Object -Unique) {
    New-NetFirewallRule `
        -DisplayName "Local Cowork: block outbound for $(Split-Path -Leaf (Split-Path -Parent $program))" `
        -Group $RuleGroup `
        -Direction Outbound `
        -Program $program `
        -Action Block `
        -RemoteAddress "Internet" | Out-Null
    Write-Output "Outbound blocked to the internet for $program"
}

# WSL's well-known VM creator ID for the Hyper-V firewall.
$wslVmCreatorId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
try {
    Set-NetFirewallHyperVVMSetting -Name $wslVmCreatorId -DefaultOutboundAction Block
    Write-Output "Hyper-V firewall: WSL default outbound action set to Block"
} catch {
    Write-Warning "Hyper-V firewall rule could not be applied: $($_.Exception.Message)"
    Write-Warning "The sandbox is NOT network-isolated. Do not run generated code until this is resolved."
    exit 1
}
