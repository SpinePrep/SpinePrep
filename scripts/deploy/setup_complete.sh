#!/bin/bash
# Complete setup script for SpinePrep canonical dashboard server
# This script sets up both systemd service and Tailscale configuration
# Run with: sudo bash scripts/deploy/setup_complete.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=========================================="
echo "SpinePrep Dashboard Server - Complete Setup"
echo "=========================================="
echo ""

# Step 1: Install systemd service
echo "[1/4] Installing systemd service..."
mkdir -p /opt/spineprep
cp "$SCRIPT_DIR/spineprep_dashboard_server.py" /opt/spineprep/
chmod +x /opt/spineprep/spineprep_dashboard_server.py
cp "$SCRIPT_DIR/spineprep-dashboard.env" /etc/spineprep-dashboard.env
cp "$SCRIPT_DIR/spineprep-dashboard.service" /etc/systemd/system/spineprep-dashboard.service
systemctl daemon-reload
systemctl enable --now spineprep-dashboard.service

echo "[1/4] ✓ Service installed and started"
echo ""

# Step 2: Check service status
echo "[2/4] Checking service status..."
if systemctl is-active --quiet spineprep-dashboard.service; then
    echo "[2/4] ✓ Service is running"
else
    echo "[2/4] ✗ Service failed to start. Check logs:"
    echo "      sudo journalctl -u spineprep-dashboard.service -n 20"
    exit 1
fi
echo ""

# Step 3: Configure Tailscale hostname
echo "[3/4] Configuring Tailscale hostname..."
# Get current hostname from status (first line shows hostname or IP)
CURRENT_HOSTNAME=$(tailscale status --self 2>&1 | head -1 | awk '{print $2}' || echo "")
# Also check if hostname is already set via tailscale status output
TS_HOSTNAME=$(tailscale status 2>&1 | grep -E "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\s+spineprep-dash" | awk '{print $2}' || echo "")

if [[ "$TS_HOSTNAME" == "spineprep-dash" ]]; then
    echo "[3/4] ✓ Hostname already set to spineprep-dash"
elif [[ -n "$CURRENT_HOSTNAME" ]]; then
    echo "      Current hostname appears to be: ${CURRENT_HOSTNAME}"
    echo "      Attempting to set hostname to: spineprep-dash"
    echo "      (Note: If this fails, you may need to set hostname manually via Tailscale admin console)"
    # Try with --reset to avoid flag conflicts, but warn user
    if tailscale up --hostname=spineprep-dash --reset 2>&1; then
        echo "[3/4] ✓ Hostname configured (using --reset)"
    else
        echo "[3/4] ⚠ Hostname configuration skipped (may need manual setup)"
        echo "      You can set it manually: tailscale up --hostname=spineprep-dash --accept-dns=false --accept-routes --advertise-tags=tag:server --operator=kiomars --ssh"
    fi
else
    echo "[3/4] ⚠ Could not determine current hostname, skipping hostname change"
    echo "      You can set it manually if needed"
fi
echo ""

# Step 4: Configure Tailscale Serve
echo "[4/4] Configuring Tailscale Serve..."
# Check if port 17837 is already configured
if tailscale serve status 2>&1 | grep -q "17837"; then
    echo "      Port 17837 already configured, resetting..."
    tailscale serve reset
fi

tailscale serve --bg --http=17837 http://127.0.0.1:17837
echo "[4/4] ✓ Tailscale Serve configured"
echo ""

# Final verification
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Service status:"
systemctl status spineprep-dashboard.service --no-pager -l | head -10 || true
echo ""
echo "Tailscale Serve status:"
tailscale serve status | grep -A 2 "17837" || echo "  (check with: tailscale serve status)"
echo ""
echo "Access the dashboard at:"
echo "  http://spineprep-dash:17837/"
echo ""
echo "Status endpoint:"
echo "  http://spineprep-dash:17837/__spineprep__/status.json"
echo ""

