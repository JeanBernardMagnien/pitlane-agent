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

$existing = Find-AcEvoServer
if ($existing) {
    [System.Windows.Forms.MessageBox]::Show(
        "AC EVO Dedicated Server déjà détecté ($existing).`nLance setup-agent.ps1 pour installer uniquement l'agent.",
        "Erreur", "OK", "Error"
    )
    exit 1
}

# ─── Interface principale ────────────────────────────────────────────────

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane — Installation complète"
$form.Size = New-Object System.Drawing.Size(680, 640)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Installation complète — steamcmd + AC EVO + Agent"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(630, 26)
$form.Controls.Add($titleLabel)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 50)
$stepsPanel.Size = New-Object System.Drawing.Size(630, 395)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Choix dossier steamcmd",
    "[2] Téléchargement steamcmd",
    "[3] Choix dossier AC EVO",
    "[4] Saisie credentials Steam",
    "[5] Téléchargement AC EVO",
    "[6] Installation agent",
    "[7] Vérification Python",
    "[8] Installation dépendances",
    "[9] Génération config.yml",
    "[10] Tâche planifiée Windows",
    "[11] Règles firewall",
    "[12] Terminé"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "⏳ " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (4 + $i * 32))
    $lbl.Size = New-Object System.Drawing.Size(610, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 453)
$progressBar.Size = New-Object System.Drawing.Size(630, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 477)
$logBox.Size = New-Object System.Drawing.Size(630, 80)
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
    $base  = $steps[$index]
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
$closeBtn.Location = New-Object System.Drawing.Point(540, 600)
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

    # [1] Choix dossier steamcmd
    Set-StepStatus 0 "running"
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Choisissez le dossier d'installation de steamcmd (ex: C:\SteamCMD)"
    $dlg.SelectedPath = "C:\SteamCMD"
    if ($dlg.ShowDialog() -ne "OK") { $form.Close(); return }
    $SteamCmdDir = $dlg.SelectedPath
    $SteamCmdExe = "$SteamCmdDir\steamcmd.exe"
    Add-Log "Dossier steamcmd : $SteamCmdDir"
    Set-StepStatus 0 "ok"

    # [2] Téléchargement steamcmd
    Set-StepStatus 1 "running"
    try {
        Add-Log "Téléchargement steamcmd…"
        $zip = "$env:TEMP\steamcmd.zip"
        Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" `
            -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $SteamCmdDir -Force
        Remove-Item $zip
        Add-Log "steamcmd extrait : $SteamCmdExe"
        Set-StepStatus 1 "ok"
    } catch {
        Set-StepStatus 1 "error"
        [System.Windows.Forms.MessageBox]::Show("Erreur steamcmd : $_", "Erreur", "OK", "Error")
        return
    }

    # [3] Choix dossier AC EVO
    Set-StepStatus 2 "running"
    $defaultAcEvo = "$SteamCmdDir\steamapps\common\Assetto Corsa EVO Dedicated Server"
    $dlg2 = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg2.Description = "Choisissez le dossier d'installation d'AC EVO"
    $dlg2.SelectedPath = $defaultAcEvo
    if ($dlg2.ShowDialog() -ne "OK") { $form.Close(); return }
    $AcEvoPath = $dlg2.SelectedPath
    $AgentPath = "$AcEvoPath\pitlane-agent"
    Add-Log "Dossier AC EVO : $AcEvoPath"
    Set-StepStatus 2 "ok"

    # [4] Saisie credentials Steam
    Set-StepStatus 3 "running"
    $credForm = New-Object System.Windows.Forms.Form
    $credForm.Text = "Credentials Steam"
    $credForm.Size = New-Object System.Drawing.Size(400, 220)
    $credForm.StartPosition = "CenterScreen"
    $credForm.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $credForm.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
    $credForm.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $credForm.FormBorderStyle = "FixedDialog"
    $credForm.MaximizeBox = $false

    $noteLbl = New-Object System.Windows.Forms.Label
    $noteLbl.Text = "Ces identifiants sont utilisés une seule fois et ne sont jamais stockés."
    $noteLbl.Location = New-Object System.Drawing.Point(12, 12)
    $noteLbl.Size = New-Object System.Drawing.Size(365, 32)
    $noteLbl.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
    $credForm.Controls.Add($noteLbl)

    foreach ($row in @(
        @{ Label="Nom d'utilisateur Steam :"; Y=54;  PassChar=[char]0 },
        @{ Label="Mot de passe Steam :";       Y=100; PassChar='*'    }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $row.Label; $lbl.Location = New-Object System.Drawing.Point(12, $row.Y)
        $lbl.Size = New-Object System.Drawing.Size(170, 20)
        $credForm.Controls.Add($lbl)
        $txt = New-Object System.Windows.Forms.TextBox
        $txt.Location = New-Object System.Drawing.Point(185, ($row.Y - 2))
        $txt.Size = New-Object System.Drawing.Size(185, 22)
        $txt.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
        $txt.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $txt.BorderStyle = "FixedSingle"
        if ($row.PassChar -ne [char]0) { $txt.PasswordChar = $row.PassChar }
        $credForm.Controls.Add($txt)
        if ($row.Y -eq 54)  { $userTxt = $txt } else { $passTxt = $txt }
    }

    $okBtn = New-Object System.Windows.Forms.Button
    $okBtn.Text = "Continuer"; $okBtn.DialogResult = "OK"
    $okBtn.Location = New-Object System.Drawing.Point(270, 148)
    $okBtn.Size = New-Object System.Drawing.Size(100, 28)
    $okBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
    $okBtn.ForeColor = [System.Drawing.Color]::Black
    $okBtn.FlatStyle = "Flat"
    $credForm.Controls.Add($okBtn)
    $credForm.AcceptButton = $okBtn

    if ($credForm.ShowDialog() -ne "OK") { $form.Close(); return }
    $steamUser = $userTxt.Text
    $steamPass = $passTxt.Text
    $passTxt.Text = "" # effacer de la mémoire du contrôle
    Add-Log "Credentials saisis"
    Set-StepStatus 3 "ok"

    # [5] Téléchargement AC EVO via steamcmd
    Set-StepStatus 4 "running"
    Add-Log "Lancement steamcmd +app_update 4564210 validate…"
    $steamArgs = "+force_install_dir `"$AcEvoPath`" +login `"$steamUser`" `"$steamPass`" +app_update 4564210 validate +quit"
    $steamUser = $null; $steamPass = $null  # effacer les credentials
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $SteamCmdExe
    $psi.Arguments = $steamArgs
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow  = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.BeginOutputReadLine()
    $proc.OutputDataReceived.Add({ param($s,$e); if ($e.Data) { Add-Log $e.Data } })
    while (-not $proc.HasExited) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path "$AcEvoPath\AssettoCorsaEVOServer.exe")) {
        Set-StepStatus 4 "error"
        [System.Windows.Forms.MessageBox]::Show(
            "Échec du téléchargement. Vérifiez vos credentials Steam.", "Erreur", "OK", "Error")
        return
    }
    Add-Log "AC EVO téléchargé"
    Set-StepStatus 4 "ok"

    # [6] Installation agent
    Set-StepStatus 5 "running"
    try {
        Download-Agent -DestinationPath $AgentPath
        Add-Log "Agent installé : $AgentPath"
        Set-StepStatus 5 "ok"
    } catch {
        Set-StepStatus 5 "error"
        [System.Windows.Forms.MessageBox]::Show("Erreur agent : $_", "Erreur", "OK", "Error")
        return
    }

    # [7] Vérification Python
    Set-StepStatus 6 "running"
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Add-Log "Python absent — installation via winget…"
        winget install Python.Python.3 --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
    } else { Add-Log "Python trouvé : $($python.Source)" }
    Set-StepStatus 6 "ok"

    # [8] Installation dépendances
    Set-StepStatus 7 "running"
    Add-Log "pip install requirements…"
    $pipOut = & python -m pip install -r "$AgentPath\requirements.txt" --quiet 2>&1
    Add-Log ($pipOut | Out-String).Trim()
    Set-StepStatus 7 "ok"

    # [9] Génération config.yml
    Set-StepStatus 8 "running"
    $JwtSecret = New-JwtSecret
    $AppManifestPath = Get-AppManifestPath $SteamCmdExe
    $configContent = Get-Content "$AgentPath\config.example.yml" -Raw
    $configContent = $configContent -replace 'INSTALL_PATH',     $AcEvoPath
    $configContent = $configContent -replace 'CONFIGS_PATH',     "$AcEvoPath\configs"
    $configContent = $configContent -replace 'RESULTS_PATH',     "$AcEvoPath\Results"
    $configContent = $configContent -replace 'LOGS_PATH',        "$AcEvoPath\logs"
    $configContent = $configContent -replace 'STEAMCMD_PATH',    ($SteamCmdExe -replace '\\', '\\\\')
    $configContent = $configContent -replace 'APPMANIFEST_PATH', ($AppManifestPath -replace '\\', '\\\\')
    $configContent = $configContent -replace 'CHANGE_ME_SAME_AS_APP_SECRET_SYMFONY', $JwtSecret
    Set-Content -Path "$AgentPath\config.yml" -Value $configContent -Encoding UTF8
    foreach ($dir in @("$AcEvoPath\configs", "$AcEvoPath\Results", "$AcEvoPath\logs")) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    }
    Add-Log "config.yml généré"
    Set-StepStatus 8 "ok"

    # [10] Tâche planifiée
    Set-StepStatus 9 "running"
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
    Set-StepStatus 9 "ok"

    # [11] Règles firewall
    Set-StepStatus 10 "running"
    @(
        @{ Name="PitLane Agent";      Port=8181; Proto="TCP" },
        @{ Name="PitLane Server TCP"; Port=9700; Proto="TCP" },
        @{ Name="PitLane Server UDP"; Port=9700; Proto="UDP" },
        @{ Name="PitLane HTTP";       Port=8081; Proto="TCP" }
    ) | ForEach-Object {
        New-NetFirewallRule -DisplayName $_.Name -Direction Inbound `
            -Protocol $_.Proto -LocalPort $_.Port -Action Allow `
            -ErrorAction SilentlyContinue | Out-Null
        Add-Log "Firewall : $($_.Proto)/$($_.Port) ouvert"
    }
    Set-StepStatus 10 "ok"

    # [12] Résumé
    Set-StepStatus 11 "ok"
    $publicIp = Get-PublicIp

    $form.Size = New-Object System.Drawing.Size(680, 730)

    $summaryBox = New-Object System.Windows.Forms.Panel
    $summaryBox.Location = New-Object System.Drawing.Point(20, 575)
    $summaryBox.Size = New-Object System.Drawing.Size(630, 72)
    $summaryBox.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
    $summaryBox.BorderStyle = "FixedSingle"
    $form.Controls.Add($summaryBox)

    foreach ($row in @(
        @{ Label="IP publique : $publicIp"; CopyText=$publicIp;  BtnText="Copier IP";  Y=8  },
        @{ Label="JWT Secret : $($JwtSecret.Substring(0,20))…"; CopyText=$JwtSecret; BtnText="Copier JWT"; Y=38 }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $row.Label; $lbl.Location = New-Object System.Drawing.Point(10, $row.Y)
        $lbl.Size = New-Object System.Drawing.Size(440, 20)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $summaryBox.Controls.Add($lbl)

        $ct = $row.CopyText
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $row.BtnText; $btn.Location = New-Object System.Drawing.Point(460, ($row.Y - 2))
        $btn.Size = New-Object System.Drawing.Size(110, 24); $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
        $btn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
        $btn.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($ct) }.GetNewClosure())
        $summaryBox.Controls.Add($btn)
    }

    $msgLbl = New-Object System.Windows.Forms.Label
    $msgLbl.Text = "Rends-toi dans le hub PitLane pour ajouter ce serveur."
    $msgLbl.Location = New-Object System.Drawing.Point(20, 658)
    $msgLbl.Size = New-Object System.Drawing.Size(490, 20)
    $msgLbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $form.Controls.Add($msgLbl)

    $closeBtn.Location = New-Object System.Drawing.Point(540, 655)
    $closeBtn.Visible = $true
    [System.Windows.Forms.Application]::DoEvents()
})

[System.Windows.Forms.Application]::Run($form)
