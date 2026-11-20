<#
.SYNOPSIS
    Creates the dedicated WSL 2 sandbox distribution (plan section 9, steps 3-4).

.DESCRIPTION
    Run from an ELEVATED PowerShell after `wsl --install --no-distribution` and a
    reboot. On an SCC-managed device, enabling WSL needs IT approval first.

    What it does:
      1. Imports a fresh Ubuntu 24.04 rootfs as a distribution named
         local-cowork-sandbox, used for nothing else.
      2. Creates a non-root user `sandbox` and makes it the default.
      3. Installs Python, the document libraries and LibreOffice (needs network,
         once).
      4. Writes /etc/wsl.conf to disable Windows drive automount and interop, so
         code inside cannot see or launch anything on the host.
      5. Caps WSL memory at 4 GB in %UserProfile%\.wslconfig.
      6. Copies the builder scripts in and exports a clean image for restore.

    It does NOT create the Hyper-V firewall rule that blocks outbound traffic
    from the sandbox. Run scripts/apply-egress-rules.ps1 for that, then prove
    it with scripts/test-sandbox-egress.ps1.

.PARAMETER RootfsPath
    Path to an Ubuntu 24.04 Arm64 WSL rootfs tarball. Download it deliberately,
    as a separate step, and verify its checksum before use.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $RootfsPath,
    [string] $DistributionName = "local-cowork-sandbox",
    [string] $InstallRoot = "$env:LOCALAPPDATA\local-cowork\wsl",
    [int] $MemoryCapGb = 4
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Sandbox {
    param([string] $Command, [string] $User = "root")
    wsl.exe --distribution $DistributionName --user $User -- sh -c $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Sandbox command failed with exit code ${LASTEXITCODE}: $Command"
    }
}

if (-not (Test-Path $RootfsPath)) {
    throw "Rootfs not found: $RootfsPath"
}
$listed = (wsl.exe --list --quiet) -replace "`0", ""
if ($listed -contains $DistributionName) {
    throw "Distribution $DistributionName already exists. Unregister it first to rebuild."
}

New-Item -ItemType Directory -Force $InstallRoot | Out-Null
wsl.exe --import $DistributionName $InstallRoot $RootfsPath --version 2

Invoke-Sandbox "useradd --create-home --shell /bin/bash sandbox"
Invoke-Sandbox "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-venv libreoffice-writer-nogui libreoffice-impress-nogui libreoffice-calc-nogui fonts-dejavu-core"
Invoke-Sandbox "python3 -m venv /home/sandbox/venv && /home/sandbox/venv/bin/pip install python-docx python-pptx openpyxl" -User "sandbox"
Invoke-Sandbox "mkdir -p /home/sandbox/tools /home/sandbox/jobs" -User "sandbox"

# Drive automount and interop off: the host's files and executables are
# invisible from inside. Default user non-root.
$wslConf = @"
[automount]
enabled = false
mountFsTab = false

[interop]
enabled = false
appendWindowsPath = false

[user]
default = sandbox
"@
$wslConf | wsl.exe --distribution $DistributionName --user root -- sh -c "cat > /etc/wsl.conf"

# The interop setting only takes effect after a restart, and the share is the
# only route for copying the builders in once interop is off.
wsl.exe --terminate $DistributionName
$sharePath = "\\wsl.localhost\$DistributionName\home\sandbox\tools"
Copy-Item -Path (Join-Path $repositoryRoot "tools\*.py") -Destination $sharePath -Force

$wslConfigPath = Join-Path $env:USERPROFILE ".wslconfig"
if (Test-Path $wslConfigPath) {
    Write-Warning "$wslConfigPath exists. Check it sets memory=${MemoryCapGb}GB under [wsl2]; not overwritten."
} else {
    "[wsl2]`nmemory=${MemoryCapGb}GB`nswap=0`n" | Set-Content -Encoding utf8 $wslConfigPath
}

wsl.exe --terminate $DistributionName
$imagePath = Join-Path $InstallRoot "clean-image.tar"
wsl.exe --export $DistributionName $imagePath
Write-Output "Sandbox ready. Clean image exported to $imagePath"
Write-Output "Next: run scripts/apply-egress-rules.ps1, then set are_host_builders_allowed: false in config/tools.yaml."
