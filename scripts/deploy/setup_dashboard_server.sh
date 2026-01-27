#!/bin/bash
# Setup script for SpinalfMRIprep canonical dashboard server
# Run with: sudo bash scripts/deploy/setup_dashboard_server.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[setup] Creating /opt/spinalfmriprep directory..."
mkdir -p /opt/spinalfmriprep

echo "[setup] Installing dashboard server script..."
cp "$SCRIPT_DIR/spinalfmriprep_dashboard_server.py" /opt/spinalfmriprep/
chmod +x /opt/spinalfmriprep/spinalfmriprep_dashboard_server.py

echo "[setup] Installing environment config..."
cp "$SCRIPT_DIR/spinalfmriprep-dashboard.env" /etc/spinalfmriprep-dashboard.env

echo "[setup] Installing systemd service..."
cp "$SCRIPT_DIR/spinalfmriprep-dashboard.service" /etc/systemd/system/spinalfmriprep-dashboard.service

echo "[setup] Reloading systemd..."
systemctl daemon-reload

echo "[setup] Enabling and starting service..."
systemctl enable --now spinalfmriprep-dashboard.service

echo "[setup] Checking service status..."
systemctl status spinalfmriprep-dashboard.service --no-pager -l || true

echo ""
echo "[setup] Dashboard server installed and started."
echo "[setup] Next steps:"
echo "  1. Configure Tailscale hostname: sudo tailscale up --hostname=spinalfmriprep-dash"
echo "  2. Publish via Tailscale Serve: sudo tailscale serve --bg --http=17837 http://127.0.0.1:17837"
echo "  3. Access at: http://spinalfmriprep-dash:17837/"




