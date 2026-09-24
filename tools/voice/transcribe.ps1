[CmdletBinding()]
param(
    [string]$File,
    [ValidateSet('whisper-tiny', 'whisper-base', 'whisper-small', 'whisper-medium', 'whisper-large-v3-turbo')]
    [string]$Model = 'whisper-small',
    [string]$Language,
    [string]$OutputPath,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command foundry -ErrorAction SilentlyContinue)) {
    throw 'Foundry Local is required. Install it with: winget install Microsoft.FoundryLocal'
}
if ($OutputPath -and -not $File) {
    throw '-OutputPath requires -File.'
}

$arguments = @('transcribe', '--model', $Model)
if ($Language) {
    $arguments += @('--language', $Language)
}
if ($File) {
    $inputFile = (Resolve-Path -LiteralPath $File -ErrorAction Stop).Path
    $arguments += @('--file', $inputFile, '--output', $(if ($Json) { 'json' } else { 'text' }))
}
elseif ($Json) {
    throw '-Json requires -File.'
}

if (-not $OutputPath) {
    & foundry @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Whisper transcription failed with exit code $LASTEXITCODE."
    }
    return
}

$parent = Split-Path -Parent $OutputPath
if ($parent) {
    $resolvedParent = (Resolve-Path -LiteralPath $parent -ErrorAction Stop).Path
    $destination = Join-Path $resolvedParent (Split-Path -Leaf $OutputPath)
}
else {
    $destination = Join-Path (Get-Location) $OutputPath
}

$transcript = & foundry @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Whisper transcription failed with exit code $LASTEXITCODE."
}
$transcript | Set-Content -LiteralPath $destination -Encoding utf8
Write-Output $destination
