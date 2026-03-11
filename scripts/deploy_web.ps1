param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web"
)

$ErrorActionPreference = "Stop"
& "$PSScriptRoot\..\deploy\cloud_run_deploy.ps1" -ProjectId $ProjectId -Region $Region -ServiceName $ServiceName
