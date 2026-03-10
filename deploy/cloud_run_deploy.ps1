param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web",
    [string]$Repository = "quantservice",
    [string]$ImageName = "web"
)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"

if (-not (Test-Path $gcloud)) {
    throw "gcloud CLI not found at $gcloud"
}

$tag = "$Region-docker.pkg.dev/$ProjectId/$Repository/${ImageName}:latest"

& $gcloud config configurations activate quantservice | Out-Null
& $gcloud config set project $ProjectId | Out-Null
& $gcloud config set run/region $Region | Out-Null

$repositories = & $gcloud artifacts repositories list --project $ProjectId --location $Region --format="value(name.basename())"
if ($repositories -notcontains $Repository) {
    & $gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description="QuantService container images"
}

& $gcloud builds submit --tag $tag .

& $gcloud run deploy $ServiceName `
    --image $tag `
    --platform managed `
    --region $Region `
    --allow-unauthenticated `
    --port 8080 `
    --set-env-vars APP_ENV=production,WEB_HOST=0.0.0.0
