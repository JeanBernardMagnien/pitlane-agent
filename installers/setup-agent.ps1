#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LegacyCommit = "0eb73569361c99256135d644da94b3e36c548e37"

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

Write-Host "PitLane Agent - installation service Windows natif"
Write-Host "Lancement de l'installateur agent historique..."

$legacyInstaller = Join-Path $env:TEMP "pitlane-setup-agent-legacy.ps1"
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/$LegacyCommit/installers/setup-agent.ps1" `
    -OutFile $legacyInstaller `
    -UseBasicParsing

& powershell.exe -ExecutionPolicy Bypass -File $legacyInstaller

$AcEvoPath = Find-AcEvoServer
if (-not $AcEvoPath) {
    throw "AC EVO Dedicated Server introuvable apres installation."
}

$AgentPath = Join-Path $AcEvoPath "pitlane-agent"
if (-not (Test-Path $AgentPath)) {
    throw "Dossier agent introuvable : $AgentPath"
}

Write-Host "Copie du service.py vers $AgentPath"
Copy-Item -Path (Join-Path $RepoRoot "agent\service.py") -Destination (Join-Path $AgentPath "service.py") -Force

Write-Host "Migration tache planifiee -> service Windows"
& (Join-Path $RepoRoot "tools\install-service.ps1") -AgentPath $AgentPath

[System.Windows.Forms.MessageBox]::Show(
    "PitLane Agent est maintenant installe comme service Windows natif.`n`nVerification : Get-Service PitLaneAgent",
    "Installation terminee",
    "OK",
    "Information"
) | Out-Null
