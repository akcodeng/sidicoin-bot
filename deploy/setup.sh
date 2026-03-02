#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# SidiApp Bot — Automated Deployment Script
# Target: Ubuntu 22.04 (DigitalOcean)
# Domain: coin.sidihost.sbs
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

DOMAIN="coin.sidihost.sbs"
APP_DIR="/var/www/sidiapp"
SERVICE_NAME="sidiapp"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "═══════════════════════════════════════════════════"
echo "  SidiApp Bot — Deployment Script"
echo "  Domain: $DOMAIN"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: System updates ─────────────────────────────────────
echo "[1/9] Updating system packages..."
apt update -y && apt upgrade -y

# ── Step 2: Install dependencies ───────────────────────────────
echo "[2/9] Installing Python 3.11, nginx, certbot..."
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update -y
apt install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    nginx \
    certbot \
    python3-certbot-nginx \
    curl \
    git \
    ufw

# ── Step 3: Create application directory ───────────────────────
echo "[3/9] Setting up application directory..."
mkdir -p "$APP_DIR"

# Copy all project files
cp -r "$REPO_DIR"/*.py "$APP_DIR/" 2>/dev/null || true
cp -r "$REPO_DIR"/bot "$APP_DIR/"
cp -r "$REPO_DIR"/services "$APP_DIR/"
cp -r "$REPO_DIR"/routes "$APP_DIR/"
cp -r "$REPO_DIR"/utils "$APP_DIR/"
cp "$REPO_DIR"/requirements.txt "$APP_DIR/"

# Check for .env file
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$REPO_DIR/.env" ]; then
        cp "$REPO_DIR/.env" "$APP_DIR/.env"
        echo "  Copied .env from repo directory"
    else
        cp "$REPO_DIR/.env.example" "$APP_DIR/.env"
        echo ""
        echo "  WARNING: No .env file found. Copied .env.example to $APP_DIR/.env"
        echo "  Please edit $APP_DIR/.env with your actual credentials before starting."
        echo ""
    fi
fi

chown -R www-data:www-data "$APP_DIR"

# ── Step 4: Python virtual environment ─────────────────────────
echo "[4/9] Creating Python virtual environment and installing packages..."
python3.11 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── Step 5: Configure systemd service ──────────────────────────
echo "[5/9] Installing systemd service..."
cp "$REPO_DIR/deploy/sidiapp.service" /etc/systemd/system/sidiapp.service
systemctl daemon-reload
systemctl enable sidiapp

# ── Step 6: Configure nginx ────────────────────────────────────
echo "[6/9] Configuring nginx..."

# Remove default site if exists
rm -f /etc/nginx/sites-enabled/default

# Write initial HTTP-only config for certbot
cat > /etc/nginx/sites-available/sidiapp << 'NGINX_TEMP'
server {
    listen 80;
    server_name coin.sidihost.sbs;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 200 'SidiApp Bot - Setting up SSL...';
        add_header Content-Type text/plain;
    }
}
NGINX_TEMP

ln -sf /etc/nginx/sites-available/sidiapp /etc/nginx/sites-enabled/sidiapp
mkdir -p /var/www/certbot

nginx -t && systemctl restart nginx

# ── Step 7: SSL Certificate ────────────────────────────────────
echo "[7/9] Obtaining SSL certificate for $DOMAIN..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@sidihost.sbs --redirect

# Now install the full nginx config
cp "$REPO_DIR/deploy/nginx.conf" /etc/nginx/sites-available/sidiapp
nginx -t && systemctl reload nginx

echo "  SSL certificate installed successfully"

# ── Step 8: Configure firewall ─────────────────────────────────
echo "[8/9] Configuring firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ── Step 9: Start the service ──────────────────────────────────
echo "[9/9] Starting SidiApp bot service..."

# Check if .env has actual values (not just the example)
if grep -q "^TELEGRAM_BOT_TOKEN=$" "$APP_DIR/.env"; then
    echo ""
    echo "  WARNING: TELEGRAM_BOT_TOKEN is empty in .env"
    echo "  Please edit $APP_DIR/.env with your credentials, then run:"
    echo "    sudo systemctl start sidiapp"
    echo ""
else
    systemctl start sidiapp
    sleep 3

    # Set Telegram webhook
    echo "  Setting Telegram webhook..."
    source "$APP_DIR/.env"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
        WEBHOOK_URL="https://$DOMAIN/webhook/telegram"
        RESPONSE=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${WEBHOOK_URL}&drop_pending_updates=true")
        echo "  Webhook response: $RESPONSE"
    else
        echo "  TELEGRAM_BOT_TOKEN not found. Set webhook manually."
    fi

    echo ""
    echo "  Service started. Check status with:"
    echo "    sudo systemctl status sidiapp"
    echo "    sudo journalctl -u sidiapp -f"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  SidiApp Bot Deployment Complete!"
echo ""
echo "  Domain:    https://$DOMAIN"
echo "  Webhook:   https://$DOMAIN/webhook/telegram"
echo "  Korapay:   https://$DOMAIN/webhook/korapay"
echo "  Health:    https://$DOMAIN/health"
echo "  Logs:      sudo journalctl -u sidiapp -f"
echo "  Config:    $APP_DIR/.env"
echo "═══════════════════════════════════════════════════"
