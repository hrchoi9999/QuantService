# RedBot Stitch Test Site

This is a standalone redesign test site built from the initial Stitch design file.

It is intentionally separate from the current `redbot.co.kr` Flask/QS source.

## Policy

- Do not wire this site into the production redbot.co.kr routes.
- Do not deploy this site to production without explicit user approval.
- Use this directory as the parallel redesign test site until the redesign is approved.
- The older `/stitch-preview` pages in the QS app are not part of this workstream.

## Local Preview

```powershell
cd D:\QuantService\redbot_stitch_test_site
python -m http.server 5061
```

Open:

```text
http://127.0.0.1:5061/
```

