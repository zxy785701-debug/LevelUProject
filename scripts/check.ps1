$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
& .venv/Scripts/python.exe -m pytest --cov=app --cov-branch --cov-report=term-missing
if ($LASTEXITCODE -ne 0) { throw '后端测试失败' }
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
npm test
if ($LASTEXITCODE -ne 0) { throw '前端状态测试失败' }
npm run typecheck
if ($LASTEXITCODE -ne 0) { throw '类型检查失败' }
