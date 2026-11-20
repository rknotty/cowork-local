<#
.SYNOPSIS
    Proves the sandbox cannot reach the network or the host's drives
    (plan section 9 exit test and section 13 control 3).

.DESCRIPTION
    Each check must FAIL to connect for the test to PASS. Writes the evidence
    to docs/evidence/sandbox-egress-<timestamp>.txt.
#>
[CmdletBinding()]
param([string] $DistributionName = "local-cowork-sandbox")

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidencePath = Join-Path $repositoryRoot "docs\evidence\sandbox-egress-$timestamp.txt"

$checks = [ordered]@{
    "HTTPS download is refused"    = "/home/sandbox/venv/bin/python -c `"import urllib.request; urllib.request.urlopen('https://www.microsoft.com', timeout=10)`""
    "DNS lookup is refused"        = "/home/sandbox/venv/bin/python -c `"import socket; socket.gethostbyname('www.microsoft.com')`""
    "Windows C: drive is not mounted" = "ls /mnt/c/Windows"
    "Windows executables cannot launch" = "cmd.exe /c echo reachable"
}

$lines = @("Sandbox isolation test $timestamp", "")
$isAllPassed = $true
foreach ($check in $checks.GetEnumerator()) {
    $output = wsl.exe --distribution $DistributionName --user sandbox -- sh -c $check.Value 2>&1 | Out-String
    $isBlocked = $LASTEXITCODE -ne 0
    if (-not $isBlocked) { $isAllPassed = $false }
    $status = if ($isBlocked) { "PASS" } else { "FAIL" }
    $lines += "[$status] $($check.Key) (exit $LASTEXITCODE)"
    $lines += "    $($output.Trim() -replace "`r?`n", ' | ')"
}
$lines += ""
$lines += "Overall: $(if ($isAllPassed) { 'PASS' } else { 'FAIL' })"
$lines | Set-Content -Encoding utf8 $evidencePath
$lines | Write-Output
if (-not $isAllPassed) { exit 1 }
