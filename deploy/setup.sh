#!/bin/bash
# Ouroboros Backend — VPS Setup Script
# Run on fresh Ubuntu 22.04+ VPS as root

set -e

echo "=== Installing system dependencies ==="
apt update && apt install -y python3.12 python3.12-venv nginx certbot python3-certbot-nginx git

echo "=== Creating ouroboros user ==="
id -u ouroboros &>/dev/null || useradd -m -s /bin/bash ouroboros

echo "=== Setting up application ==="
mkdir -p /opt/ouroboros-backend
cd /opt/ouroboros-backend

echo "=== Creating virtual environment ==="
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing systemd service ==="
cp deploy/ouroboros.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ouroboros

echo "=== Installing nginx config ==="
cp deploy/nginx.conf /etc/nginx/sites-available/ouroboros
ln -sf /etc/nginx/sites-available/ouroboros /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "1. Copy your .env file to /opt/ouroboros-backend/.env"
echo "2. Update server_name in /etc/nginx/sites-available/ouroboros"
echo "3. Run: certbot --nginx -d ouroboros-api.YOUR_DOMAIN.com"
echo "4. Run: systemctl start ouroboros"
echo "5. Run: systemctl restart nginx"
