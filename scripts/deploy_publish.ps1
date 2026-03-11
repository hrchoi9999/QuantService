param(
    [string]$Asof,
    [string]$OutDir = "service_platform/web/public_data",
    [string]$Models,
    [int]$KeepDays = 14,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$arguments = @{}
if ($Asof) { $arguments.Asof = $Asof }
if ($Models) { $arguments.Models = $Models }
$arguments.OutDir = $OutDir
$arguments.KeepDays = $KeepDays
if ($Force) { $arguments.Force = $true }
& "$PSScriptRoot\..\deploy\publish_daily.ps1" @arguments
