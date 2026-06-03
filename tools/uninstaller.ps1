#Requires -RunAsAdministrator

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Continue"

# Utility functions

function Find-AcEvoServer {
    param([System.Windows.Forms.TextBox]$LogBox)

    # Chercher d'abord dans les chemins connus pour eviter un scan global lent
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

    # Fallback scan global
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        Add-LogSafe -LogBox $LogBox -Message "Recherche AC EVO sur $drive ..."
        $found = Get-ChildItem -Path $drive -Filter "AssettoCorsaEVOServer.exe" `
            -Recurse -Depth 6 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }

    return $null
}

function Find-SteamCmd {
    param([System.Windows.Forms.TextBox]$LogBox)

    # Chercher d'abord dans les chemins connus
    $knownPaths = @(
        "C:\SteamCMD\steamcmd.exe",
        "D:\SteamCMD\steamcmd.exe",
        "C:\steamcmd\steamcmd.exe",
        "D:\steamcmd\steamcmd.exe"
    )

    foreach ($path in $knownPaths) {
        if (Test-Path $path) { return $path }
    }

    # Fallback scan global
    $drives = (Get-PSDrive -PSProvider FileSystem).Root
    foreach ($drive in $drives) {
        Add-LogSafe -LogBox $LogBox -Message "Recherche steamcmd.exe sur $drive ..."
        $found = Get-ChildItem -Path $drive -Filter "steamcmd.exe" `
            -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    return $null
}

function Add-LogSafe {
    param(
        [System.Windows.Forms.TextBox]$LogBox,
        [string]$Message
    )

    if (-not $Message) { return }
    $LogBox.AppendText("$Message`r`n")
    $LogBox.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

function Remove-PathSafe {
    param(
        [string]$Path,
        [bool]$DryRun,
        [System.Windows.Forms.TextBox]$LogBox
    )

    if (-not $Path) { return }

    $fullPath = [System.IO.Path]::GetFullPath($Path)

    if ($fullPath -match '^[A-Z]:\\$') {
        Add-LogSafe -LogBox $LogBox -Message "SECURITE : refus de supprimer une racine de disque : $fullPath"
        return
    }

    if (Test-Path $Path) {
        if ($DryRun) {
            Add-LogSafe -LogBox $LogBox -Message "[DRY RUN] Supprimerait : $Path"
        } else {
            Add-LogSafe -LogBox $LogBox -Message "Suppression : $Path"
            try {
                Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
            } catch {
                Add-LogSafe -LogBox $LogBox -Message "Remove-Item echoue, tentative via cmd rmdir..."
                & cmd /c rmdir /s /q `"$Path`"
                if (Test-Path $Path) {
                    Add-LogSafe -LogBox $LogBox -Message "ERREUR : impossible de supprimer $Path (fichiers verrouilles ?)"
                } else {
                    Add-LogSafe -LogBox $LogBox -Message "Suppression reussie via cmd : $Path"
                }
            }
        }
    } else {
        Add-LogSafe -LogBox $LogBox -Message "Introuvable : $Path"
    }
}

function Backup-DirectorySafe {
    param(
        [string]$SourcePath,
        [string]$DestinationPath,
        [bool]$DryRun,
        [System.Windows.Forms.TextBox]$LogBox
    )

    if (-not $SourcePath -or -not (Test-Path $SourcePath)) {
        Add-LogSafe -LogBox $LogBox -Message "Aucun dossier a sauvegarder : $SourcePath"
        return
    }

    if ($DryRun) {
        Add-LogSafe -LogBox $LogBox -Message "[DRY RUN] Sauvegarderait : $SourcePath -> $DestinationPath"
        return
    }

    Add-LogSafe -LogBox $LogBox -Message "Sauvegarde : $SourcePath -> $DestinationPath"
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    Copy-Item -Path (Join-Path $SourcePath "*") -Destination $DestinationPath -Recurse -Force -ErrorAction SilentlyContinue
}

# Main UI

$form = New-Object System.Windows.Forms.Form
$form.Text = "PitLane - Uninstaller / Reset"
$form.Size = New-Object System.Drawing.Size(720, 780)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)
$form.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "PitLane Uninstaller / Reset Tool"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$titleLabel.Location = New-Object System.Drawing.Point(20, 14)
$titleLabel.Size = New-Object System.Drawing.Size(660, 28)
$form.Controls.Add($titleLabel)

$warningLabel = New-Object System.Windows.Forms.Label
$warningLabel.Text = "Standard reset removes agent, service/task, firewall rules, logs, and backups configs. Results are kept."
$warningLabel.Location = New-Object System.Drawing.Point(20, 43)
$warningLabel.Size = New-Object System.Drawing.Size(660, 22)
$warningLabel.ForeColor = [System.Drawing.Color]::FromArgb(240, 165, 0)
$form.Controls.Add($warningLabel)

$optionsPanel = New-Object System.Windows.Forms.Panel
$optionsPanel.Location = New-Object System.Drawing.Point(20, 70)
$optionsPanel.Size = New-Object System.Drawing.Size(660, 92)
$optionsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$optionsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($optionsPanel)

$dryRunChk = New-Object System.Windows.Forms.CheckBox
$dryRunChk.Text = "Dry run only"
$dryRunChk.Location = New-Object System.Drawing.Point(12, 10)
$dryRunChk.Size = New-Object System.Drawing.Size(160, 22)
$dryRunChk.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$dryRunChk.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$optionsPanel.Controls.Add($dryRunChk)

$removeSteamChk = New-Object System.Windows.Forms.CheckBox
$removeSteamChk.Text = "Remove SteamCMD"
$removeSteamChk.Location = New-Object System.Drawing.Point(12, 42)
$removeSteamChk.Size = New-Object System.Drawing.Size(180, 22)
$removeSteamChk.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$removeSteamChk.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$optionsPanel.Controls.Add($removeSteamChk)

$removeAcEvoChk = New-Object System.Windows.Forms.CheckBox
$removeAcEvoChk.Text = "Remove AC EVO server"
$removeAcEvoChk.Location = New-Object System.Drawing.Point(220, 42)
$removeAcEvoChk.Size = New-Object System.Drawing.Size(210, 22)
$removeAcEvoChk.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$removeAcEvoChk.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$optionsPanel.Controls.Add($removeAcEvoChk)

$removePythonChk = New-Object System.Windows.Forms.CheckBox
$removePythonChk.Text = "Remove Python deps"
$removePythonChk.Location = New-Object System.Drawing.Point(455, 42)
$removePythonChk.Size = New-Object System.Drawing.Size(190, 22)
$removePythonChk.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$removePythonChk.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$optionsPanel.Controls.Add($removePythonChk)

$stepsPanel = New-Object System.Windows.Forms.Panel
$stepsPanel.Location = New-Object System.Drawing.Point(20, 175)
$stepsPanel.Size = New-Object System.Drawing.Size(660, 300)
$stepsPanel.BackColor = [System.Drawing.Color]::FromArgb(22, 27, 34)
$stepsPanel.BorderStyle = "FixedSingle"
$form.Controls.Add($stepsPanel)

$steps = @(
    "[1] Arret de l'agent PitLane",
    "[2] Suppression service/tache",
    "[3] Suppression regles firewall",
    "[4] Detection installations",
    "[5] Backup configs et nettoyage logs/configs",
    "[6] Suppression agent PitLane",
    "[7] Suppressions avancees",
    "[8] Termine"
)

$stepLabels = @()
for ($i = 0; $i -lt $steps.Count; $i++) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "WAIT " + $steps[$i]
    $lbl.Location = New-Object System.Drawing.Point(10, (8 + $i * 34))
    $lbl.Size = New-Object System.Drawing.Size(635, 26)
    $lbl.ForeColor = [System.Drawing.Color]::FromArgb(139, 148, 158)
    $stepsPanel.Controls.Add($lbl)
    $stepLabels += $lbl
}

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 488)
$progressBar.Size = New-Object System.Drawing.Size(660, 16)
$progressBar.Maximum = $steps.Count
$form.Controls.Add($progressBar)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Location = New-Object System.Drawing.Point(20, 515)
$logBox.Size = New-Object System.Drawing.Size(660, 155)
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
    Add-LogSafe -LogBox $logBox -Message $msg
}

function Is-UnsafeRootPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $true }

    $fullPath = [System.IO.Path]::GetFullPath($Path)

    return $fullPath -match '^[A-Z]:\\$'
}

$runBtn = New-Object System.Windows.Forms.Button
$runBtn.Text = "Run reset"
$runBtn.Location = New-Object System.Drawing.Point(445, 695)
$runBtn.Size = New-Object System.Drawing.Size(110, 30)
$runBtn.BackColor = [System.Drawing.Color]::FromArgb(0, 255, 136)
$runBtn.ForeColor = [System.Drawing.Color]::Black
$runBtn.FlatStyle = "Flat"
$form.Controls.Add($runBtn)

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Text = "Fermer"
$closeBtn.Location = New-Object System.Drawing.Point(570, 695)
$closeBtn.Size = New-Object System.Drawing.Size(110, 30)
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(48, 54, 61)
$closeBtn.ForeColor = [System.Drawing.Color]::FromArgb(230, 237, 243)
$closeBtn.FlatStyle = "Flat"
$closeBtn.Add_Click({ $form.Close() })
$form.Controls.Add($closeBtn)

$runBtn.Add_Click({
    $runBtn.Enabled = $false
    $dryRun = $dryRunChk.Checked
    $removeSteamCmd = $removeSteamChk.Checked
    $removeAcEvoServer = $removeAcEvoChk.Checked
    $removePythonDeps = $removePythonChk.Checked

    if ($removeSteamCmd -or $removeAcEvoServer -or $removePythonDeps) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "Suppressions avancees demandees.`nSteamCMD, AC EVO ou des dependances Python peuvent etre supprimes.`nContinuer ?",
            "Confirmation", "YesNo", "Warning"
        )

        if ($answer -ne "Yes") {
            Add-Log "Annule par utilisateur."
            $runBtn.Enabled = $true
            return
        }
    }

    try {
        Add-Log "=== PitLane uninstaller / reset tool ==="
        if ($dryRun) { Add-Log "Mode DRY RUN actif." }

        # [1] Stop agent + process steamcmd pour liberer les locks
        Set-StepStatus 0 "running"
        $service = Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue
        if ($service) {
            if ($dryRun) {
                Add-Log "[DRY RUN] Stopperait le service PitLaneAgent"
            } else {
                Add-Log "Arret service PitLaneAgent"
                Stop-Service -Name "PitLaneAgent" -Force -ErrorAction SilentlyContinue
            }
        }

        if (-not $dryRun) {
            Stop-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue
        } else {
            Add-Log "[DRY RUN] Stopperait la tache PitLaneAgent"
        }

        # Process Python lies a PitLane
        Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -like "*pitlane-agent*" -or
            $_.CommandLine -like "*app.py*" -or
            $_.CommandLine -like "*service.py*"
        } |
        ForEach-Object {
            if ($dryRun) {
                Add-Log "[DRY RUN] Stopperait process python PID $($_.ProcessId)"
            } else {
                Add-Log "Stop process python PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }

        # Process SteamCMD qui pourraient tenir des locks
        Get-Process -Name "steamcmd" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($dryRun) {
                Add-Log "[DRY RUN] Stopperait process steamcmd PID $($_.Id)"
            } else {
                Add-Log "Stop process steamcmd PID $($_.Id)"
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
        }

        # Pause pour laisser les handles se liberer
        if (-not $dryRun) {
            Add-Log "Attente liberation des handles..."
            Start-Sleep -Seconds 2
        }

        Set-StepStatus 0 "ok"

        # [2] Service + scheduled task
        Set-StepStatus 1 "running"
        if (Get-Service -Name "PitLaneAgent" -ErrorAction SilentlyContinue) {
            if ($dryRun) {
                Add-Log "[DRY RUN] Supprimerait le service PitLaneAgent"
            } else {
                Add-Log "Suppression service PitLaneAgent"
                sc.exe delete PitLaneAgent | Out-Null
            }
        } else {
            Add-Log "Aucun service PitLaneAgent trouve"
        }

        if (Get-ScheduledTask -TaskName "PitLaneAgent" -ErrorAction SilentlyContinue) {
            if ($dryRun) {
                Add-Log "[DRY RUN] Supprimerait la tache PitLaneAgent"
            } else {
                Unregister-ScheduledTask -TaskName "PitLaneAgent" -Confirm:$false
                Add-Log "Tache PitLaneAgent supprimee"
            }
        } else {
            Add-Log "Aucune tache PitLaneAgent trouvee"
        }
        Set-StepStatus 1 "ok"

        # [3] Firewall
        Set-StepStatus 2 "running"
        $pitlaneRules = Get-NetFirewallRule -DisplayName "PitLane*" -ErrorAction SilentlyContinue

        if ($pitlaneRules) {
            foreach ($rule in $pitlaneRules) {
                if ($dryRun) {
                    Add-Log "[DRY RUN] Supprimerait regle firewall : $($rule.DisplayName)"
                } else {
                    Add-Log "Suppression regle firewall : $($rule.DisplayName)"
                    $rule | Remove-NetFirewallRule
                }
            }
        } else {
            Add-Log "Aucune regle firewall PitLane trouvee"
        }
        Set-StepStatus 2 "ok"

        # [4] Detection
        Set-StepStatus 3 "running"
        $AcEvoPath = Find-AcEvoServer -LogBox $logBox
        $SteamCmdExe = Find-SteamCmd -LogBox $logBox
        Add-Log "AC EVO   : $(if ($AcEvoPath) { $AcEvoPath } else { 'introuvable' })"
        Add-Log "SteamCMD : $(if ($SteamCmdExe) { $SteamCmdExe } else { 'introuvable' })"
        Set-StepStatus 3 "ok"

        # [5] Backup configs and cleanup generated files
        Set-StepStatus 4 "running"
        if ($AcEvoPath) {
            $DesktopPath = [Environment]::GetFolderPath("Desktop")
            $ConfigBackupPath = Join-Path $DesktopPath "PitLane AC EVO config backup"

            Backup-DirectorySafe -SourcePath "$AcEvoPath\configs" -DestinationPath $ConfigBackupPath -DryRun $dryRun -LogBox $logBox
            Remove-PathSafe -Path "$AcEvoPath\configs" -DryRun $dryRun -LogBox $logBox
            Remove-PathSafe -Path "$AcEvoPath\logs" -DryRun $dryRun -LogBox $logBox
        } else {
            Add-Log "AC EVO introuvable, impossible de nettoyer configs/logs"
        }
        Set-StepStatus 4 "ok"

        # [6] Remove agent
        Set-StepStatus 5 "running"
        if ($AcEvoPath) {
            Remove-PathSafe -Path "$AcEvoPath\pitlane-agent" -DryRun $dryRun -LogBox $logBox
        } else {
            Add-Log "AC EVO introuvable, impossible de deduire le chemin de l'agent"
        }
        Set-StepStatus 5 "ok"

        # [7] Advanced cleanup
        Set-StepStatus 6 "running"

        if ($removeSteamCmd) {
            if ($SteamCmdExe) {
                $SteamCmdDir = Split-Path $SteamCmdExe

                if ($SteamCmdDir -match '^[A-Z]:\\$') {
                    Add-Log "steamcmd.exe est a la racine ($SteamCmdExe). Suppression du fichier uniquement."
                    Remove-PathSafe -Path $SteamCmdExe -DryRun $dryRun -LogBox $logBox
                } else {
                    Remove-PathSafe -Path $SteamCmdDir -DryRun $dryRun -LogBox $logBox
                }
            } else {
                Add-Log "steamcmd.exe introuvable, aucune suppression SteamCMD"
            }
        }

        if ($removeAcEvoServer) {
            if ($AcEvoPath) {
                if (Is-UnsafeRootPath $AcEvoPath) {
                    Add-Log "SECURITE : refus de supprimer une racine de disque : $AcEvoPath"
                } elseif (-not (Test-Path $AcEvoPath)) {
                    Add-Log "AC EVO deja supprime avec SteamCMD."
                } else {
                    Remove-PathSafe -Path $AcEvoPath -DryRun $dryRun -LogBox $logBox
                }
            } else {
                Add-Log "AC EVO introuvable"
            }
        }

        if ($removePythonDeps) {
            if ($dryRun) {
                Add-Log "[DRY RUN] Desinstallerait les dependances Python PitLane"
            } else {
                Add-Log "Desinstallation dependances Python PitLane"
                python -m pip uninstall -y flask flask-cors pyjwt pyyaml requests psutil waitress websocket-client pywin32 2>$null
            }
        }

        if (-not $removeSteamCmd -and -not $removeAcEvoServer -and -not $removePythonDeps) {
            Add-Log "Aucune suppression avancee demandee"
        }

        Set-StepStatus 6 "ok"

        # [8] Done
        Set-StepStatus 7 "ok"
        Add-Log "Results conserve volontairement."
        Add-Log "Desinstallation / reset termine."
    } catch {
        Add-Log "ERROR : $_"
        [System.Windows.Forms.MessageBox]::Show("Erreur pendant le reset : $_", "Erreur", "OK", "Error")
    }

    $runBtn.Enabled = $true
})

[System.Windows.Forms.Application]::Run($form)