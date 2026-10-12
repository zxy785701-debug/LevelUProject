$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
& .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
