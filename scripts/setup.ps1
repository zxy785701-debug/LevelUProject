$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
python -m venv backend/.venv
if ($LASTEXITCODE -ne 0) { python -m venv --without-pip backend/.venv }
python -m pip --python backend/.venv/Scripts/python.exe install -r backend/requirements.lock --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
npm ci --registry=https://registry.npmjs.org
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
Write-Host '依赖已安装。请在 backend/.env 配置密钥，然后运行启动脚本。'
