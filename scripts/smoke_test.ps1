param(
    [string]$BaseUrl = "https://redbot.co.kr"
)

$ErrorActionPreference = "Stop"
$paths = @(
    "/healthz",
    "/status",
    "/today",
    "/market-analysis",
    "/investment-portfolio",
    "/api/v1/model-snapshots/today",
    "/api/v1/market-analysis/page",
    "/api/v1/market-analysis/manifest",
    "/api/v1/market-environment-indicators",
    "/api/v1/investment-portfolio",
    "/api/v1/discovery/t-series"
)
foreach ($path in $paths) {
    $response = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + $path) -UseBasicParsing -TimeoutSec 20
    Write-Host "$path -> $($response.StatusCode)"
    if ($response.StatusCode -ne 200) {
        throw "Smoke test failed for $path"
    }
}
