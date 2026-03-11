param(
    [string]$BaseUrl = "https://redbot.co.kr"
)

$ErrorActionPreference = "Stop"
$paths = @("/healthz", "/status", "/today")
foreach ($path in $paths) {
    $response = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + $path) -UseBasicParsing -TimeoutSec 20
    Write-Host "$path -> $($response.StatusCode)"
    if ($response.StatusCode -ne 200) {
        throw "Smoke test failed for $path"
    }
}
