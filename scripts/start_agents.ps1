$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$Root'; & '$Python' -m bahulam_poc.agents.setup_server"
)
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$Root'; & '$Python' -m bahulam_poc.agents.builder_server"
)

Write-Host "Started Workspace Setup Agent (9101) and Code Builder Agent (9102)." -ForegroundColor Green
Write-Host "In another terminal run: .\.venv\Scripts\python.exe -m bahulam_poc.health_check"
