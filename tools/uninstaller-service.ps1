#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms

$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Find-AcEvoServer {
    $knownPaths = @(
        "C:\SteamCMD\steamapps\common",
        "D:\SteamCMD\steamapps\common",
        "C:\steamcmd\steamapps\common",
        "D:\steamcmd\steamapps\common"
    )

    foreach ($path in $knownPaths) {
        if (-not (Test-Path $path)) { continue }
        $found = Get-ChildItem -Path $path -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 3 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }

    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }

    return $null
}

$AcEvoPath = Find-AcEvoServer
$AgentPath = if ($AcEvoPath) { Join-Path $AcEvoPath "pitlane-agent" } else { Join-Path $RepoRoot "agent" }

Write-Host "Suppression du service PitLaneAgent si present..."
& (Join-Path $RepoRoot "tools\remove-service.ps1") -AgentPath $AgentPath

Write-Host "Lancement de l'uninstaller standard..."
& (Join-Path $RepoRoot "tools\uninstaller.ps1")
