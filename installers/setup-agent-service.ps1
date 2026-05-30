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

function Find-SteamCmd {
    $knownPaths = @(
        "C:\SteamCMD\steamcmd.exe",
        "D:\SteamCMD\steamcmd.exe",
        "C:\steamcmd\steamcmd.exe",
        "D:\steamcmd\steamcmd.exe"
    )

    foreach ($path in $knownPaths) {
        if (Test-Path $path) { return $path }
    }

    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
            -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    return $null
}

function Get-AppManifestPath {
    param([string]$AcEvoPath, [string]$SteamCmdExePath)

    if ($AcEvoPath) {
        $normalized = $AcEvoPath -replace '/', '\'
        if ($normalized -match '\\steamapps\\common\\') {
            $steamapps = $normalized -replace '\\common\\.*$', ''
            return (Join-Path $steamapps "appmanifest_4564210.acf")
        }
    }

    if ($SteamCmdExePath) {
        return (Join-Path (Split-Path $SteamCmdExePath) "steamapps\appmanifest_4564210.acf")
    }

    return ""
}

function Download-Agent {
    param([string]$DestinationPath)

    $url = "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/agent.zip"
    $zip = "$env:TEMP\pitlane-agent.zip"

    if (Test-Path $DestinationPath) {
        Remove-Item -Path $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $DestinationPath -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

function New-JwtSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-PublicIp {
    try {
        $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()
        if ($ip) { return $ip }
    } catch {}
    return "IP_A_REMPLACER"
}

Write-Host "Installation PitLane Agent avec service Windows natif..."

$AcEvoPath = Find-AcEvoServer
if (-not $AcEvoPath) {
    [System.Windows.Forms.MessageBox]::Show(
        "AC EVO Dedicated Server introuvable. Lance setup-full.ps1 pour une installation complete.",
        "Erreur",
        "OK",
        "Error"
    ) | Out-Null
    exit 1
}

$AgentPath = Join-Path $AcEvoPath "pitlane-agent"
$SteamCmdExe = Find-SteamCmd
$AppManifestPath = Get-AppManifestPath -AcEvoPath $AcEvoPath -SteamCmdExePath $SteamCmdExe

Write-Host "Telechargement agent vers $AgentPath"
Download-Agent -DestinationPath $AgentPath

Copy-Item -Path (Join-Path $RepoRoot "agent\service.py") -Destination (Join-Path $AgentPath "service.py") -Force

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python absent - installation via winget"
    winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "Generation config.yml"
$JwtSecret = New-JwtSecret
$publicIp = Get-PublicIp
$BaseUrl = "http://$publicIp"
$AgentUrl = "http://$publicIp`:8181"

$configContent = Get-Content (Join-Path $AgentPath "config.template.yml") -Raw
$configContent = $configContent.Replace("__BASE_URL__", $BaseUrl)
$configContent = $configContent.Replace("__INSTALL_PATH__", $AcEvoPath)
$configContent = $configContent.Replace("__CONFIGS_PATH__", "$AcEvoPath/configs")
$configContent = $configContent.Replace("__RESULTS_PATH__", "$AcEvoPath/Results")
$configContent = $configContent.Replace("__LOGS_PATH__", "$AcEvoPath/logs")
$configContent = $configContent.Replace("__STEAMCMD_PATH__", $SteamCmdExe)
$configContent = $configContent.Replace("__APPMANIFEST_PATH__", $AppManifestPath)
$configContent = $configContent.Replace("__JWT_SECRET__", $JwtSecret)
Set-Content -Path (Join-Path $AgentPath "config.yml") -Value $configContent -Encoding UTF8
Remove-Item (Join-Path $AgentPath "config.template.yml") -Force -ErrorAction SilentlyContinue

foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
}

Write-Host "Installation service Windows PitLaneAgent"
& (Join-Path $RepoRoot "tools\install-service.ps1") -AgentPath $AgentPath

Get-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -Direction Inbound `
    -Protocol TCP -LocalPort 8181 -Action Allow `
    -ErrorAction SilentlyContinue | Out-Null

[System.Windows.Forms.MessageBox]::Show(
    "PitLane Agent est installe comme service Windows natif.`n`nAgent URL : $AgentUrl`nJWT Secret : $JwtSecret",
    "Installation terminee",
    "OK",
    "Information"
) | Out-Null
