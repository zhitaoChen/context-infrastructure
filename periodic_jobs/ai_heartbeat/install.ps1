[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$GitHubUser,
    [ValidateRange(60, 3600)][int]$TimeoutSeconds = 600,
    [switch]$ReplaceExisting
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$local = Join-Path $root 'contexts\memory\.local'
$python = (& python -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
    throw 'Python 3.10+ must be installed before installing memory schedules.'
}
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$copilot = (Get-Command copilot -ErrorAction Stop).Source
$gh = (Get-Command gh -ErrorAction Stop).Source
if ([TimeZoneInfo]::Local.Id -notin @('China Standard Time', 'Asia/Shanghai')) {
    throw 'These schedules require Asia/Shanghai (Windows: China Standard Time); system timezone differs.'
}
if ($copilot.EndsWith('.ps1')) { $command = @($pwsh, '-NoProfile', '-File', $copilot) }
elseif ($copilot.EndsWith('.exe')) { $command = @($copilot) }
else { throw 'Resolve copilot to a .ps1 or .exe entry point first.' }
$names = @('PersonalBrain-Daily', 'PersonalBrain-Weekly')
foreach ($name in $names) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and -not $ReplaceExisting) { throw "Task $name exists; inspect it before using -ReplaceExisting." }
}
if (-not $PSCmdlet.ShouldProcess($root, 'Install logged-in, least-privilege memory tasks')) { return }
New-Item -ItemType Directory -Path $local -Force | Out-Null
$config = @{
    python = $python; gh = $gh; gh_user = $GitHubUser; copilot_command = $command
    timeout_seconds = $TimeoutSeconds; max_ai_credits = $null; promotion_mode = 'review'
}
$config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $local 'config.json') -Encoding utf8
& $python (Join-Path $root 'tools\brain\memory.py') render
if ($LASTEXITCODE -ne 0) { throw 'Memory storage initialization failed.' }
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At '00:00'),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '23:30')
)
for ($i = 0; $i -lt $names.Count; $i++) {
    $kind = @('daily', 'weekly')[$i]
    $modelCalls = if ($kind -eq 'daily') { 2 } else { 1 }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Seconds ($modelCalls * $TimeoutSeconds + 120)) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Kind {1}' -f `
        (Join-Path $PSScriptRoot 'run.ps1'), $kind
    $action = New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $root
    $task = New-ScheduledTask -Action $action -Trigger $triggers[$i] -Settings $settings -Principal $principal `
        -Description 'Personal brain: non-sensitive workflow memory; proposals only; no autonomous rule edits.'
    Register-ScheduledTask -TaskName $names[$i] -InputObject $task -Force:$ReplaceExisting | Out-Null
}
Get-ScheduledTask -TaskName $names | Select-Object TaskName, State
