---
status: approved
---

# Scope Spec: Dashboard simplification

## Objective
Strip the unified QC dashboard to its information-bearing minimum:
one compact scope card, compact step status, and compact reportlet
link lists. Every redundant element and label gets removed.

## Constraints
- Must not change reportlet URLs — gallery + image paths stay so
  shared links keep working.
- Must keep all three cache-bust mechanisms intact (HTTP no-cache
  header, HTML meta, image `?v=mtime`).
- Must not regress the S1 HTML iframe embed or S10 release banner —
  those are content, not chrome.
- Must not lose information needed for QC (status counts per step,
  reportlet links). Only the *presentation* tightens.
- No new dependencies. Keep the dark theme + existing CSS variables.

## Deliverables
1. **Scope banner**: only the current workfolder's own scope is shown
   prominently. Other scopes (if any) collapse to a single-line
   "Other scopes: [smoke] [full]" chip row.
2. **Step cards**: replace `<div class="status-summary">Runs: X total,
   Y passed, Z warned, W failed</div>` with a single compact line of
   color-coded badges (e.g. `<span class="pill pass">9</span>
   <span class="pill warn">2</span>` next to the step h2).
3. **Reportlet list**: drop the `(N images)` / `(N reports)` suffix.
   Just the labeled link.
4. **Workfolder dropdown removed** entirely (CSS + HTML + JS). Cross-wf
   navigation lives in the scope banner only.
5. **Header**: replace `<h1>SpinalfMRIprep QC Dashboard</h1>` (24 px
   default) with a tighter `<h1>` (≈ 16 px) plus a small `<code>` chip
   showing the current wf name on the same line.
6. **Drop the `Reportlets` section sub-header** and any other
   ornamental `h2`/`h3` that doesn't carry data.
7. **Drop the per-step `<div class="status-summary">` wrapper** —
   inline the badges into the step `<h2>` row.

## Inputs
- `src/spinalfmriprep/qc_dashboard_html.py`
  (`_generate_index_html`, `_generate_workfolder_dropdown_html`)
- `src/spinalfmriprep/dashboard_latest.py`
  (`render_scope_banner`, `_scope_card_html`, `_SCOPE_CSS`)
- Existing live dashboards in `work/wf_reg_*/dashboard/`

## Success Criteria
- The latest dashboard (visit `https://271828.space/p2/`) shows the
  scope banner in a *single* card row (~80 px tall), the workfolder-
  name chip in the title bar, and the 11 step cards each ≤ 60 px tall
  before the reportlet links.
- Total dashboard scroll height for the wf_reg_071 dataset drops by
  ≥ 30 % vs current state.
- Reportlet galleries themselves are unchanged — clicking any reportlet
  label opens the same gallery as before.
- All three cache-bust mechanisms verified via `curl -D - …` on the
  live URL.

## Next Steps
1. Update `dashboard_latest.py`:
   `render_scope_banner(work_root, links_from, current_scope=None)` —
   when `current_scope` is given, render only that scope as a card and
   collapse others to a chip row.
2. Add a `current_scope` parameter to the call site in
   `qc_dashboard_html._generate_index_html` (derive from
   `out_dir.parents` / workfolder name prefix: `wf_reg_*` ⇒ "reg" etc.).
3. Replace `status-summary` div with inline badges; drop the
   `Reportlets` sub-header and `(N images)` suffix.
4. Remove `_generate_workfolder_dropdown_html` + all its CSS/HTML/JS
   slots from `_generate_index_html` and the reportlet gallery page.
5. Tighten the `<h1>` — combine title with a `<code>` wf-name chip.
6. Regenerate all dashboards via `scripts/refresh_dashboards.py`,
   restart the systemd `p2-dashboard` unit, verify externally.

## Decision Log
| Q# | Choice | Rationale |
|----|--------|-----------|
| Q1 | A — only current scope prominent, others as chips | reg is the daily scope; smoke/full are occasional and the 3-card view burns 250 px of real estate every page load |
| Q2 | A — compact reportlet link list, drop "(N images)" suffix | Inline thumbnails 200+ images/page; gallery click-through is the established pattern. The count was noise |
| Q3 | A — drop workfolder dropdown entirely | Duplicates the scope card's per-step deep links; removes dropdown JS/CSS complexity |
