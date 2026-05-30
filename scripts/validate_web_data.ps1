param(
    [string]$QuantServiceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$UserMaxAgeDays = 10,
    [int]$MarketMaxAgeDays = 2,
    [int]$PortfolioMaxAgeDays = 5
)

$ErrorActionPreference = "Stop"
$python = Join-Path $QuantServiceRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found at $python"
}

& $python "$PSScriptRoot\validate_web_data.py" `
    --root $QuantServiceRoot `
    --user-max-age-days $UserMaxAgeDays `
    --market-max-age-days $MarketMaxAgeDays `
    --portfolio-max-age-days $PortfolioMaxAgeDays

if ($LASTEXITCODE -ne 0) {
    throw "web data validation failed"
}
