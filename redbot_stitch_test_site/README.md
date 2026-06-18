# REDBOT Stitch Test Site

Standalone redesign test site for the institutional/trading terminal direction from the Stitch v2 design files.

This directory is intentionally separate from the current `redbot.co.kr` Flask/QS source and the older `/stitch-preview` experiment.

## Policy

- Do not wire this site into production routes yet.
- Do not deploy this site without explicit user approval.
- Use Pretendard for Korean UI text and JetBrains Mono for numeric/terminal labels.
- Keep production `service_platform` pages unchanged until the redesign is fully reviewed.

## Pages

- `index.html`: dashboard and market briefing
- `markets.html`: market analysis
- `models.html`: quant model command view
- `portfolio.html`: portfolio strategy view
- `reports.html`: report/archive view
- `font-samples.html`: Korean font comparison reference

## Local Preview

```powershell
cd D:\QuantService\redbot_stitch_test_site
python -m http.server 5173 --bind 127.0.0.1
```

Open `http://127.0.0.1:5173/`.
