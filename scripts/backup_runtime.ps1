param(
    [string]$SourceDir = "service_platform/web/public_data",
    [string]$FeedbackDb = "data/feedback.db",
    [string]$AlertLog = "data/alerts.log",
    [string]$BackupDir = "backups",
    [string]$GcsBucket = ""
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir $timestamp
New-Item -ItemType Directory -Force -Path $target | Out-Null

Copy-Item "$SourceDir\current" -Destination $target -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$SourceDir\published" -Destination $target -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $FeedbackDb -Destination $target -Force -ErrorAction SilentlyContinue
Copy-Item $AlertLog -Destination $target -Force -ErrorAction SilentlyContinue

$zipPath = "$target.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$target\*" -DestinationPath $zipPath -Force
Write-Host "Backup created: $zipPath"

if ($GcsBucket) {
    $gcloud = "$env:LOCALAPPDATA\GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"
    if (-not (Test-Path $gcloud)) {
        throw "gcloud CLI not found at $gcloud"
    }
    & $gcloud storage cp $zipPath "$GcsBucket/ops-backups/"
}
