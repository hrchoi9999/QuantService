param(
    [string]$PublishedRoot = "service_platform/web/public_data/published",
    [string]$CurrentDir = "service_platform/web/public_data/current",
    [string]$VersionLabel
)

$ErrorActionPreference = "Stop"
if (-not $VersionLabel) {
    $dayDir = Get-ChildItem $PublishedRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $dayDir) { throw "No published day directory found." }
    $runDir = Get-ChildItem $dayDir.FullName -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $runDir) { throw "No published run directory found." }
    $sourceDir = $runDir.FullName
}
else {
    $sourceDir = Join-Path $PublishedRoot $VersionLabel
}

if (-not (Test-Path $sourceDir)) {
    throw "Published version not found: $sourceDir"
}

$tempBackup = "$CurrentDir.__rollback_backup"
if (Test-Path $tempBackup) { Remove-Item $tempBackup -Recurse -Force }
if (Test-Path $CurrentDir) { Rename-Item $CurrentDir $tempBackup }
Copy-Item $sourceDir -Destination $CurrentDir -Recurse -Force
if (Test-Path $tempBackup) { Remove-Item $tempBackup -Recurse -Force }
Write-Host "Current restored from: $sourceDir"
