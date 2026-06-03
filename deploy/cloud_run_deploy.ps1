param(
    [string]$ProjectId = "quantservice-489808",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "quantservice-web",
    [string]$Repository = "quantservice",
    [string]$ImageName = "web",
    [string]$CloudBuildBucketName = "quantservice-489808-cloudbuild-asia-northeast3",
    [string]$PublicBaseUrl = "https://redbot.co.kr",
    [string]$SnapshotSource = "remote",
    [string]$SnapshotGcsBaseUrl = "https://storage.googleapis.com/quantservice-489808-market-analysis",
    [string]$MarketAnalysisSource = "remote",
    [string]$MarketAnalysisBaseUrl = "https://storage.googleapis.com/quantservice-489808-market-analysis/market_analysis/current",
    [string]$InvestmentPortfolioUrl = "https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json",
    [bool]$InvestmentPortfolioAllowLocalFallback = $false,
    [string]$InvestmentStorageSource = "gcs",
    [string]$InvestmentGcsBucket = "quantservice-489808-private-investments",
    [string]$InvestmentGcsPrefix = "investment_status",
    [string]$AnalyticsPreviewAllowedEmails = "hrchoi@koreascf.com",
    [string]$BootstrapAdminEmail = "hrchoi@koreascf.com",
    [bool]$UiRedesignEnabled = $true,
    [ValidateSet("light", "dark", "system")]
    [string]$UiThemeDefault = "light",
    [bool]$BillingEnabled = $false,
    [ValidateSet("test", "prod")]
    [string]$BillingMode = "test",
    [int]$BillingCycleDays = 30,
    [string]$BillingCurrency = "KRW",
    [string]$NotifyAllowedIps = "",
    [string]$SessionSecretName = "redbot-session-secret",
    [string]$FeedbackAdminSecretName = "redbot-feedback-admin-key",
    [string]$LightPayMidSecretName = "redbot-lightpay-mid",
    [string]$LightPayMerchantKeySecretName = "redbot-lightpay-merchant-key",
    [string]$BootstrapAdminPasswordSecretName = "redbot-bootstrap-admin-password"
)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\GoogleCloudSDK\google-cloud-sdk\bin\gcloud.cmd"

if (-not (Test-Path $gcloud)) {
    throw "gcloud CLI not found at $gcloud"
}

$imageTag = Get-Date -Format "yyyyMMdd-HHmmss"
$tag = "$Region-docker.pkg.dev/$ProjectId/$Repository/${ImageName}:$imageTag"
$latestTag = "$Region-docker.pkg.dev/$ProjectId/$Repository/${ImageName}:latest"
$cloudBuildBucketUri = "gs://$CloudBuildBucketName"
$cloudBuildSourceStagingDir = "$cloudBuildBucketUri/source"
$cloudBuildLogDir = "$cloudBuildBucketUri/logs"

& $gcloud config configurations activate quantservice | Out-Null
& $gcloud config set project $ProjectId | Out-Null
& $gcloud config set run/region $Region | Out-Null

$repositories = & $gcloud artifacts repositories list --project $ProjectId --location $Region --format="value(name.basename())"
if ($repositories -notcontains $Repository) {
    & $gcloud artifacts repositories create $Repository --repository-format=docker --location=$Region --description="QuantService container images"
}

$buildBuckets = & $gcloud storage buckets list --project $ProjectId --format="value(name)"
if ($buildBuckets -notcontains $CloudBuildBucketName) {
    & $gcloud storage buckets create $cloudBuildBucketUri --project $ProjectId --location=$Region --uniform-bucket-level-access | Out-Null
}

& $gcloud builds submit --tag $tag . --gcs-source-staging-dir $cloudBuildSourceStagingDir --gcs-log-dir $cloudBuildLogDir
& $gcloud artifacts docker tags add $tag $latestTag | Out-Null

$projectNumber = & $gcloud projects describe $ProjectId --format="value(projectNumber)"
$serviceAccount = "$projectNumber-compute@developer.gserviceaccount.com"
$tmpFile = Join-Path $env:TEMP ("cloudrun-{0}.yaml" -f ([guid]::NewGuid().ToString()))
$billingEnabledValue = $BillingEnabled.ToString().ToLowerInvariant()
$uiRedesignEnabledValue = $UiRedesignEnabled.ToString().ToLowerInvariant()
$investmentPortfolioAllowLocalFallbackValue = $InvestmentPortfolioAllowLocalFallback.ToString().ToLowerInvariant()

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
        - name: SNAPSHOT_GCS_BASE_URL
          value: $SnapshotGcsBaseUrl
        - name: USER_SNAPSHOT_DIR
          value: /app/service_platform/web/public_data/user_current
        - name: MARKET_ANALYSIS_SOURCE
          value: $MarketAnalysisSource
        - name: MARKET_ANALYSIS_BASE_URL
          value: $MarketAnalysisBaseUrl
        - name: INVESTMENT_PORTFOLIO_URL
          value: $InvestmentPortfolioUrl
        - name: INVESTMENT_PORTFOLIO_ALLOW_LOCAL_FALLBACK
          value: '$investmentPortfolioAllowLocalFallbackValue'
        - name: INVESTMENT_STORAGE_SOURCE
          value: $InvestmentStorageSource
        - name: INVESTMENT_GCS_BUCKET
          value: $InvestmentGcsBucket
        - name: INVESTMENT_GCS_PREFIX
          value: $InvestmentGcsPrefix
        - name: ANALYTICS_PREVIEW_ALLOWED_EMAILS
          value: $AnalyticsPreviewAllowedEmails
        - name: BOOTSTRAP_ADMIN_EMAIL
          value: $BootstrapAdminEmail
        - name: UI_REDESIGN_ENABLED
          value: '$uiRedesignEnabledValue'
        - name: UI_THEME_DEFAULT
          value: $UiThemeDefault
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
        - name: BOOTSTRAP_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: $BootstrapAdminPasswordSecretName
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
