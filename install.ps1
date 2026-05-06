[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
####################################################################
# PitLane Server Agent - Script d'installation automatique
# A placer dans le dossier pitlane-server-agent, lui meme dans le
# dossier d'installation d'AC EVO
# Usage : .\install.ps1
####################################################################

$AgentPath   = $PSScriptRoot
$SteamPath   = Split-Path $PSScriptRoot -Parent
$ConfigsPath = "$SteamPath\configs"
$ResultsPath = "$SteamPath\Results"
$LogsPath    = "$SteamPath\logs"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PitLane Server Agent - Installation  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Agent  : $AgentPath" -ForegroundColor Gray
Write-Host "  Serveur: $SteamPath" -ForegroundColor Gray
Write-Host ""

# --- 1. Verification / Installation Python ---
Write-Host "[1/6] Verification de Python..." -ForegroundColor Yellow

$pythonExists = Get-Command python -ErrorAction SilentlyContinue

if (-not $pythonExists) {
    Write-Host "      Python introuvable, installation via winget..." -ForegroundColor Yellow
    winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements

    # Recharger le PATH pour que python soit dispo dans la session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    $pythonExists = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonExists) {
        Write-Host "      ERREUR : installation Python echouee, installe manuellement depuis python.org" -ForegroundColor Red
        exit 1
    }
    Write-Host "      OK : Python installe" -ForegroundColor Green
} else {
    $pythonVersion = python --version 2>&1
    Write-Host "      OK : $pythonVersion" -ForegroundColor Green
}

python -m pip install --upgrade pip --quiet
Write-Host "      OK : pip a jour" -ForegroundColor Green

# --- 2. Creation des dossiers ---
Write-Host "[2/6] Creation des dossiers..." -ForegroundColor Yellow

$folders = @($ConfigsPath, $ResultsPath, $LogsPath)
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
        Write-Host "      Cree : $folder" -ForegroundColor Green
    } else {
        Write-Host "      Deja existant : $folder" -ForegroundColor Gray
    }
}

# --- 3. Installation des dependances Python ---
Write-Host "[3/6] Installation des dependances Python..." -ForegroundColor Yellow

Set-Location $AgentPath
pip install -r requirements.txt --quiet

if ($LASTEXITCODE -eq 0) {
    Write-Host "      OK : dependances installees" -ForegroundColor Green
} else {
    Write-Host "      ERREUR : pip install a echoue" -ForegroundColor Red
    exit 1
}

# --- 4. Configuration ---
Write-Host "[4/6] Configuration..." -ForegroundColor Yellow

if (-not (Test-Path "$AgentPath\config.yml")) {
    if (Test-Path "$AgentPath\config.example.yml") {
        $config = Get-Content "$AgentPath\config.example.yml" -Raw

        # Remplacement automatique des chemins
        $config = $config.Replace('INSTALL_PATH', $SteamPath)
        $config = $config.Replace('CONFIGS_PATH', $ConfigsPath)
        $config = $config.Replace('RESULTS_PATH', $ResultsPath)
        $config = $config.Replace('LOGS_PATH',    $LogsPath)

        $config | Set-Content "$AgentPath\config.yml" -Encoding UTF8

        Write-Host "      config.yml genere avec les chemins automatiques" -ForegroundColor Green
        Write-Host "      /!\ Pense a editer config.yml (jwt_secret, base_url)" -ForegroundColor Yellow
    } else {
        Write-Host "      ERREUR : config.example.yml introuvable" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "      config.yml deja present, chemins non modifies" -ForegroundColor Gray
}

# --- 5. Tache planifiee ---
Write-Host "[5/6] Installation de la tache planifiee..." -ForegroundColor Yellow

$taskName = "PitLaneAgent"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "      Ancienne tache supprimee" -ForegroundColor Gray
}

$pythonPath = (where.exe python 2>$null | Select-Object -First 1)
if (-not $pythonPath) {
    $pythonPath = (Get-Command python).Source
}

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$AgentPath\app.py`"" -WorkingDirectory $AgentPath
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "      OK : tache 'PitLaneAgent' creee" -ForegroundColor Green

# --- 6. Ports firewall ---
Write-Host "[6/6] Ouverture des ports firewall Windows..." -ForegroundColor Yellow

$configContent = Get-Content "$AgentPath\config.yml" -Raw
$agentPort = if ($configContent -match 'port:\s*(\d+)') { $matches[1] } else { "8180" }

$ruleName = "PitLane Agent"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $agentPort -Action Allow | Out-Null
    Write-Host "      Port $agentPort (agent Flask) ouvert" -ForegroundColor Green
} else {
    Write-Host "      Port $agentPort deja ouvert" -ForegroundColor Gray
}

# --- Resume ---
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation terminee !" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Prochaines etapes :" -ForegroundColor White
Write-Host "  1. Edite config.yml (jwt_secret, base_url)" -ForegroundColor White
Write-Host "  2. Redemarre le serveur ou lance : python app.py" -ForegroundColor White
Write-Host "  3. Ajoute ce serveur dans le hub PitLane" -ForegroundColor White
Write-Host ""

# --- Suppression du script ---
Write-Host "  Nettoyage..." -ForegroundColor Gray
Remove-Item -Path "$AgentPath\install.ps1" -Force
Write-Host "  install.ps1 supprime" -ForegroundColor Gray
Write-Host ""

Read-Host "  Appuie sur Entree pour fermer"