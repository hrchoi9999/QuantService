param(
    [string]$SourcePath = "D:\QuantService",
    [string]$BackupRoot = "D:\QuantBackup\QuantService",
    [int]$KeepLatest = 1,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $BackupRoot "logs"
$logPath = Join-Path $logDir ("quantservice_backup_{0}.log" -f (Get-Date -Format "yyyyMM"))
$stagingRoot = Join-Path $BackupRoot "_staging"
$stagingPath = Join-Path $stagingRoot "QuantService_$timestamp"
$zipPath = Join-Path $BackupRoot "QuantService_$timestamp.zip"
$checksumPath = "$zipPath.sha256"
$latestInfo = Join-Path $BackupRoot "latest_backup.txt"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

function Assert-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside expected root: $fullPath"
    }
}

New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

Assert-PathInside -Path $stagingPath -Root $BackupRoot
Assert-PathInside -Path $zipPath -Root $BackupRoot

Write-Log "Backup started. source=$SourcePath keep_latest=$KeepLatest verify=$Verify"

if ($KeepLatest -ne 1) {
    Write-Log "KeepLatest override ignored. requested=$KeepLatest enforced=1"
    $KeepLatest = 1
}

if (Test-Path -LiteralPath $stagingPath) {
    Remove-Item -Recurse -Force -LiteralPath $stagingPath
}
New-Item -ItemType Directory -Force -Path $stagingPath | Out-Null

$excludeDirs = @(
    ".git",
    ".venv",
    ".venv_32_backup",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "htmlcov"
)
$xdArgs = foreach ($item in $excludeDirs) { "/XD"; (Join-Path $SourcePath $item) }
$robocopyArgs = @(
    $SourcePath,
    $stagingPath,
    "/E",
    "/R:1",
    "/W:1",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
) + $xdArgs

& robocopy @robocopyArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -gt 7) {
    Write-Log "Backup failed during robocopy. exit_code=$rc"
    throw "robocopy failed with exit code $rc"
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -Force -LiteralPath $zipPath
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stagingPath,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

if ($Verify) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        if ($zip.Entries.Count -eq 0) {
            throw "backup zip is empty"
        }
    }
    finally {
        $zip.Dispose()
    }
}

$checksum = Get-FileHash -Path $zipPath -Algorithm SHA256
"$($checksum.Hash)  $(Split-Path -Leaf $zipPath)" | Set-Content -Path $checksumPath -Encoding ASCII

$gitHead = ""
try {
    $gitHead = (& git -C $SourcePath rev-parse --short HEAD).Trim()
}
catch {
    $gitHead = "unknown"
}

@(
    "backup_created_at=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')",
    "source=$SourcePath",
    "zip=$zipPath",
    "sha256=$($checksum.Hash)",
    "git_head=$gitHead",
    "keep_latest=$KeepLatest"
) | Set-Content -Path $latestInfo -Encoding UTF8

$oldBackups = Get-ChildItem -Path $BackupRoot -Filter "QuantService_*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepLatest

foreach ($old in $oldBackups) {
    $oldChecksum = "$($old.FullName).sha256"
    Remove-Item -Force -LiteralPath $old.FullName
    if (Test-Path -LiteralPath $oldChecksum) {
        Remove-Item -Force -LiteralPath $oldChecksum
    }
    Write-Log "Deleted old backup: $($old.Name)"
}

Remove-Item -Recurse -Force -LiteralPath $stagingPath
Write-Log "Backup completed. zip=$zipPath sha256=$($checksum.Hash) git_head=$gitHead"
Write-Output "Backup created: $zipPath"
Write-Output "SHA256: $($checksum.Hash)"
