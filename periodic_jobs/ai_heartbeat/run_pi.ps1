[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('daily', 'weekly')][string]$Kind)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$local = Join-Path $root 'contexts\memory\.local'
$config = Get-Content -LiteralPath (Join-Path $local 'pi_runtime.json') -Raw | ConvertFrom-Json
$env:PYTHONIOENCODING = 'utf-8'
& $config.python (Join-Path $root 'tools\brain\pi_schedule.py') --root $root --kind $Kind 2>&1 |
    Out-File -LiteralPath (Join-Path $local "pi_$Kind.log") -Encoding utf8
exit $LASTEXITCODE
