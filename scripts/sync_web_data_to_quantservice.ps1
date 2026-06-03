param(
    [string]$QuantRoot = "D:\Quant",
    [string]$QuantMarketRoot = "D:\QuantMarket",
    [string]$QuantAnalysisRoot = "D:\QuantAnalysis",
    [string]$QuantServiceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$GcsBucket = "quantservice-489808-market-analysis",
    [switch]$PublishToGcs,
    [switch]$SkipGcs,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$gcsUpload = [bool]$PublishToGcs -and -not [bool]$SkipGcs

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source file: $Source"
    }
    Ensure-Directory -Path (Split-Path -Parent $Destination)
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    return (Get-Item -LiteralPath $Destination)
}

function Copy-JsonDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$DestinationDir
    )
    if (-not (Test-Path -LiteralPath $SourceDir)) {
        throw "Missing source directory: $SourceDir"
    }
    Ensure-Directory -Path $DestinationDir
    $copied = @()
    foreach ($file in Get-ChildItem -LiteralPath $SourceDir -Filter "*.json" -File) {
        $destination = Join-Path $DestinationDir $file.Name
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        $copied += (Get-Item -LiteralPath $destination)
    }
    return $copied
}

function Resolve-Gcloud {
    $bundled = Join-Path $env:LOCALAPPDATA "GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"
    if (Test-Path -LiteralPath $bundled) {
        return $bundled
    }
    $command = Get-Command gcloud -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "gcloud not found"
}

function Upload-GcsFile {
    param(
        [Parameter(Mandatory = $true)][string]$GcloudPath,
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target
    )
    & $GcloudPath storage cp $Source $Target --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud storage cp failed: $Source -> $Target"
    }
}

$quantCurrentDir = Join-Path $QuantRoot "service_platform\web\public_data\current"
$quantHistoryDir = Join-Path $QuantRoot "service_platform\web\public_data\history"
$marketHandoffDir = Join-Path $QuantMarketRoot "service_platform\web\public_data\handoff\quantservice\current"
$portfolioSource = Join-Path $QuantAnalysisRoot "outputs\investment_portfolio_latest.json"

$servicePublicDir = Join-Path $QuantServiceRoot "service_platform\web\public_data"
$serviceUserCurrentDir = Join-Path $servicePublicDir "user_current"
$serviceHistoryDir = Join-Path $servicePublicDir "history"
$serviceTseriesCurrentDir = Join-Path $servicePublicDir "tseries_discovery\current"
$serviceMarketCurrentDir = Join-Path $servicePublicDir "market_analysis\current"
$servicePortfolioCurrentDir = Join-Path $QuantServiceRoot "service_platform\web\admin_data\current"

$copiedUser = Copy-JsonDirectory -SourceDir $quantCurrentDir -DestinationDir $serviceUserCurrentDir
$copiedHistory = Copy-JsonDirectory -SourceDir $quantHistoryDir -DestinationDir $serviceHistoryDir
$copiedMarket = Copy-JsonDirectory -SourceDir $marketHandoffDir -DestinationDir $serviceMarketCurrentDir
$copiedPortfolio = Copy-RequiredFile `
    -Source $portfolioSource `
    -Destination (Join-Path $servicePortfolioCurrentDir "investment_portfolio_latest.json")
$copiedTseries = Copy-RequiredFile `
    -Source (Join-Path $quantCurrentDir "quantservice_tseries_discovery.json") `
    -Destination (Join-Path $serviceTseriesCurrentDir "quantservice_tseries_discovery.json")

if (-not $SkipValidation) {
    & "$PSScriptRoot\validate_web_data.ps1" -QuantServiceRoot $QuantServiceRoot
    if ($LASTEXITCODE -ne 0) {
        throw "web data validation failed"
    }
}

if ($gcsUpload) {
    $gcloud = Resolve-Gcloud
    & $gcloud config configurations activate quantservice | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "failed to activate gcloud configuration: quantservice"
    }

    Upload-GcsFile `
        -GcloudPath $gcloud `
        -Source $copiedPortfolio.FullName `
        -Target "gs://$GcsBucket/admin/current/investment_portfolio_latest.json"

    foreach ($file in $copiedUser) {
        if ($file.Name -ne "quantservice_tseries_discovery.json") {
            Upload-GcsFile -GcloudPath $gcloud -Source $file.FullName -Target "gs://$GcsBucket/$($file.Name)"
        }
    }
    foreach ($file in $copiedHistory) {
        Upload-GcsFile -GcloudPath $gcloud -Source $file.FullName -Target "gs://$GcsBucket/history/$($file.Name)"
    }
    Upload-GcsFile `
        -GcloudPath $gcloud `
        -Source $copiedTseries.FullName `
        -Target "gs://$GcsBucket/tseries_discovery/current/quantservice_tseries_discovery.json"
    foreach ($file in $copiedMarket) {
        $prefix = "market_analysis/current"
        if ($file.Name -like "*_history.json") {
            $prefix = "market_analysis/history"
        }
        Upload-GcsFile -GcloudPath $gcloud -Source $file.FullName -Target "gs://$GcsBucket/$prefix/$($file.Name)"
    }
}

[pscustomobject]@{
    QuantUserFiles = $copiedUser.Count
    QuantHistoryFiles = $copiedHistory.Count
    QuantMarketFiles = $copiedMarket.Count
    TSeriesFile = $copiedTseries.FullName
    PortfolioFile = $copiedPortfolio.FullName
    GcsUpload = $gcsUpload
    Mode = if ($gcsUpload) { "recovery-gcs-publish" } else { "local-fallback-refresh" }
    SyncedAt = (Get-Date).ToString("s")
} | ConvertTo-Json -Depth 3
