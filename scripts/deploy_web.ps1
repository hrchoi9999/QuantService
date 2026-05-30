param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web"
)

$ErrorActionPreference = "Stop"
& "$PSScriptRoot\check_quality.ps1"
if ($LASTEXITCODE -ne 0) {
    throw "quality gate failed"
}
& "$PSScriptRoot\..\deploy\cloud_run_deploy.ps1" -ProjectId $ProjectId -Region $Region -ServiceName $ServiceName
