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
& $config.python (Join-Path $root 'tools\brain\memory.py') --root $root $Kind 2>&1 |
    Out-File -LiteralPath $log -Encoding utf8
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Error "Memory $Kind failed (exit $code). See $log" -ErrorAction Continue }
exit $code
