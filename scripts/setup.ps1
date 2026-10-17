# One-shot setup on Windows:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -q -e .

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Install it:  winget install Ollama.Ollama   (or https://ollama.com/download)" -ForegroundColor Yellow
} else {
    $model = if ($env:REPOMEDIC_MODEL) { $env:REPOMEDIC_MODEL } else { "gemma4:e4b" }
    Write-Host "Pulling $model ..."
    ollama pull $model
}

.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests
Write-Host "`nReady. Try:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\repomedic scan bench\buggy_shop"
Write-Host "  .\.venv\Scripts\repomedic serve      # http://127.0.0.1:8765"
