# Stitch redesign preview analysis

Date: 2026-06-18

## Conclusion

The previous redesign attempt did not look like the Stitch deliverable because it changed QS CSS tokens and overrode parts of the existing QS templates, but it did not actually use the Stitch page structures.

## Root causes

1. The production root route `/` renders `market_analysis.html`, not `home.html`.
   - The earlier home redesign work did not affect the first page the user checks.

2. Existing QS templates remained the source of truth.
   - `_redesign_market_analysis.html`, `_redesign_today.html`, and related templates kept the current QS component hierarchy.
   - Applying Stitch colors to those components made the page look like the old page with minor style changes.

3. The structural Stitch HTML was not served as a preview.
   - Stitch `pc_1` through `pc_4` are full standalone layouts.
   - They require template migration, not only CSS overrides.

4. Font fallback hid design differences.
   - Stitch used `Hanken Grotesk`, but Korean text fell back to the browser/system Korean font.
   - Preview pages now explicitly use Pretendard for Korean text and JetBrains Mono for numeric/terminal-style labels.

5. The failed structural override was unsafe.
   - CSS grid overrides were applied to live QS data templates.
   - That distorted the market briefing layout because the QS DOM did not match Stitch's DOM.

## Preview policy

The Stitch redesign is now isolated under:

- `/stitch-preview`
- `/stitch-preview/market`
- `/stitch-preview/today`
- `/stitch-preview/models`
- `/stitch-preview/portfolio`
- `/stitch-preview/mobile`

These paths are for design review only. They are not wired to production QS data and must not replace the official redbot.co.kr pages until the user explicitly approves.

## Migration approach

1. Review the raw Stitch preview pages first.
2. Decide which Stitch page maps to each QS page.
3. Rebuild QS templates page by page using the Stitch layout as the target DOM structure.
4. Keep preview routes available for side-by-side comparison.
5. Only after full-page visual approval, merge the migrated templates into the production routes.
6. Do not deploy production route changes without explicit user confirmation.
