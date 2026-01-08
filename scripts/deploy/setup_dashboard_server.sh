#!/bin/bash
# Setup script for SpinePrep canonical dashboard server
# Run with: sudo bash scripts/deploy/setup_dashboard_server.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[setup] Creating /opt/spineprep directory..."
mkdir -p /opt/spineprep

echo "[setup] Installing dashboard server script..."
cp "$SCRIPT_DIR/spineprep_dashboard_server.py" /opt/spineprep/
chmod +x /opt/spineprep/spineprep_dashboard_server.py

echo "[setup] Installing environment config..."
cp "$SCRIPT_DIR/spineprep-dashboard.env" /etc/spineprep-dashboard.env

echo "[setup] Installing systemd service..."
cp "$SCRIPT_DIR/spineprep-dashboard.service" /etc/systemd/system/spineprep-dashboard.service

echo "[setup] Reloading systemd..."
systemctl daemon-reload

echo "[setup] Enabling and starting service..."
systemctl enable --now spineprep-dashboard.service

echo "[setup] Checking service status..."
systemctl status spineprep-dashboard.service --no-pager -l || true

echo ""
echo "[setup] Dashboard server installed and started."
echo "[setup] Next steps:"
echo "  1. Configure Tailscale hostname: sudo tailscale up --hostname=spineprep-dash"
echo "  2. Publish via Tailscale Serve: sudo tailscale serve --bg --http=17837 http://127.0.0.1:17837"
echo "  3. Access at: http://spineprep-dash:17837/"




