$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
& .venv/Scripts/python.exe -m app.migrate
if ($LASTEXITCODE -ne 0) { throw 'MySQL 数据库迁移失败，请检查本地配置' }
& .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
