$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
& .venv/Scripts/python.exe -m app.migrate
if ($LASTEXITCODE -ne 0) { throw 'MySQL migration failed; check backend/.env configuration.' }
# Local development: reload Python application changes so newly added routes
# cannot remain absent until a manual restart. Migrations still run before start.
& .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
