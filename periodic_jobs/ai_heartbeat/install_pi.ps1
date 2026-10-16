[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Provider,
    [Parameter(Mandatory)][string]$Model,
    [ValidateRange(60, 3600)][int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$local = Join-Path $root 'contexts\memory\.local'
$python = (& python -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Python is required.' }
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$pi = (Get-Command pi -ErrorAction Stop).Source
$agentDir = if ($env:PI_CODING_AGENT_DIR) { $env:PI_CODING_AGENT_DIR } else { Join-Path $HOME '.pi\agent' }
if ($pi.EndsWith('.ps1')) { $command = @($pwsh, '-NoProfile', '-File', $pi) }
elseif ($pi.EndsWith('.exe')) { $command = @($pi) }
else { throw 'Resolve pi to a .ps1 or .exe entry point.' }
if ([TimeZoneInfo]::Local.Id -notin @('China Standard Time', 'Asia/Shanghai')) {
    throw 'Schedules require China Standard Time.'
}
$names = @('PersonalBrain-Pi-Daily', 'PersonalBrain-Pi-Weekly')
foreach ($name in ($names + @('PersonalBrain-Daily', 'PersonalBrain-Weekly'))) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        throw "Existing task $name must be inspected before installing another runner."
    }
}
$branch = (& git -C $root branch --show-current).Trim()
$remote = (& git -C $root remote get-url --push origin).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch -or -not $remote) { throw 'Git branch and origin required.' }
if (-not $PSCmdlet.ShouldProcess($root, 'Install daily Pi maintenance/public push and Sunday review')) { return }
& $pi auth check --provider $Provider --json
if ($LASTEXITCODE -ne 0) { throw 'Pi provider is not ready; authenticate locally.' }
New-Item -ItemType Directory -Path $local -Force | Out-Null
@{
    python = $python; pi_command = $command; agent_dir = $agentDir
    provider = $Provider; model = $Model; timeout_seconds = $TimeoutSeconds
    branch = $branch; remote = $remote
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $local 'pi_runtime.json') -Encoding utf8
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$triggers = @((New-ScheduledTaskTrigger -Daily -At '23:00'),
              (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '23:30'))
for ($i = 0; $i -lt $names.Count; $i++) {
    $kind = @('daily', 'weekly')[$i]
    # Daily: 8 conversation batches x 2 validation attempts + classifier x2 + publication.
    $modelCalls = if ($kind -eq 'daily') { 19 } else { 2 }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Seconds ($modelCalls * $TimeoutSeconds + 1800)) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Kind {1}' -f `
        (Join-Path $PSScriptRoot 'run_pi.ps1'), $kind
    $action = New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $root
    $task = New-ScheduledTask -Action $action -Trigger $triggers[$i] -Settings $settings -Principal $principal `
        -Description 'Pi brain maintenance; restricted model; daily public tracked-file sync; weekly drafts only.'
    Register-ScheduledTask -TaskName $names[$i] -InputObject $task | Out-Null
}
Get-ScheduledTask -TaskName $names | Select-Object TaskName, State
