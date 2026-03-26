Get-Process | Where-Object {
    $_.ProcessName -like 'python*' -and $_.Path -like '*QuantService*'
} | Stop-Process -Force
Write-Host 'Stopped local QuantService Python processes.'
