$ErrorActionPreference = 'Stop'
$repository = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repository 'apps/api/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python 3.12 API virtual environment required; see docs/M1_1B_3_E2E.md.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 22 required.' }
$web = Join-Path $repository 'apps/web'
if (-not (Test-Path -LiteralPath (Join-Path $web 'node_modules'))) { throw 'Install project dependencies first; see docs/M1_1B_3_E2E.md.' }
$env:PATHWISE_E2E_PYTHON = $python
Push-Location $web
try {
    Write-Host 'Synthetic data only. Edge: http://127.0.0.1:15173. Ctrl+C stops services and removes this isolated run.'
    npm run e2e:manual
    if ($LASTEXITCODE -ne 0) { throw 'Isolated preview refused/failed; no development fallback.' }
} finally { Pop-Location }
