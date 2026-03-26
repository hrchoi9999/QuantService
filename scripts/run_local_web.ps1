$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "Python not found at $python"
    exit 1
}
Start-Process -FilePath 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    -ArgumentList '-NoExit', '-Command', "Set-Location '$root'; & '$python' -m service_platform.web.app"
Write-Host 'Started local web server in a new PowerShell window.'
Write-Host 'Open: http://127.0.0.1:8000/login'
