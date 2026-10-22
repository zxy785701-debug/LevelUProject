[CmdletBinding()]
param([switch]$Check,[switch]$Status)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
$workerArguments = @('-m','app.knowledge.worker')
if ($Check) { $workerArguments += '--check' }
if ($Status) { $workerArguments += '--status' }
& .venv/Scripts/python.exe @workerArguments
exit $LASTEXITCODE
