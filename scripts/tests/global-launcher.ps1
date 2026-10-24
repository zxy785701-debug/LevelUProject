# Cross-process duplicate-launch protection, including the root batch entry point.
# Does not start services, call models, or change the database.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'scripts/start.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher syntax is invalid.' }
$helper = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-LevelUpLauncherMutexName' }, $true)
if (-not $helper) { throw 'Launcher lock helper is missing.' }
. ([scriptblock]::Create($helper.Extent.Text))
$name = Get-LevelUpLauncherMutexName $projectRoot
if ($name -ne (Get-LevelUpLauncherMutexName ($projectRoot.ToLowerInvariant() + '\'))) {
    throw 'Equivalent project paths must use the same lock.'
}
if ($name -eq (Get-LevelUpLauncherMutexName (Join-Path $projectRoot 'another-project'))) {
    throw 'Independent checkouts must use different locks.'
}
$mutex = New-Object Threading.Mutex($false, $name)
$held = $false
$migrationLog = Join-Path $projectRoot 'backend/logs/start-migrate.log'
$before = if (Test-Path -LiteralPath $migrationLog) { (Get-Item -LiteralPath $migrationLog).LastWriteTimeUtc.Ticks } else { 0 }
try {
    try { $held = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'Stop the existing launcher before running this isolated lock test.' }
    Push-Location -LiteralPath $env:TEMP
    try {
        $output = & (Join-Path $projectRoot 'start.bat') -Target all 2>&1 | Out-String
        $childExit = $LASTEXITCODE
    } finally { Pop-Location }
    if ($childExit -ne 0 -or $output -notmatch 'already running' -or $output -match 'Applying database migrations') {
        throw 'Duplicate launch did not return cleanly before starting services.'
    }
    $after = if (Test-Path -LiteralPath $migrationLog) { (Get-Item -LiteralPath $migrationLog).LastWriteTimeUtc.Ticks } else { 0 }
    if ($before -ne $after) { throw 'Duplicate launch touched the migration log.' }
    Write-Output 'Global launcher: cross-process lock, duplicate no-op, path normalization, and launch from another directory PASS'
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
