param(
    [switch]$FullTests,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found at $python"
}

$targets = @(
    "service_platform\web\app.py",
    "service_platform\web\investment_portfolio_api.py",
    "service_platform\web\market_analysis_api.py",
    "service_platform\web\data_provider.py",
    "service_platform\web\user_snapshot_api.py",
    "scripts\validate_web_data.py"
)

Push-Location $root
try {
    & $python -m ruff check @targets
    if ($LASTEXITCODE -ne 0) {
        throw "ruff check failed"
    }

    & $python -m py_compile @targets
    if ($LASTEXITCODE -ne 0) {
        throw "py_compile failed"
    }

    if (-not $SkipTests) {
        if ($FullTests) {
            & $python -m pytest tests -q
        }
        else {
            & $python -m pytest `
                tests\test_web\test_data_provider.py `
                tests\test_web\test_tseries_api.py `
                tests\test_publishers `
                -q
        }
        if ($LASTEXITCODE -ne 0) {
            throw "pytest failed"
        }
    }

    Write-Host "Quality checks passed."
}
finally {
    Pop-Location
}
