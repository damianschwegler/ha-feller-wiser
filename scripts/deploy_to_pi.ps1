<#
.SYNOPSIS
  Copy custom_components/feller_wiser to a Home Assistant host for quick iteration.

.EXAMPLE
  scripts/deploy_to_pi.ps1 -PiHost homeassistant.local -Method scp -Restart
  scripts/deploy_to_pi.ps1 -Method samba -SambaShare \\homeassistant\config

  -Restart needs $env:HA_TOKEN (long-lived access token) and calls homeassistant.restart.
#>
param(
    [string]$PiHost = "homeassistant.local",
    [ValidateSet("scp", "samba")] [string]$Method = "scp",
    [string]$SshUser = "root",
    [string]$SambaShare = "\\homeassistant\config",
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "custom_components\feller_wiser"

if ($Method -eq "scp") {
    ssh "$SshUser@$PiHost" "mkdir -p /config/custom_components && rm -rf /config/custom_components/feller_wiser"
    scp -r $source "$SshUser@${PiHost}:/config/custom_components/"
} else {
    $target = Join-Path $SambaShare "custom_components\feller_wiser"
    robocopy $source $target /MIR /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed with $LASTEXITCODE" }
}
Write-Host "Deployed feller_wiser to $PiHost"

if ($Restart) {
    if (-not $env:HA_TOKEN) { throw "Set HA_TOKEN to a long-lived access token" }
    Invoke-RestMethod -Method Post -Headers @{ Authorization = "Bearer $env:HA_TOKEN" } `
        -Uri "http://${PiHost}:8123/api/services/homeassistant/restart" | Out-Null
    Write-Host "Restart requested"
}
