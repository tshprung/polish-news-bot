#!/bin/bash
set -e

REPO_URL="$1"  # pass your GitHub repo SSH URL as argument
INSTALL_DIR="/opt/polish_news"

echo "=== Installing dependencies ==="
sudo apt-get update -q
sudo apt-get install -y python3 python3-venv python3-pip git

echo "=== Cloning repo ==="
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER":"$USER" "$INSTALL_DIR"
git clone "$REPO_URL" "$INSTALL_DIR"

echo "=== Creating virtualenv ==="
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "=== Creating .env ==="
cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
echo ""
echo ">>> Edit $INSTALL_DIR/.env and fill in your secrets, then run:"
echo "    chmod +x $INSTALL_DIR/run.sh"
echo "    crontab -e"
echo "    Add this line (hourly; use CRON_TZ=Europe/Warsaw if needed):"
echo "    0 * * * * $INSTALL_DIR/run.sh"
