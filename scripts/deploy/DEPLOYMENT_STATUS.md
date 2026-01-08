# SpinePrep Dashboard Server - Deployment Status

## ✅ Deployment Complete

The canonical dashboard server is **fully operational**.

### Service Status
- **Service**: `spineprep-dashboard.service` - **ACTIVE (running)**
- **Port**: `17837` (reserved for SpinePrep)
- **Work Root**: `/mnt/ssd1/SpinePrep/work`
- **Latest Dashboard**: Automatically serves most recent `wf_*/dashboard/index.html` (includes `wf_smoke_*`, `wf_reg_*`, `wf_full_*`)

### Access URLs

**On Tailnet:**
- `http://balgrist:17837/` (short hostname)
- `http://balgrist.tail184bba.ts.net:17837/` (full FQDN)

**Localhost:**
- `http://127.0.0.1:17837/`

### Current Status

The server is currently serving:
- **Latest workflow**: `wf_004` (legacy naming)
- **Dashboard path**: `/mnt/ssd1/SpinePrep/work/wf_004/dashboard/index.html`
- **Note**: New runs use canonical naming (`wf_smoke_*`, `wf_reg_*`, `wf_full_*`)

### Health Check

Status endpoint: `http://balgrist:17837/__spineprep__/status.json`

```json
{
    "work_root": "/mnt/ssd1/SpinePrep/work",
    "latest_out": "/mnt/ssd1/SpinePrep/work/wf_004",
    "latest_dashboard_index": "/mnt/ssd1/SpinePrep/work/wf_004/dashboard/index.html",
    "checked_at_unix": 1767364981.3797576
}
```

### Hostname Note

The Tailscale hostname is currently `balgrist` (not `spineprep-dash`). This is fine - the service works perfectly with the current hostname. If you want to change it to `spineprep-dash`:

1. Use Tailscale admin console to rename the device, OR
2. Run: `tailscale up --hostname=spineprep-dash --accept-dns=false --accept-routes --advertise-tags=tag:server --operator=kiomars --ssh`

The service will then be accessible at `http://spineprep-dash:17837/`.

### Service Management

```bash
# Check status
sudo systemctl status spineprep-dashboard.service

# View logs
sudo journalctl -u spineprep-dashboard.service -f

# Restart service
sudo systemctl restart spineprep-dashboard.service

# Stop service
sudo systemctl stop spineprep-dashboard.service
```

### Tailscale Serve Management

```bash
# Check status
sudo tailscale serve status

# Restart serve (if needed)
sudo tailscale serve reset
sudo tailscale serve --bg --http=17837 http://127.0.0.1:17837
```

---

**Deployment Date**: 2026-01-02  
**Status**: ✅ Operational



