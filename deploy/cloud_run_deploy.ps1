param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web",
    [string]$Repository = "quantservice",
    [string]$ImageName = "web",
    [string]$PublicBaseUrl = "https://redbot.co.kr",
    [string]$SnapshotSource = "local",
    [string]$MarketAnalysisSource = "remote",
    [string]$MarketAnalysisBaseUrl = "https://storage.googleapis.com/quantservice-489808-market-analysis/market_analysis/current",
    [string]$AnalyticsPreviewAllowedEmails = "hrchoi@koreascf.com",
    [bool]$BillingEnabled = $false,
    [ValidateSet("test", "prod")]
    [string]$BillingMode = "test",
    [int]$BillingCycleDays = 30,
    [string]$BillingCurrency = "KRW",
    [string]$NotifyAllowedIps = "",
    [string]$SessionSecretName = "redbot-session-secret",
    [string]$FeedbackAdminSecretName = "redbot-feedback-admin-key",
    [string]$LightPayMidSecretName = "redbot-lightpay-mid",
    [string]$LightPayMerchantKeySecretName = "redbot-lightpay-merchant-key"
)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"

if (-not (Test-Path $gcloud)) {
    throw "gcloud CLI not found at $gcloud"
}

$imageTag = Get-Date -Format "yyyyMMdd-HHmmss"
$tag = "$Region-docker.pkg.dev/$ProjectId/$Repository/${ImageName}:$imageTag"
$latestTag = "$Region-docker.pkg.dev/$ProjectId/$Repository/${ImageName}:latest"

& $gcloud config configurations activate quantservice | Out-Null
& $gcloud config set project $ProjectId | Out-Null
& $gcloud config set run/region $Region | Out-Null

$repositories = & $gcloud artifacts repositories list --project $ProjectId --location $Region --format="value(name.basename())"
if ($repositories -notcontains $Repository) {
    & $gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description="QuantService container images"
}

& $gcloud builds submit --tag $tag .
& $gcloud artifacts docker tags add $tag $latestTag | Out-Null

$projectNumber = & $gcloud projects describe $ProjectId --format="value(projectNumber)"
$serviceAccount = "$projectNumber-compute@developer.gserviceaccount.com"
$tmpFile = Join-Path $env:TEMP ("cloudrun-{0}.yaml" -f ([guid]::NewGuid().ToString()))
$billingEnabledValue = $BillingEnabled.ToString().ToLowerInvariant()

@"
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: $ServiceName
  namespace: '$projectNumber'
  labels:
    cloud.googleapis.com/location: $Region
  annotations:
    run.googleapis.com/ingress: all
    run.googleapis.com/maxScale: '20'
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: '20'
        run.googleapis.com/startup-cpu-boost: 'true'
    spec:
      containerConcurrency: 80
      serviceAccountName: $serviceAccount
      timeoutSeconds: 300
      containers:
      - image: $tag
        env:
        - name: APP_ENV
          value: production
        - name: WEB_HOST
          value: 0.0.0.0
        - name: SNAPSHOT_SOURCE
          value: $SnapshotSource
        - name: USER_SNAPSHOT_DIR
          value: /app/service_platform/web/public_data/user_current
        - name: MARKET_ANALYSIS_SOURCE
          value: $MarketAnalysisSource
        - name: MARKET_ANALYSIS_BASE_URL
          value: $MarketAnalysisBaseUrl
        - name: ANALYTICS_PREVIEW_ALLOWED_EMAILS
          value: $AnalyticsPreviewAllowedEmails
        - name: BILLING_ENABLED
          value: '$billingEnabledValue'
        - name: BILLING_MODE
          value: $BillingMode
        - name: BILLING_CYCLE_DAYS
          value: '$BillingCycleDays'
        - name: BILLING_CURRENCY
          value: $BillingCurrency
        - name: LIGHTPAY_RETURN_URL
          value: $PublicBaseUrl/billing/return
        - name: LIGHTPAY_NOTIFY_URL
          value: $PublicBaseUrl/billing/notify
        - name: LIGHTPAY_NOTIFY_ALLOWED_IPS
          value: '$NotifyAllowedIps'
        - name: SESSION_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: $SessionSecretName
              key: latest
        - name: FEEDBACK_ADMIN_KEY
          valueFrom:
            secretKeyRef:
              name: $FeedbackAdminSecretName
              key: latest
        - name: LIGHTPAY_MID
          valueFrom:
            secretKeyRef:
              name: $LightPayMidSecretName
              key: latest
        - name: LIGHTPAY_MERCHANT_KEY
          valueFrom:
            secretKeyRef:
              name: $LightPayMerchantKeySecretName
              key: latest
        ports:
        - containerPort: 8080
          name: http1
        resources:
          limits:
            cpu: 1000m
            memory: 512Mi
        startupProbe:
          failureThreshold: 1
          periodSeconds: 240
          tcpSocket:
            port: 8080
          timeoutSeconds: 240
  traffic:
  - latestRevision: true
    percent: 100
"@ | Set-Content $tmpFile -Encoding utf8

try {
    & $gcloud run services replace $tmpFile --region $Region
}
finally {
    if (Test-Path $tmpFile) {
        Remove-Item $tmpFile -Force
    }
}
