# SpinalfMRIprep Dashboard Server Deployment

This directory contains files to deploy the canonical SpinalfMRIprep dashboard server.

## Quick Setup

Run the setup script with sudo:

```bash
sudo bash scripts/deploy/setup_dashboard_server.sh
```

This will:
1. Install the server script to `/opt/spinalfmriprep/spinalfmriprep_dashboard_server.py`
2. Install environment config to `/etc/spinalfmriprep-dashboard.env`
3. Install systemd service to `/etc/systemd/system/spinalfmriprep-dashboard.service`
4. Enable and start the service

## Manual Setup (if script fails)

If you prefer to set up manually:

```bash
# 1. Create directory
sudo mkdir -p /opt/spinalfmriprep

# 2. Install server script
sudo cp scripts/deploy/spinalfmriprep_dashboard_server.py /opt/spinalfmriprep/
sudo chmod +x /opt/spinalfmriprep/spinalfmriprep_dashboard_server.py

# 3. Install environment config
sudo cp scripts/deploy/spinalfmriprep-dashboard.env /etc/spinalfmriprep-dashboard.env

# 4. Install systemd service
sudo cp scripts/deploy/spinalfmriprep-dashboard.service /etc/systemd/system/spinalfmriprep-dashboard.service

# 5. Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable --now spinalfmriprep-dashboard.service

# 6. Check status
sudo systemctl status spinalfmriprep-dashboard.service
```

## Tailscale Configuration

After the service is running, configure Tailscale:

```bash
# 1. Set hostname (if not already set)
sudo tailscale up --hostname=spinalfmriprep-dash

# 2. Publish the service via Tailscale Serve
sudo tailscale serve --bg --http=17837 http://127.0.0.1:17837
```

## Verification

### Local verification

```bash
# Check service status
sudo systemctl status spinalfmriprep-dashboard.service

# Check status endpoint
curl -s http://127.0.0.1:17837/__spinalfmriprep__/status.json | jq

# Check root redirect
curl -I http://127.0.0.1:17837/
```

### Tailnet verification

From another machine on your tailnet, open:
- `http://spinalfmriprep-dash:17837/`

You should see the latest workflow dashboard.

## Configuration

Edit `/etc/spinalfmriprep-dashboard.env` to change:
- `SPINALFMRIPREP_WORK_ROOT`: Work root to scan for workflow runs (default: `/mnt/ssd1/SpinalfMRIprep/work`)
- `SPINALFMRIPREP_DASH_HOST`: Bind address (default: `127.0.0.1`)
- `SPINALFMRIPREP_DASH_PORT`: Port (default: `17837`)
- `SPINALFMRIPREP_DASH_REFRESH_SECONDS`: Cache refresh interval (default: `5`)

After changing the config, restart the service:
```bash
sudo systemctl restart spinalfmriprep-dashboard.service
```

## Troubleshooting

### Service not starting
```bash
sudo journalctl -u spinalfmriprep-dashboard.service -f
```

### No dashboard found
- Ensure you've run `spinalfmriprep qc --out <out>` to generate a dashboard
- Check that `<out>/dashboard/index.html` exists
- Verify `SPINALFMRIPREP_WORK_ROOT` points to the correct directory
- Dashboard server scans for `wf_smoke_*`, `wf_reg_*`, `wf_full_*` patterns (canonical naming)

### Tailscale Serve not working
```bash
# Check current serve status
sudo tailscale serve status

# Remove and re-add if needed
sudo tailscale serve reset
sudo tailscale serve --bg --http=17837 http://127.0.0.1:17837
```



