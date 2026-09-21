[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('daily', 'weekly')][string]$Kind
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$local = Join-Path $root 'contexts\memory\.local'
$config = Get-Content -LiteralPath (Join-Path $local 'config.json') -Raw | ConvertFrom-Json
$env:PYTHONIOENCODING = 'utf-8'
$log = Join-Path $local "$Kind.log"
& $config.python (Join-Path $root 'tools\brain\history.py') --root $root collect 2>&1 |
    Out-File -LiteralPath $log -Encoding utf8
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Error "History collection failed (exit $code). Memory $Kind not started. See $log" -ErrorAction Continue
    exit $code
}
if ($Kind -eq 'daily') {
    & $config.python (Join-Path $root 'tools\brain\observer.py') --root $root run 2>&1 |
        Out-File -LiteralPath $log -Encoding utf8 -Append
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Error "Observer failed (exit $code). Daily classification not started. See $log" -ErrorAction Continue
        exit $code
    }
}
& $config.python (Join-Path $root 'tools\brain\memory.py') --root $root $Kind 2>&1 |
    Out-File -LiteralPath $log -Encoding utf8 -Append
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Error "Memory $Kind failed (exit $code). See $log" -ErrorAction Continue }
exit $code
