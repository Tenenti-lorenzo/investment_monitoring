$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "PortfolioLab avviato su http://localhost:8000"
& ".\.venv\Scripts\uvicorn.exe" backend.main:app --reload --port 8000
