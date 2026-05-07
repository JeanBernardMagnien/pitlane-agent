#Requires -RunAsAdministrator
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ─── Fonctions utilitaires ──────────────────────────────────────────────────

function Find-AcEvoServer {
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
                               -Recurse -Depth 6 -ErrorAction SilentlyContinue `
                               | Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }
    return $null
}

function Find-SteamRoot {
    $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam" `
                               -ErrorAction SilentlyContinue).InstallPath
    if (-not $path) {
        $path = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Valve\Steam" `
                                   -ErrorAction SilentlyContinue).InstallPath
    }
    return $path
}

function Find-SteamCmd {
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
                               -Recurse -Depth 4 -ErrorAction SilentlyContinue `
                               | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Get-AppManifestPath {
    param($SteamCmdExePath)
    $steamapps = Join-Path (Split-Path $SteamCmdExePath) "steamapps"
    return "$steamapps\appmanifest_4564210.acf"
}

function Download-Agent {
    param($DestinationPath)
    $url = "https://github.com/JeanBernardMagnien/pitlane-agent/releases/latest/download/agent.zip"
    $zip = "$env:TEMP\pitlane-agent.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $DestinationPath -Force
    Remove-Item $zip
}

function New-JwtSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-PublicIp {
    try {
        return (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content.Trim()
    } catch {
        return "INCONNUE"
    }
}

# ─── Vérification préalable ────────────────────────────────────────────────

$AcEvoPath = Find-AcEvoServer
if (-not $AcEvoPath) {
    [System.Windows.Forms.MessageBox]::Show(
        "AC EVO Dedicated Server introuvable. Lance setup-full.ps1 pour une installation complète.",
        "Erreur", "OK", "Error"
    )
    exit 1
}

# ─── Interface principale ────────────────────────────────────────────────

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane Agent — Installation"
$form.Size = New-Object System.Drawing.Size(620, 590)
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
    "[1] Détection AC EVO",
    "[2] Détection Steam / steamcmd",
    "[3] Déduction appmanifest",
    "[4] Téléchargement agent",
    "[5] Vérification Python",
    "[6] Installation dépendances",
    "[7] Génération config.yml",
    "[8] Tâche planifiée Windows",
    "[9] Règles firewall",
    "[10] Terminé"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "⏳ " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (6 + $i * 33))
    $lbl.Size = New-Object System.Drawing.Size(535, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 403)
$progressBar.Size = New-Object System.Drawing.Size(560, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 427)
$logBox.Size = New-Object System.Drawing.Size(560, 60)
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
        "running" { $label.Text = "▶ $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0) }
        "ok"      { $label.Text = "✓ $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136) }
        "error"   { $label.Text = "✗ $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(255, 68, 68) }
        "skip"    { $label.Text = "— $base"; $label.ForeColor = [System.Drawing.Color]::FromArgb(110, 118, 129) }
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
$closeBtn.Location = New-Object System.Drawing.Point(470, 550)
$closeBtn.Size = New-Object System.Drawing.Size(110, 28)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$closeBtn.ForeColor = [System.Drawing.Color]::Black
$closeBtn.FlatStyle = "Flat"
$closeBtn.Visible = $false
$closeBtn.Add_Click({ $form.Close() })
$form.Controls.Add($closeBtn)

# ─── Installation ───────────────────────────────────────────────────────────

$form.Add_Shown({
    $form.Activate()
    $JwtSecret = $null
    $SteamCmdExe = $null
    $AppManifestPath = ""

    # [1] Détection AC EVO
    Set-StepStatus 0 "running"
    $AgentPath = "$AcEvoPath\pitlane-agent"
    Add-Log "AC EVO détecté : $AcEvoPath"
    Set-StepStatus 0 "ok"

    # [2] Détection Steam / steamcmd
    Set-StepStatus 1 "running"
    $SteamRoot  = Find-SteamRoot
    $SteamCmdExe = Find-SteamCmd

    if ($SteamRoot -and -not $SteamCmdExe) {
        $ans = [System.Windows.Forms.MessageBox]::Show(
            "Steam est installé mais steamcmd.exe est introuvable.`nVoulez-vous installer steamcmd maintenant ?",
            "steamcmd manquant", "YesNo", "Question"
        )
        if ($ans -eq "Yes") {
            $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
            $dlg.Description = "Choisissez le dossier d'installation de steamcmd"
            $dlg.SelectedPath = "C:\SteamCMD"
            if ($dlg.ShowDialog() -eq "OK") {
                $cmdDir = $dlg.SelectedPath
                Add-Log "Téléchargement steamcmd → $cmdDir"
                $zip = "$env:TEMP\steamcmd.zip"
                Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" `
                    -OutFile $zip -UseBasicParsing
                Expand-Archive -Path $zip -DestinationPath $cmdDir -Force
                Remove-Item $zip
                $SteamCmdExe = "$cmdDir\steamcmd.exe"
                Add-Log "steamcmd installé : $SteamCmdExe"
            }
        }
    }

    if ($SteamCmdExe) {
        Add-Log "steamcmd trouvé : $SteamCmdExe"
        Set-StepStatus 1 "ok"
    } else {
        Add-Log "steamcmd non trouvé — mise à jour à distance désactivée"
        Set-StepStatus 1 "skip"
    }

    # [3] Déduction appmanifest
    Set-StepStatus 2 "running"
    if ($SteamCmdExe) {
        $AppManifestPath = Get-AppManifestPath $SteamCmdExe
        Add-Log "appmanifest : $AppManifestPath"
        Set-StepStatus 2 "ok"
    } else {
        $AppManifestPath = ""
        Set-StepStatus 2 "skip"
    }

    # [4] Téléchargement agent
    Set-StepStatus 3 "running"
    try {
        Add-Log "Téléchargement agent → $AgentPath"
        Download-Agent -DestinationPath $AgentPath
        Set-StepStatus 3 "ok"
    } catch {
        Set-StepStatus 3 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "Échec du téléchargement de l'agent : $_", "Erreur", "OK", "Error")
        return
    }

    # [5] Vérification Python
    Set-StepStatus 4 "running"
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Add-Log "Python absent — installation via winget…"
        winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Add-Log "Python trouvé : $($python.Source)"
    }
    Set-StepStatus 4 "ok"

    # [6] Installation dépendances
    Set-StepStatus 5 "running"
    Add-Log "pip install requirements…"
    $pipOut = & python -m pip install -r "$AgentPath\requirements.txt" --quiet 2>&1
    Add-Log ($pipOut | Out-String).Trim()
    Set-StepStatus 5 "ok"

    # [7] Génération config.yml
    Set-StepStatus 6 "running"
    $JwtSecret = New-JwtSecret
    $configContent = Get-Content "$AgentPath\config.example.yml" -Raw
    $configContent = $configContent -replace 'INSTALL_PATH',      $AcEvoPath
    $configContent = $configContent -replace 'CONFIGS_PATH',      "$AcEvoPath\configs"
    $configContent = $configContent -replace 'RESULTS_PATH',      "$AcEvoPath\Results"
    $configContent = $configContent -replace 'LOGS_PATH',         "$AcEvoPath\logs"
    $configContent = $configContent -replace 'STEAMCMD_PATH',     ($SteamCmdExe -replace '\\', '\\\\')
    $configContent = $configContent -replace 'APPMANIFEST_PATH',  ($AppManifestPath -replace '\\', '\\\\')
    $configContent = $configContent -replace 'CHANGE_ME_SAME_AS_APP_SECRET_SYMFONY', $JwtSecret
    Set-Content -Path "$AgentPath\config.yml" -Value $configContent -Encoding UTF8
    foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    }
    Add-Log "config.yml généré"
    Set-StepStatus 6 "ok"

    # [8] Tâche planifiée
    Set-StepStatus 7 "running"
    Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false -ErrorAction SilentlyContinue
    $action    = New-ScheduledTaskAction -Execute "python" `
                     -Argument "`"$AgentPath\app.py`"" -WorkingDirectory $AgentPath
    $trigger   = New-ScheduledTaskTrigger -AtStartup
    $settings  = New-ScheduledTaskSettingsSet -RestartCount 3 `
                     -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
    Register-ScheduledTask -TaskName "PitLaneAgent" -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Add-Log "Tâche planifiée PitLaneAgent créée"
    Set-StepStatus 7 "ok"

    # [9] Règles firewall
    Set-StepStatus 8 "running"
    @(
        @{ Name="PitLane Agent";      Port=8181; Proto="TCP" },
        @{ Name="PitLane Server TCP"; Port=9700; Proto="TCP" },
        @{ Name="PitLane Server UDP"; Port=9700; Proto="UDP" },
        @{ Name="PitLane HTTP";       Port=8081; Proto="TCP" }
    ) | ForEach-Object {
        New-NetFirewallRule -DisplayName $_.Name -Direction Inbound `
            -Protocol $_.Proto -LocalPort $_.Port -Action Allow `
            -ErrorAction SilentlyContinue | Out-Null
        Add-Log "Firewall : $($_.Proto)/$($_.Port) ouvert ($($_.Name))"
    }
    Set-StepStatus 8 "ok"

    # [10] Résumé
    Set-StepStatus 9 "ok"
    $publicIp = Get-PublicIp

    $form.Size = New-Object System.Drawing.Size(620, 680)

    $summaryBox = New-Object System.Windows.Forms.Panel
    $summaryBox.Location = New-Object System.Drawing.Point(20, 500)
    $summaryBox.Size = New-Object System.Drawing.Size(560, 72)
    $summaryBox.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $summaryBox.BorderStyle = "FixedSingle"
    $form.Controls.Add($summaryBox)

    foreach ($row in @(
        @{ Label="IP publique : $publicIp"; CopyText=$publicIp;  BtnText="Copier IP";  Y=8  },
        @{ Label="JWT Secret : $($JwtSecret.Substring(0,20))…"; CopyText=$JwtSecret; BtnText="Copier JWT"; Y=38 }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $row.Label; $lbl.Location = New-Object System.Drawing.Point(10, $row.Y)
        $lbl.Size = New-Object System.Drawing.Size(390, 20)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $summaryBox.Controls.Add($lbl)

        $ct = $row.CopyText
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $row.BtnText; $btn.Location = New-Object System.Drawing.Point(410, ($row.Y - 2))
        $btn.Size = New-Object System.Drawing.Size(90, 24); $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $btn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $btn.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($ct) }.GetNewClosure())
        $summaryBox.Controls.Add($btn)
    }

    $yNext = 580
    if (-not $SteamCmdExe) {
        $warnLbl = New-Object System.Windows.Forms.Label
        $warnLbl.Text = "⚠ steamcmd non détecté — mise à jour à distance désactivée"
        $warnLbl.Location = New-Object System.Drawing.Point(20, $yNext)
        $warnLbl.Size = New-Object System.Drawing.Size(560, 20)
        $warnLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
        $form.Controls.Add($warnLbl)
        $yNext += 28
        $form.Size = New-Object System.Drawing.Size(620, ($yNext + 60))
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
