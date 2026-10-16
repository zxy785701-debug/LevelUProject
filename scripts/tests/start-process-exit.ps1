# Exercise the launcher's actual process helper without starting the app or MySQL.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$launcherPath = Join-Path $projectRoot 'scripts/start.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($launcherPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher syntax is invalid.' }
$helper = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-LoggedProcess' }, $true)
if (-not $helper) { throw 'Process helper was not found.' }
. ([scriptblock]::Create($helper.Extent.Text))
$logs = Join-Path $projectRoot 'backend/logs/launcher-exit-regression'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$results = @()
foreach ($expected in @(0, 7)) {
    $prefix = Join-Path $logs "exit-$expected"
    $child = Start-LoggedProcess $env:ComSpec @('/d', '/c', 'exit', '/b', "$expected") $projectRoot $prefix -Wait
    $deadline = (Get-Date).AddSeconds(10)
    while (-not $child.HasExited -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 50; $child.Refresh() }
    $actual = $child.ExitCode
    $results += [pscustomobject]@{ expected = $expected; actual = $actual; passed = $child.HasExited -and $null -ne $actual -and $actual -eq $expected }
}
$report = [pscustomobject]@{ powershell = $PSVersionTable.PSVersion.ToString(); passed = @($results | Where-Object { -not $_.passed }).Count -eq 0; results = $results }
$report | ConvertTo-Json -Depth 4
if (-not $report.passed) { throw 'Launcher lost a native process exit code.' }
