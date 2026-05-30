#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Find-AcEvoServer {
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) { return $found.DirectoryName }
    }
    return $null
}

Write-Host "Installation PitLane Agent avec service Windows natif..."

& (Join-Path $PSScriptRoot "setup-agent.ps1")

$AcEvoPath = Find-AcEvoServer
if (-not $AcEvoPath) {
    throw "AC EVO Dedicated Server introuvable apres installation."
}

$AgentPath = Join-Path $AcEvoPath "pitlane-agent"
if (-not (Test-Path $AgentPath)) {
    throw "Dossier agent introuvable : $AgentPath"
}

Write-Host "Injection du wrapper service dans $AgentPath"
Copy-Item -Path (Join-Path $RepoRoot "agent\service.py") -Destination (Join-Path $AgentPath "service.py") -Force

Write-Host "Migration de la tache planifiee vers service Windows..."
& (Join-Path $RepoRoot "tools\install-service.ps1") -AgentPath $AgentPath

[System.Windows.Forms.MessageBox]::Show(
    "PitLane Agent est installe comme service Windows natif.`n`nVerification : Get-Service PitLaneAgent",
    "Installation terminee",
    "OK",
    "Information"
) | Out-Null
