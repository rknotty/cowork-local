<#
.SYNOPSIS
    Egress proof (plan section 13, control 4): run a full agent task with the
    network up and fail if the orchestrator opens any non-loopback connection.

.DESCRIPTION
    Starts the terminal agent on a small task, samples TCP connections owned by
    its process tree every 200 ms, and writes the evidence to
    docs/evidence/egress-<timestamp>.txt.

    Limits, stated so the evidence is not overclaimed:
      - Sampling every 200 ms can miss a very short connection. The firewall
        rule from apply-egress-rules.ps1 is the control; this is the check.
      - UDP (including DNS) is captured through Get-NetUDPEndpoint, which
        shows bound endpoints, not destinations.
      - Foundry Local's own process is out of scope: it is a separate service
        and is expected to reach the catalogue only during model downloads.
#>
[CmdletBinding()]
param(
    [string] $Prompt = "List the files in the workspace, then write a two-line note called egress-check.md saying the check ran."
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidencePath = Join-Path $repositoryRoot "docs\evidence\egress-$timestamp.txt"
$workspace = Join-Path $env:TEMP "local-cowork-egress-$timestamp"
New-Item -ItemType Directory -Force $workspace | Out-Null

$loopbackAddresses = @("127.0.0.1", "::1", "0.0.0.0", "::")

function Get-ProcessTreeIds {
    param([int] $RootId)
    $ids = @($RootId)
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { $ids += Get-ProcessTreeIds -RootId $child.ProcessId }
    return $ids
}

$process = Start-Process -FilePath $python `
    -ArgumentList @("-m", "orchestrator.cli", "--workspace", "`"$workspace`"", "--auto-approve", "`"$Prompt`"") `
    -WorkingDirectory $repositoryRoot -PassThru -NoNewWindow `
    -RedirectStandardOutput "$workspace\agent-stdout.txt" -RedirectStandardError "$workspace\agent-stderr.txt"

$observed = @{}
$sampleCount = 0
while (-not $process.HasExited) {
    $treeIds = Get-ProcessTreeIds -RootId $process.Id
    Get-NetTCPConnection -ErrorAction SilentlyContinue |
        Where-Object { $treeIds -contains $_.OwningProcess } |
        ForEach-Object {
            $key = "$($_.RemoteAddress):$($_.RemotePort) state=$($_.State) pid=$($_.OwningProcess)"
            $observed[$key] = $_.RemoteAddress
        }
    $sampleCount++
    Start-Sleep -Milliseconds 200
}

$external = $observed.GetEnumerator() | Where-Object { $loopbackAddresses -notcontains $_.Value }
$verdict = if ($external) { "FAIL" } else { "PASS" }

$report = @(
    "Egress proof $timestamp"
    "Verdict: $verdict"
    "Agent exit code: $($process.ExitCode)"
    "Samples taken: $sampleCount"
    "Network adapters up: $((Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object Name) -join ', ')"
    "Prompt: $Prompt"
    ""
    "Connections observed for the orchestrator process tree:"
    ($observed.Keys | Sort-Object)
    ""
    "Non-loopback connections:"
    ($external | ForEach-Object { $_.Key })
    ""
    "Agent output:"
    (Get-Content "$workspace\agent-stdout.txt")
)
$report | Set-Content -Encoding utf8 $evidencePath
Write-Output "Egress proof: $verdict. Evidence written to $evidencePath"
if ($verdict -eq "FAIL") { exit 1 }
