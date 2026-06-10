---
status: implemented
---

# Scope Spec: P2 Dashboard Server

## Objective
Wrap the existing static QC dashboard in a lightweight web server on localhost:9002, serving at `/`, accessible at `271828.space/p2/`.

## Constraints
- Must serve at `/` (Cloudflare Worker strips `/p2` prefix)
- Must not modify existing `qc_dashboard.py` / `qc_dashboard_html.py` logic
- Must serve reportlet images (PNGs) from workfolder paths outside the dashboard dir
- No auth required (Cloudflare/Tailscale handles access)
- Must run as a persistent systemd service

## Deliverables
- `src/spinalfmriprep/dashboard_server.py` — FastAPI app
  - `GET /` redirects to `/dashboard/index.html`
  - Static file serving from latest workfolder's `dashboard/` dir
  - `GET /__spinalfmriprep__/workfolders.json` — lists available workfolders
  - `GET /wf_{name}/dashboard/...` — serves from specific workfolder
  - Serves images from workfolder trees (resolving relative paths to PNGs)
- `scripts/p2-dashboard.service` — systemd unit file
- CLI entrypoint or standalone script

## Inputs
- Workfolders at `/mnt/ssd1/SpinalfMRIprep/work/wf_*`
- Pre-generated `dashboard/` HTML in each workfolder
- Existing `qc_dashboard_html.py` already emits JS that fetches `/__spinalfmriprep__/workfolders.json`

## Success Criteria
- `curl localhost:9002/` returns redirect to dashboard
- `curl localhost:9002/dashboard/index.html` returns the index page
- Workfolder dropdown works (JSON endpoint returns list)
- Reportlet PNGs load in browser
- Service survives reboot (systemd)

## Next Steps
1. Create `dashboard_server.py` with FastAPI
2. Create systemd unit file
3. Test locally, enable service

## Decision Log
| Q# | Choice | Rationale |
|----|--------|-----------|
| - | Fast path | All keys inferable from context |
