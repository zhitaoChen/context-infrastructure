[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$homeDirectory = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME '.copilot' }
$file = Join-Path $homeDirectory 'copilot-instructions.md'
$start = '<!-- personal-brain:start -->'
$end = '<!-- personal-brain:end -->'
$block = @"
$start
# Personal Brain

The shared brain root is ``$root``.
At the start of a new task, read its ``AGENTS.md`` and use its lazy-loading rules.
Use the native ``personal-brain`` skill when relevant. Read only matched references;
do not preload all skills, axioms, memory or archives. Missing permissions must be
reported, not bypassed; grant this exact brain directory when needed.

Target-project instructions own project engineering constraints. The brain supplies
cross-project workflow preferences and references, not permission to override them.
``rules\USER.local.md`` is optional local configuration, never a background memory input.

For durable non-sensitive engineering lessons, follow ``contexts\memory\INBOX.md`` and
use the transactional capture CLI; never append to generated Markdown. Do not capture
personal profiles, identity, employment, financial/health/legal/relationship data,
confidential business data, credentials, source code, or raw conversations.
Weekly outputs are proposals only; apply rules only after explicit user review.
Keep long-task checkpoints in the target project's approved local artifact directory.
$end
"@
if (-not $PSCmdlet.ShouldProcess($file, 'Install native skill and managed global brain entry')) { return }
& copilot skill add (Join-Path $PSScriptRoot 'skills')
if ($LASTEXITCODE -ne 0) { throw 'Native skill registration failed.' }
New-Item -ItemType Directory -Path $homeDirectory -Force | Out-Null
$existing = if (Test-Path -LiteralPath $file) { Get-Content -LiteralPath $file -Raw } else { '' }
if ($existing.Contains($start) -xor $existing.Contains($end)) {
    throw 'Incomplete brain marker block; inspect the global instructions before editing.'
}
if ($existing.Contains($start)) {
    $pattern = '(?s)' + [regex]::Escape($start) + '.*?' + [regex]::Escape($end)
    $updated = [regex]::Replace($existing, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block })
} else {
    $updated = $existing.TrimEnd() + "`n`n" + $block + "`n"
}
$temporary = "$file.brain-tmp"
try {
    [IO.File]::WriteAllText($temporary, $updated, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $file -Force
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}
Write-Output "Global brain entry installed: $file"
