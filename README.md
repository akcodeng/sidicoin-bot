# Sidicoin Telegram Bot

Production-ready Telegram bot backend for Sidicoin -- Africa's leading cryptocurrency and instant money transfer platform built on TON blockchain.

**Domain:** `coin.sidihost.sbs`

## Architecture

- **Python 3.11** + **FastAPI** (webhook server)
- **aiogram 3** (Telegram bot framework)
- **Upstash Redis** REST API (all user data and balances)
- **Groq AI** llama-3.3-70b-versatile (conversational assistant)
- **Korapay API** (NGN payments: collections and disbursements)
- **TON SDK** (wallet creation via tonsdk)
- **AES-256-CBC** encryption for all private keys
- **APScheduler** for scheduled jobs

## Prerequisites

Before deploying, you need the following API keys and services:

### 1. Telegram Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow prompts
3. Copy the bot token

### 2. Groq API Key

1. Go to [console.groq.com](https://console.groq.com)
2. Create an account and generate an API key

### 3. Korapay API Keys

1. Register at [korapay.com](https://korapay.com)
2. Complete business verification
3. Get your Secret Key, Public Key, and Webhook Secret from the dashboard

### 4. Upstash Redis

1. Go to [upstash.com](https://upstash.com)
2. Create a Redis database
3. Copy the REST URL and REST Token

### 5. TON API Key (Optional)

1. Go to [toncenter.com](https://toncenter.com)
2. Get an API key for mainnet

### 6. Encryption Key

Generate a strong random key for AES-256 encryption:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Quick Start (DigitalOcean Ubuntu 22.04)

### Step 1: Create Droplet

- Create an Ubuntu 22.04 droplet on DigitalOcean (minimum 1GB RAM)
- Point your domain `coin.sidihost.sbs` to the droplet's IP via DNS A record
- SSH into the server

### Step 2: Clone and Configure

```bash
# Clone the repository
git clone <your-repo-url> /tmp/sidicoin
cd /tmp/sidicoin

# Create your .env file
cp .env.example .env
nano .env   # Fill in all your actual API keys
```

### Step 3: Run Automated Setup

```bash
chmod +x deploy/setup.sh
sudo bash deploy/setup.sh
```

This script will:
1. Update Ubuntu and install Python 3.11, nginx, certbot
2. Create `/var/www/sidicoin` and copy all files
3. Set up Python virtualenv and install dependencies
4. Install and enable the systemd service
5. Configure nginx reverse proxy
6. Obtain SSL certificate for `coin.sidihost.sbs`
7. Start the bot service
8. Set the Telegram webhook

### Step 4: Verify

```bash
# Check service is running
sudo systemctl status sidicoin

# Check webhook is set
curl https://coin.sidihost.sbs/health

# Watch live logs
sudo journalctl -u sidicoin -f
```

Then open Telegram and send `/start` to your bot.

## Manual Deployment

If you prefer to deploy manually instead of using `setup.sh`:

```bash
# Install dependencies
sudo apt install python3.11 python3.11-venv nginx certbot python3-certbot-nginx

# Setup application
sudo mkdir -p /var/www/sidicoin
sudo cp -r . /var/www/sidicoin/
cd /var/www/sidicoin
python3.11 -m venv venv
venv/bin/pip install -r requirements.txt

# Copy your .env
cp .env.example .env
nano .env

# Install service
sudo cp deploy/sidicoin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sidicoin
sudo systemctl start sidicoin

# Setup nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/sidicoin
sudo ln -s /etc/nginx/sites-available/sidicoin /etc/nginx/sites-enabled/
sudo certbot --nginx -d coin.sidihost.sbs
sudo systemctl reload nginx
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `KORAPAY_SECRET_KEY` | Korapay API secret key |
| `KORAPAY_PUBLIC_KEY` | Korapay API public key |
| `KORAPAY_WEBHOOK_SECRET` | Korapay webhook HMAC secret |
| `TON_API_KEY` | TON Center API key |
| `GROQ_API_KEY` | Groq API key for AI assistant |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis auth token |
| `SIDI_PRICE_NGN` | SIDI price in Naira (default: 25) |
| `SIDI_FEE_WALLET` | TON wallet address for collected fees |
| `ADMIN_TELEGRAM_ID` | Admin's Telegram user ID |
| `ENCRYPTION_KEY` | 64-char hex key for AES-256 encryption |
| `WEBHOOK_BASE_URL` | `https://coin.sidihost.sbs` |
| `PORT` | Server port (default: 8000) |

## Project Structure

```
main.py                    # FastAPI entry point, scheduler setup
bot/
  handler.py               # Handler registration
  commands.py              # All command and callback handlers
  keyboards.py             # Inline keyboard builders
  middleware.py             # Ban check and rate limit middleware
services/
  redis.py                 # Upstash Redis data layer
  ton.py                   # TON wallet creation
  korapay.py               # Korapay payments API
  groq.py                  # Groq AI conversational assistant
  notifications.py         # Scheduled notification jobs
routes/
  telegram.py              # POST /webhook/telegram
  korapay_webhook.py       # POST /webhook/korapay
  admin.py                 # GET /admin/* REST endpoints
utils/
  encryption.py            # AES-256-CBC encryption
  formatting.py            # Number, currency, date formatting
  validation.py            # Input validation and sanitization
deploy/
  nginx.conf               # Nginx reverse proxy config
  sidicoin.service          # Systemd service unit
  setup.sh                 # Automated deployment script
```

## Bot Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Create wallet, onboarding |
| `/balance` | Check SIDI balance |
| `/send` | Send SIDI to a user |
| `/buy` | Buy SIDI with Naira |
| `/sell` | Cash out SIDI to bank |
| `/history` | Transaction history |
| `/contacts` | Saved contacts |
| `/refer` | Referral link and earnings |
| `/checkin` | Daily reward |
| `/premium` | Upgrade to premium |
| `/leaderboard` | Top holders |
| `/price` | SIDI price and market data |
| `/stats` | Platform statistics |
| `/settings` | Account settings |
| `/help` | Command reference |
| `/about` | About Sidicoin |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/admin_stats` | Platform dashboard |
| `/admin_user @username` | View user profile |
| `/admin_credit @username amount` | Credit SIDI |
| `/admin_debit @username amount` | Debit SIDI |
| `/admin_ban @username` | Ban user |
| `/admin_unban @username` | Unban user |
| `/admin_broadcast message` | Broadcast to all |
| `/admin_fees` | Total fees collected |
| `/admin_pending` | Pending transactions |

## Monitoring

```bash
# Live logs
sudo journalctl -u sidicoin -f

# Service status
sudo systemctl status sidicoin

# Restart service
sudo systemctl restart sidicoin

# Check health endpoint
curl https://coin.sidihost.sbs/health

# Check admin stats (requires X-Admin-Id header)
curl -H "X-Admin-Id: YOUR_ADMIN_ID" https://coin.sidihost.sbs/admin/stats
```

## Troubleshooting

### Bot not responding

1. Check service is running: `sudo systemctl status sidicoin`
2. Check logs: `sudo journalctl -u sidicoin --since "10 min ago"`
3. Verify webhook: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
4. Ensure `.env` has correct `TELEGRAM_BOT_TOKEN`

### Webhook errors

1. Verify SSL: `curl -I https://coin.sidihost.sbs`
2. Check nginx: `sudo nginx -t && sudo systemctl status nginx`
3. Re-set webhook: `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://coin.sidihost.sbs/webhook/telegram"`

### Payment issues

1. Check Korapay dashboard for payment status
2. Verify `KORAPAY_WEBHOOK_SECRET` matches dashboard
3. Check logs for webhook signature errors
4. Ensure Korapay webhook URL is set to `https://coin.sidihost.sbs/webhook/korapay`

### Redis connection errors

1. Verify `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`
2. Check Upstash dashboard for connection status
3. Test: `curl -H "Authorization: Bearer <TOKEN>" <URL>/ping`

### SSL certificate renewal

Certbot auto-renewal is configured. To manually renew:

```bash
sudo certbot renew
sudo systemctl reload nginx
```

## Security

- All TON private keys are AES-256-CBC encrypted before Redis storage
- 24-hour cashout hold for new users
- Rate limiting: 10 transactions per hour per user
- Large transfer warnings (>10,000 SIDI)
- Suspicious activity alerts (>3 large transfers/hour)
- HMAC-SHA512 webhook signature verification
- Banned user middleware on every request
- Input sanitization on all user text
- No raw errors exposed to users
