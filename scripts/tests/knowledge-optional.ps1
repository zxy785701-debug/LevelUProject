$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'scripts/start.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher syntax is invalid.' }
foreach ($name in @('Start-LoggedProcess','Stop-OwnedProcess','Get-RunningDevelopmentProcesses')) {
    $helper = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (-not $helper) { throw "Missing $name" }
    . ([scriptblock]::Create($helper.Extent.Text))
}
$logRoot = Join-Path $projectRoot 'backend/logs/knowledge-optional-smoke'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$required = $null
try {
    $optional = Start-LoggedProcess $env:ComSpec @('/d','/c','exit','/b','7') $projectRoot (Join-Path $logRoot 'optional') -Wait
    $required = Start-LoggedProcess (Get-Command powershell.exe).Source @('-NoProfile','-Command','Start-Sleep -Seconds 20') $projectRoot (Join-Path $logRoot 'required')
    $live = @(Get-RunningDevelopmentProcesses @($optional,$required) $optional.Id)
    $required.Refresh()
    $blocked = $false
    try { Get-RunningDevelopmentProcesses @($optional) 0 | Out-Null } catch { $blocked = $true }
    $passed = $live.Count -eq 1 -and $live[0].Id -eq $required.Id -and -not $required.HasExited -and $blocked
    [pscustomobject]@{passed=$passed;optional_exit_ignored=($live.Count -eq 1);required_alive=(-not $required.HasExited);required_exit_detected=$blocked} | ConvertTo-Json
    if (-not $passed) { throw 'Optional executor failure interfered with required development processes.' }
} finally {
    if ($required) { Stop-OwnedProcess $required }
}
