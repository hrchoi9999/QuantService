# QuantService

QuantService is the collaboration repository for the web service layer of the stock recommendation product.

This repository is for:
- web application code
- snapshot publishing pipeline
- deployment and operations scripts
- tests for the service platform

This repository is not for:
- quant model source code
- model training data or research data
- private planning or task documents
- runtime databases, logs, backups, or published snapshot artifacts

## Scope

The service reads pre-generated snapshots and renders them for the web.

It does not run quant models in real time.

## Main Directories

- `service_platform/`: web, publisher, feedback, shared modules
- `deploy/`: deployment and batch execution scripts
- `scripts/`: operations helpers, smoke tests, backup and restore scripts
- `tests/`: service-platform tests

## Local Development

Recommended environment:
- Python `3.10.11`
- `venv` 64-bit

Install dependencies:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run the web app:

```powershell
.\.venv\Scripts\python -m service_platform.web.app
```

Run the daily publish job:

```powershell
.\deploy\publish_daily.ps1 -Asof 2026-03-11
```

Run tests:

```powershell
.\.venv\Scripts\python -m pytest tests -q
```

Run the deploy quality gate:

```powershell
.\scripts\check_quality.ps1
```

Validate web handoff data before GCS upload:

```powershell
.\scripts\validate_web_data.ps1
```

Refresh local fallback web data from Quant, QuantMarket, and QuantAnalysis:

```powershell
.\scripts\sync_web_data_to_quantservice.ps1
```

This local sync is for backup and recovery. Source threads publish their current web JSON directly to GCS, and production reads the GCS current objects. Use `-PublishToGcs` only for explicit recovery publishing from QS.

Investment portfolio production source:

```powershell
INVESTMENT_PORTFOLIO_URL=https://storage.googleapis.com/quantservice-489808-market-analysis/admin/current/investment_portfolio_latest.json
INVESTMENT_PORTFOLIO_ALLOW_LOCAL_FALLBACK=false
```

Create a verified local repository backup. QS-Master owns this operation, and only the latest
backup set is retained:

```powershell
.\scripts\backup_quantservice.ps1 -Verify
```

## Repository Policy

Private materials are managed outside this repository.

Ignored by Git:
- `quant_models/`
- `docs/`
- `tests/fixtures/adapters/`
- `data/` runtime contents
- `service_platform/web/public_data/` generated outputs
- `backups/`

## Deployment

Production service:
- [https://redbot.co.kr](https://redbot.co.kr)

Prepare or rotate Cloud Run secrets:

```powershell
.\deploy\gcp_setup_secrets.ps1
```

Deploy to Cloud Run with Secret Manager bindings:

```powershell
.\deploy\cloud_run_deploy.ps1
```

Billing-related runtime flags:
- `BILLING_ENABLED=false` keeps billing routes disabled.
- `BILLING_MODE=test|prod` switches LightPay endpoints.
- `LIGHTPAY_NOTIFY_ALLOWED_IPS` can be set to a comma-separated allowlist when the provider shares fixed webhook source IPs.
