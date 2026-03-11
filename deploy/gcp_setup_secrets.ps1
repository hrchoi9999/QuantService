param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web",
    [string]$SessionSecretName = "redbot-session-secret",
    [string]$FeedbackAdminSecretName = "redbot-feedback-admin-key",
    [string]$LightPayMidSecretName = "redbot-lightpay-mid",
    [string]$LightPayMerchantKeySecretName = "redbot-lightpay-merchant-key",
    [string]$LightPayMidValue = "",
    [string]$LightPayMerchantKeyValue = "",
    [switch]$RotateSessionSecret,
    [switch]$RotateFeedbackAdminKey
)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"

if (-not (Test-Path $gcloud)) {
    throw "gcloud CLI not found at $gcloud"
}

function New-RandomSecret([int]$bytes = 32) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer)
}

function Test-SecretExists([string]$SecretName) {
    $result = & $gcloud secrets list --project $ProjectId --filter="name:$SecretName" --format="value(name)"
    return ($result -split "`n" | Where-Object { $_.Trim() -eq $SecretName }).Count -gt 0
}

function Ensure-SecretVersion([string]$SecretName, [string]$SecretValue) {
    $tmpFile = Join-Path $env:TEMP ("{0}.txt" -f ([guid]::NewGuid().ToString()))
    try {
        Set-Content -Path $tmpFile -Value $SecretValue -Encoding utf8
        if (-not (Test-SecretExists $SecretName)) {
            & $gcloud secrets create $SecretName --project $ProjectId --replication-policy="automatic" --data-file=$tmpFile | Out-Null
        }
        else {
            & $gcloud secrets versions add $SecretName --project $ProjectId --data-file=$tmpFile | Out-Null
        }
    }
    finally {
        if (Test-Path $tmpFile) {
            Remove-Item $tmpFile -Force
        }
    }
}

& $gcloud config configurations activate quantservice | Out-Null
& $gcloud config set project $ProjectId | Out-Null
& $gcloud config set run/region $Region | Out-Null

$projectNumber = & $gcloud projects describe $ProjectId --format="value(projectNumber)"
$serviceAccount = "$projectNumber-compute@developer.gserviceaccount.com"

$sessionValue = if ($RotateSessionSecret) { New-RandomSecret } else { "KEEP_EXISTING" }
$adminValue = if ($RotateFeedbackAdminKey) { New-RandomSecret 24 } else { "KEEP_EXISTING" }
$midValue = if ($LightPayMidValue) { $LightPayMidValue } else { "SET_ME_BEFORE_BILLING_ENABLED" }
$keyValue = if ($LightPayMerchantKeyValue) { $LightPayMerchantKeyValue } else { "SET_ME_BEFORE_BILLING_ENABLED" }

if ($sessionValue -ne "KEEP_EXISTING") {
    Ensure-SecretVersion -SecretName $SessionSecretName -SecretValue $sessionValue
}
elseif (-not (Test-SecretExists $SessionSecretName)) {
    Ensure-SecretVersion -SecretName $SessionSecretName -SecretValue (New-RandomSecret)
}

if ($adminValue -ne "KEEP_EXISTING") {
    Ensure-SecretVersion -SecretName $FeedbackAdminSecretName -SecretValue $adminValue
}
elseif (-not (Test-SecretExists $FeedbackAdminSecretName)) {
    Ensure-SecretVersion -SecretName $FeedbackAdminSecretName -SecretValue (New-RandomSecret 24)
}

if (-not (Test-SecretExists $LightPayMidSecretName)) {
    Ensure-SecretVersion -SecretName $LightPayMidSecretName -SecretValue $midValue
}
elseif ($LightPayMidValue) {
    Ensure-SecretVersion -SecretName $LightPayMidSecretName -SecretValue $LightPayMidValue
}

if (-not (Test-SecretExists $LightPayMerchantKeySecretName)) {
    Ensure-SecretVersion -SecretName $LightPayMerchantKeySecretName -SecretValue $keyValue
}
elseif ($LightPayMerchantKeyValue) {
    Ensure-SecretVersion -SecretName $LightPayMerchantKeySecretName -SecretValue $LightPayMerchantKeyValue
}

$secretNames = @(
    $SessionSecretName,
    $FeedbackAdminSecretName,
    $LightPayMidSecretName,
    $LightPayMerchantKeySecretName
)

foreach ($secretName in $secretNames) {
    & $gcloud secrets add-iam-policy-binding $secretName `
        --project $ProjectId `
        --member="serviceAccount:$serviceAccount" `
        --role="roles/secretmanager.secretAccessor" | Out-Null
}

Write-Host "Secrets prepared for service account $serviceAccount"
