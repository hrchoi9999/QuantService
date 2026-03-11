param(
    [string]$Asof,
    [string]$OutDir = "service_platform/web/public_data",
    [string]$Models,
    [int]$KeepDays = 14,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python executable not found at $python"
}

$arguments = @("-m", "service_platform.publishers.run_daily_publish", "--out-dir", $OutDir, "--keep-days", "$KeepDays")

if ($Asof) {
    $arguments += @("--asof", $Asof)
}

if ($Models) {
    $arguments += @("--models", $Models)
}

if ($Force) {
    $arguments += "--force"
}

& $python @arguments
