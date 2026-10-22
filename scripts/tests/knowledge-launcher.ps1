# Exercise the actual launch/stop helpers with two harmless, explicitly owned processes.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'scripts/start.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher syntax is invalid.' }
foreach ($name in @('Start-LoggedProcess','Stop-OwnedProcess','Get-KnowledgeWorkerPlan')) {
    $helper = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (-not $helper) { throw "Missing $name" }
    . ([scriptblock]::Create($helper.Extent.Text))
}
$logRoot = Join-Path $projectRoot 'backend/logs/knowledge-launcher-smoke'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$sleeper = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $sleeper)) { $sleeper = (Get-Command powershell.exe).Source }
$ours = $null
$other = $null
try {
    $ours = Start-LoggedProcess $sleeper @('-NoProfile','-Command','Start-Sleep -Seconds 30') $projectRoot (Join-Path $logRoot 'ours')
    $other = Start-LoggedProcess $sleeper @('-NoProfile','-Command','Start-Sleep -Seconds 30') $projectRoot (Join-Path $logRoot 'other')
    Stop-OwnedProcess $ours
    $ours.WaitForExit(5000) | Out-Null
    $other.Refresh()
    $passed = $ours.HasExited -and -not $other.HasExited
    [pscustomobject]@{passed=$passed;owned_stopped=$ours.HasExited;other_survived=(-not $other.HasExited)} | ConvertTo-Json
    if (-not $passed) { throw 'Launcher stopped a process it did not own or failed to stop its own child.' }
} finally {
    if ($ours) { Stop-OwnedProcess $ours }
    if ($other) { Stop-OwnedProcess $other }
}
