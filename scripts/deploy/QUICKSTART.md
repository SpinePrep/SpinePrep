# Quick Start: SpinePrep Dashboard Server

## One-Command Setup

Run this command to set up everything (systemd service + Tailscale):

```bash
sudo bash scripts/deploy/setup_complete.sh
```

This will:
1. ✅ Install the dashboard server to `/opt/spineprep/`
2. ✅ Configure and start the systemd service
3. ✅ Set Tailscale hostname to `spineprep-dash`
4. ✅ Publish the service via Tailscale Serve on port 17837

## Verify It Works

After running the setup script:

### Local verification
```bash
# Check service is running
sudo systemctl status spineprep-dashboard.service

# Check status endpoint
curl -s http://127.0.0.1:17837/__spineprep__/status.json | jq

# Test root redirect
curl -I http://127.0.0.1:17837/
```

### Tailnet verification
From another machine on your tailnet, open:
- **http://spineprep-dash:17837/**

You should see the latest workflow dashboard automatically.

## What Gets Served

The server automatically finds the **most recent** workflow run by scanning:
- `/mnt/ssd1/SpinePrep/work/**/wf_*/dashboard/index.html`
- Canonical patterns: `wf_smoke_*`, `wf_reg_*`, `wf_full_*`
- Picks the one with the newest modification time across all types
- Serves the entire `<out>` directory (so dashboard images load correctly)

## Troubleshooting

If something doesn't work:

```bash
# Check service logs
sudo journalctl -u spineprep-dashboard.service -f

# Check Tailscale Serve status
sudo tailscale serve status

# Restart service
sudo systemctl restart spineprep-dashboard.service
```

See `README.md` for more details.



