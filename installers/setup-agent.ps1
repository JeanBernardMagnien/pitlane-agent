#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Utility functions

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

function Find-SteamRoot {
    Add-Log "Recherche Steam client dans le registre..."

    $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam" `
        -ErrorAction SilentlyContinue).InstallPath

    if (-not $path) {
        $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Valve\Steam" `
            -ErrorAction SilentlyContinue).InstallPath
    }

    if ($path) {
        Add-Log "Steam client trouve : $path"
    } else {
        Add-Log "Steam client non trouve."
    }

    return $path
}

function Find-SteamCmd {
    Add-Log "Recherche steamcmd.exe dans les chemins connus..."

    $knownPaths = @(
        "C:\SteamCMD\steamcmd.exe",
        "D:\SteamCMD\steamcmd.exe",
        "C:\steamcmd\steamcmd.exe",
        "D:\steamcmd\steamcmd.exe"
    )

    foreach ($path in $knownPaths) {
        if (Test-Path $path) {
            Add-Log "steamcmd.exe trouve : $path"
            return $path
        }
    }

    Add-Log "steamcmd.exe non trouve dans les chemins connus."
    Add-Log "Recherche sur les disques, cela peut prendre quelques secondes..."

    $drives = (Get-PSDrive -PSProvider FileSystem).Root

    foreach ($drive in $drives) {
        Add-Log "Recherche steamcmd.exe sur $drive ..."

        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
            -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($found) {
            Add-Log "steamcmd.exe trouve : $($found.FullName)"
            return $found.FullName
        }
    }

    Add-Log "Aucun steamcmd.exe trouve."
    return $null
}

function Get-AppManifestPath {
    param(
        [string]$AcEvoPath,
        [string]$SteamCmdExePath
    )

    if (-not [string]::IsNullOrWhiteSpace($AcEvoPath)) {
        $normalized = $AcEvoPath -replace '/', '\'

        if ($normalized -match '\\steamapps\\common\\') {
            $steamapps = $normalized -replace '\\common\\.*$', ''
            return (Join-Path $steamapps "appmanifest_4564210.acf")
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($SteamCmdExePath)) {
        $steamCmdDir = Split-Path $SteamCmdExePath

        if (-not [string]::IsNullOrWhiteSpace($steamCmdDir)) {
            return (Join-Path $steamCmdDir "steamapps\appmanifest_4564210.acf")
        }
    }

    throw "Impossible de deduire appmanifest_path depuis AcEvoPath='$AcEvoPath' et SteamCmdExePath='$SteamCmdExePath'"
}

function Download-Agent {
    param($DestinationPath)

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

function Install-AgentUpdater {
    param([string]$AgentPath)

    $url = "https://raw.githubusercontent.com/JeanBernardMagnien/pitlane-agent/feature/manual-agent-updater/installers/updater.exe"
    $toolsPath = Join-Path $AgentPath "tools"
    $updaterPath = Join-Path $toolsPath "PitLaneAgentUpdater.exe"

    New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null

    Invoke-WebRequest `
        -Uri $url `
        -OutFile $updaterPath `
        -UseBasicParsing
}

function New-JwtSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-PublicIp {
    try {
        $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()

        if ([string]::IsNullOrWhiteSpace($ip)) {
            return "IP_A_REMPLACER"
        }

        return $ip
    } catch {
        return "IP_A_REMPLACER"
    }
}

function Escape-ForYamlPath {
    param([string]$Path)

    if (-not $Path) { return "" }
    return $Path -replace '\\', '\\'
}

# Pre-check

$AcEvoPath = Find-AcEvoServer
if (-not $AcEvoPath) {
    [System.Windows.Forms.MessageBox]::Show(
        "AC EVO Dedicated Server introuvable. Lance setup-full.ps1 pour une installation complete.",
        "Erreur", "OK", "Error"
    )
    exit 1
}

# Main UI

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane Agent - Installation"
$form.Size = New-Object System.Drawing.Size(620, 760)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Installation de PitLane Agent"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(560, 28)
$form.Controls.Add($titleLabel)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 50)
$stepsPanel.Size = New-Object System.Drawing.Size(560, 345)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Detection AC EVO",
    "[2] Detection Steam / steamcmd",
    "[3] Deduction appmanifest",
    "[4] Telechargement agent",
    "[5] Verification Python",
    "[6] Installation dependances",
    "[7] Generation config.yml",
    "[8] Tache planifiee Windows",
    "[9] Regle firewall API agent",
    "[10] Termine"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "WAIT " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (6 + $i * 33))
    $lbl.Size = New-Object System.Drawing.Size(535, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 405)
$progressBar.Size = New-Object System.Drawing.Size(560, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 430)
$logBox.Size = New-Object System.Drawing.Size(560, 140)
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$form.Controls.Add($logBox)

function Set-StepStatus {
    param($index, $status)

    $label = $stepLabels[$index]
    $base = $steps[$index]

    switch ($status) {
        "running" { $label.Text = "> $base";     $label.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0) }
        "ok"      { $label.Text = "OK $base";    $label.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136) }
        "error"   { $label.Text = "ERROR $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(255, 68, 68) }
        "skip"    { $label.Text = "SKIP $base";  $label.ForeColor = [System.Drawing.Color]::FromArgb(110, 118, 129) }
    }

    $progressBar.Value = [Math]::Min($index + 1, $progressBar.Maximum)
    [System.Windows.Forms.Application]::DoEvents()
}

function Add-Log {
    param($msg)

    $logBox.AppendText("$msg`r`n")
    $logBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(470, 630)
$closeBtn.Size = New-Object System.Drawing.Size(110, 28)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$closeBtn.ForeColor = [System.Drawing.Color]::Black
$closeBtn.FlatStyle = "Flat"
$closeBtn.Visible = $false
$closeBtn.Add_Click({ $form.Close() })
$form.Controls.Add($closeBtn)

# Installation

$form.Add_Shown({
    $form.Activate()
    $JwtSecret = $null
    $SteamCmdExe = $null
    $AppManifestPath = ""

    # [1] Detection AC EVO
    Set-StepStatus 0 "running"
    $AgentPath = "$AcEvoPath\pitlane-agent"
    Add-Log "AC EVO detecte : $AcEvoPath"
    Set-StepStatus 0 "ok"

    # [2] Detection Steam / steamcmd
    Set-StepStatus 1 "running"
    $SteamRoot = Find-SteamRoot
    $SteamCmdExe = Find-SteamCmd

    if (-not $SteamCmdExe) {
        $cmdDir = "C:\SteamCMD"
        $SteamCmdExe = Join-Path $cmdDir "steamcmd.exe"

        Add-Log "steamcmd.exe introuvable - installation automatique dans $cmdDir"

        try {
            New-Item -ItemType Directory -Path $cmdDir -Force | Out-Null

            $zip = "$env:TEMP\steamcmd.zip"

            Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" `
                -OutFile $zip -UseBasicParsing

            Expand-Archive -Path $zip -DestinationPath $cmdDir -Force
            Remove-Item $zip -Force -ErrorAction SilentlyContinue

            if (-not (Test-Path $SteamCmdExe)) {
                throw "steamcmd.exe introuvable apres extraction : $SteamCmdExe"
            }

            Add-Log "steamcmd installe : $SteamCmdExe"
        } catch {
            Set-StepStatus 1 "error"
            [System.Windows.Forms.MessageBox]::Show(
                "Erreur installation steamcmd : $_",
                "Erreur", "OK", "Error"
            )
            return
        }
    } else {
        Add-Log "steamcmd trouve : $SteamCmdExe"
    }

    Set-StepStatus 1 "ok"

    # [3] Deduction appmanifest
    Set-StepStatus 2 "running"

    try {
        $AppManifestPath = Get-AppManifestPath -AcEvoPath $AcEvoPath -SteamCmdExePath $SteamCmdExe
        Add-Log "appmanifest : $AppManifestPath"
        Set-StepStatus 2 "ok"
    } catch {
        Set-StepStatus 2 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "$_",
            "Erreur appmanifest", "OK", "Error"
        )
        return
    }

    # [4] Telechargement agent
    Set-StepStatus 3 "running"
    try {
        Add-Log "Telechargement agent vers $AgentPath"
        Download-Agent -DestinationPath $AgentPath
        Install-AgentUpdater -AgentPath $AgentPath
        Set-StepStatus 3 "ok"
    } catch {
        Set-StepStatus 3 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "Echec du telechargement de l'agent : $_", "Erreur", "OK", "Error")
        return
    }

    # [5] Verification Python
    Set-StepStatus 4 "running"
    $python = Get-Command python -ErrorAction SilentlyContinue

    if (-not $python) {
        Add-Log "Python absent - installation via winget"
        winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Add-Log "Python trouve : $($python.Source)"
    }
    Set-StepStatus 4 "ok"

    # [6] Installation dependances
    Set-StepStatus 5 "running"
    Add-Log "pip install requirements"
    $pipOut = & python -m pip install -r "$AgentPath\requirements.txt" --quiet 2>&1
    Add-Log ($pipOut | Out-String).Trim()
    Set-StepStatus 5 "ok"

    # [7] Generation config.yml
    Set-StepStatus 6 "running"
    $JwtSecret = New-JwtSecret
    $publicIp = Get-PublicIp
    $BaseUrl = "http://$publicIp"
    $AgentUrl = "http://$publicIp`:8181"

    $configContent = Get-Content "$AgentPath/config.template.yml" -Raw
    $configContent = $configContent.Replace("__BASE_URL__", $BaseUrl)
    $configContent = $configContent.Replace("__INSTALL_PATH__", $AcEvoPath)
    $configContent = $configContent.Replace("__CONFIGS_PATH__", "$AcEvoPath/configs")
    $configContent = $configContent.Replace("__RESULTS_PATH__", "$AcEvoPath/Results")
    $configContent = $configContent.Replace("__LOGS_PATH__", "$AcEvoPath/logs")
    $configContent = $configContent.Replace("__STEAMCMD_PATH__", $SteamCmdExe)
    $configContent = $configContent.Replace("__APPMANIFEST_PATH__", $AppManifestPath)
    $configContent = $configContent.Replace("__JWT_SECRET__", $JwtSecret)
    Set-Content -Path "$AgentPath/config.yml" -Value $configContent -Encoding UTF8
    Remove-Item "$AgentPath/config.template.yml" -Force -ErrorAction SilentlyContinue

    foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir | Out-Null
        }
    }

    Add-Log "config.yml genere"
    Add-Log "config.template.yml supprime"
    Set-StepStatus 6 "ok"

    # [8] Tache planifiee
    Set-StepStatus 7 "running"
    Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction -Execute "python" `
        -Argument "`"$AgentPath\app.py`"" -WorkingDirectory $AgentPath
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

    Register-ScheduledTask -TaskName "PitLaneAgent" -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal | Out-Null

    Start-ScheduledTask -TaskName "PitLaneAgent"

    Add-Log "Tache planifiee PitLaneAgent creee"
    Add-Log "Agent PitLane demarre"
    Set-StepStatus 7 "ok"

    # [9] Regle firewall API agent
    Set-StepStatus 8 "running"

    Get-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    New-NetFirewallRule -DisplayName "PitLane - Agent API 8181" -Direction Inbound `
        -Protocol TCP -LocalPort 8181 -Action Allow `
        -ErrorAction SilentlyContinue | Out-Null
    Add-Log "Firewall : TCP/8181 ouvert (PitLane - Agent API 8181)"
    Add-Log "Les ports d'instances seront geres par le hub lors de la creation/modification/suppression."

    Set-StepStatus 8 "ok"

    # [10] Resume
    Set-StepStatus 9 "ok"

    $form.Size = New-Object System.Drawing.Size(620, 790)

    $summaryBox = New-Object System.Windows.Forms.Panel
    $summaryBox.Location = New-Object System.Drawing.Point(20, 585)
    $summaryBox.Size = New-Object System.Drawing.Size(560, 72)
    $summaryBox.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $summaryBox.BorderStyle = "FixedSingle"
    $form.Controls.Add($summaryBox)

    foreach ($row in @(
        @{ Label = "Agent URL : $AgentUrl"; CopyText = $AgentUrl; BtnText = "Copier URL"; Y = 8 },
        @{ Label = "JWT Secret : $($JwtSecret.Substring(0,20))..."; CopyText = $JwtSecret; BtnText = "Copier JWT"; Y = 38 }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $row.Label
        $lbl.Location = New-Object System.Drawing.Point(10, $row.Y)
        $lbl.Size = New-Object System.Drawing.Size(390, 20)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $summaryBox.Controls.Add($lbl)

        $ct = $row.CopyText
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $row.BtnText
        $btn.Location = New-Object System.Drawing.Point(410, ($row.Y - 2))
        $btn.Size = New-Object System.Drawing.Size(90, 24)
        $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $btn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $btn.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($ct) }.GetNewClosure())
        $summaryBox.Controls.Add($btn)
    }

    $yNext = 665
    if (-not $SteamCmdExe) {
        $warnLbl = New-Object System.Windows.Forms.Label
        $warnLbl.Text = "WARNING steamcmd non detecte - mise a jour distante desactivee"
        $warnLbl.Location = New-Object System.Drawing.Point(20, $yNext)
        $warnLbl.Size = New-Object System.Drawing.Size(560, 20)
        $warnLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
        $form.Controls.Add($warnLbl)
        $yNext += 28
        $form.Size = New-Object System.Drawing.Size(620, ($yNext + 95))
    }

    $msgLbl = New-Object System.Windows.Forms.Label
    $msgLbl.Text = "Rends-toi dans le hub PitLane pour ajouter ce serveur."
    $msgLbl.Location = New-Object System.Drawing.Point(20, $yNext)
    $msgLbl.Size = New-Object System.Drawing.Size(430, 20)
    $msgLbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $form.Controls.Add($msgLbl)

    $closeBtn.Location = New-Object System.Drawing.Point(470, $yNext)
    $closeBtn.Visible = $true
    [System.Windows.Forms.Application]::DoEvents()
})

[System.Windows.Forms.Application]::Run($form)
