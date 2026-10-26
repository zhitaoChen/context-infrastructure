[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('daily', 'weekly')][string]$Kind,
    [ValidateRange(0, 3600)][int]$QueueTimeoutSeconds = 2700
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$local = Join-Path $root 'contexts\memory\.local'
$config = Get-Content -LiteralPath (Join-Path $local 'config.json') -Raw | ConvertFrom-Json
$env:PYTHONIOENCODING = 'utf-8'
if ($config.node_directory) { $env:PATH = "$($config.node_directory);$env:PATH" }
$log = Join-Path $local "$Kind.log"
# Scheduler IgnoreNew applies per task, not across Daily and Weekly. Catch-up
# triggers can start both together. Hold a separate OS-released lock throughout
# the pipeline; Python commands still retain their transactional worker locks.
$pipelineLock = $null
$deadline = [DateTime]::UtcNow.AddSeconds($QueueTimeoutSeconds)
while ($null -eq $pipelineLock) {
    try {
        $pipelineLock = [IO.File]::Open((Join-Path $local 'pipeline.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        if ([DateTime]::UtcNow -ge $deadline) {
            Write-Error 'Another scheduled memory pipeline is still running; queue timeout.' -ErrorAction Continue
            exit 1
        }
        Start-Sleep -Seconds 2
    }
}
$code = 0
try {
    $commands = @(
        @{ Script = 'history.py'; Command = 'collect' },
        @{ Script = 'agent_history.py'; Command = 'collect' }
    )
    if ($Kind -eq 'daily') {
        $commands += @{ Script = 'observer.py'; Command = 'run' }
    }
    $commands += @{ Script = 'memory.py'; Command = $Kind }
    "Started $Kind at $([DateTimeOffset]::Now.ToString('o'))" |
        Out-File -LiteralPath $log -Encoding utf8
    foreach ($step in $commands) {
        & $config.python (Join-Path $root "tools\brain\$($step.Script)") --root $root $step.Command 2>&1 |
            Out-File -LiteralPath $log -Encoding utf8 -Append
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            Write-Error "$($step.Script) $($step.Command) failed (exit $code). See $log" -ErrorAction Continue
            break
        }
    }
} finally {
    $pipelineLock.Dispose()
}
exit $code
