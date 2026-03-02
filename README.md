# Sidicoin Telegram Bot

Production-ready Telegram bot for Sidicoin -- instant digital money transfers with zero fees, escrow protection, and merchant payments. Works in 13+ countries.

**Domain:** `coin.sidihost.sbs`

## Architecture

- **Python 3.11** + **FastAPI** (webhook server)
- **aiogram 3** (Telegram bot framework)
- **Upstash Redis** REST API (all user data and balances)
- **Groq AI** llama-3.3-70b-versatile (conversational assistant)
- **Korapay API** (NGN bank transfers: collections and disbursements)
- **Paystack API** (international payments: cards, mobile money, bank transfers)
- **TON SDK** (wallet creation via tonsdk)
- **AES-256-CBC** encryption for all private keys
- **Telegram OTP** (6-digit verification codes for sensitive actions)
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

### 4. Paystack API Keys (International Payments)

Paystack handles card payments (Visa/Mastercard), bank transfers, mobile money (Ghana, Kenya), and payouts. Owned by Stripe -- very reliable and easy to get live mode approved.

1. Go to [dashboard.paystack.com](https://dashboard.paystack.com)
2. Create an account and complete business verification
3. Go to **Settings** > **API Keys & Webhooks**
4. Copy your **Secret Key** (starts with `sk_live_`) and **Public Key** (starts with `pk_live_`)

**Webhook setup (required):**

5. In the same Settings page, find **Webhook URL**
6. Set it to: `https://coin.sidihost.sbs/webhook/paystack`
7. Save

Paystack verifies webhooks using HMAC-SHA512 -- it signs every webhook request with your Secret Key. Your server computes the same signature and compares. No separate webhook secret needed -- it uses your existing Secret Key.

**Supported countries:** Nigeria (cards, bank transfer, USSD), Ghana (cards, mobile money), Kenya (cards, mobile money), South Africa (cards)

**Test vs Live mode:**
- Test keys start with `sk_test_` / `pk_test_`
- Live keys start with `sk_live_` / `pk_live_`
- To go live: complete business verification on Paystack dashboard, then switch to live keys

### 5. Upstash Redis

1. Go to [upstash.com](https://upstash.com)
2. Create a Redis database
3. Copy the REST URL and REST Token

### 6. TON API Key (Optional)

1. Go to [toncenter.com](https://toncenter.com)
2. Get an API key for mainnet

### 7. Encryption Key

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

| Variable | Required | Description | Where to get it |
|----------|----------|-------------|-----------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token | [@BotFather](https://t.me/BotFather) > `/newbot` |
| `ADMIN_TELEGRAM_ID` | Yes | Your Telegram user ID | [@userinfobot](https://t.me/userinfobot) |
| `KORAPAY_SECRET_KEY` | Yes | Korapay API secret key | [korapay.com](https://korapay.com) > Dashboard > API Keys |
| `KORAPAY_PUBLIC_KEY` | Yes | Korapay API public key | Same as above |
| `KORAPAY_WEBHOOK_SECRET` | Yes | Korapay webhook HMAC secret | Korapay Dashboard > Webhooks |
| `PAYSTACK_SECRET_KEY` | Yes | Paystack secret key (starts with `sk_live_`) | [dashboard.paystack.com](https://dashboard.paystack.com) > Settings > API Keys |
| `PAYSTACK_PUBLIC_KEY` | Yes | Paystack public key (starts with `pk_live_`) | Same as above |
| `TON_API_KEY` | Optional | TON Center API key | [toncenter.com](https://toncenter.com) |
| `GROQ_API_KEY` | Yes | Groq AI API key | [console.groq.com](https://console.groq.com) |
| `UPSTASH_REDIS_REST_URL` | Yes | Redis REST endpoint | [upstash.com](https://upstash.com) > Database > REST API |
| `UPSTASH_REDIS_REST_TOKEN` | Yes | Redis auth token | Same as above |
| `SIDI_PRICE_NGN` | No | SIDI price in Naira (default: 25) | Set manually |
| `ENCRYPTION_KEY` | Yes | 64-char hex key for AES-256 | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `WEBHOOK_BASE_URL` | Yes | Your domain URL | `https://coin.sidihost.sbs` |
| `PORT` | No | Server port (default: 8000) | Set manually |

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
  korapay.py               # Korapay payments API (NGN)
  paystack.py              # Paystack payments API (international)
  otp.py                   # Telegram OTP verification system
  groq.py                  # Groq AI conversational assistant
  notifications.py         # Scheduled notification jobs
routes/
  telegram.py              # POST /webhook/telegram
  korapay_webhook.py       # POST /webhook/korapay
  paystack_webhook.py      # POST /webhook/paystack
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
| `/send` | Send SIDI to a user (zero fees) |
| `/buy` | Buy SIDI with Naira or international payments (zero fees) |
| `/sell` | Cash out SIDI to bank (zero fees, OTP verified) |
| `/escrow` | Create/manage escrow trades for safe P2P |
| `/history` | Transaction history |
| `/contacts` | Saved contacts |
| `/refer` | Referral link and earnings |
| `/checkin` | Monthly check-in reward (10/month, progressive) |
| `/merchant` | Business tools -- accept payments with 2% merchant fee |
| `/support` | Donate SIDI to keep the platform free |
| `/premium` | Upgrade to premium |
| `/leaderboard` | Top holders |
| `/price` | SIDI price and market data |
| `/stats` | Platform statistics |
| `/settings` | Account settings (OTP verified for bank changes) |
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
| `/admin_merchant_approve <user_id>` | Approve merchant application |

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

### Payment issues (Korapay -- NGN)

1. Check Korapay dashboard for payment status
2. Verify `KORAPAY_WEBHOOK_SECRET` matches dashboard
3. Check logs for webhook signature errors
4. Ensure Korapay webhook URL is set to `https://coin.sidihost.sbs/webhook/korapay`

### Payment issues (Paystack -- International)

1. Check Paystack dashboard for payment status
2. Verify `PAYSTACK_SECRET_KEY` is your live key (starts with `sk_live_`), not test key
3. Ensure Paystack webhook URL is set to `https://coin.sidihost.sbs/webhook/paystack`
4. Check logs for `invalid signature` errors -- means the secret key doesn't match
5. For mobile money (Ghana, Kenya), payments may take 30-60 seconds to confirm
6. If stuck on test mode, complete business verification on Paystack dashboard to go live

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

- **Telegram OTP** -- 6-digit codes sent via Telegram DM for cashouts, escrow funding, large sends (>5,000 SIDI), and bank detail changes. 5-min expiry, 3 attempts max, 60s cooldown between codes.
- **Auto-flag** -- Accounts with 5+ cumulative OTP failures are auto-locked and admin is notified
- **Session timeout** -- Users must re-verify after 30 minutes of inactivity on financial actions
- All TON private keys are AES-256-CBC encrypted before Redis storage
- 24-hour cashout hold for new users
- Rate limiting: 10 transactions per hour per user
- Large transfer warnings (>10,000 SIDI)
- Suspicious activity alerts (>3 large transfers/hour)
- HMAC-SHA512 webhook verification (Korapay)
- HMAC-SHA512 webhook verification (Paystack)
- Banned user middleware on every request
- Input sanitization on all user text
- No raw errors exposed to users

## Revenue Model

Sidicoin is zero-fee for users. Revenue comes from:

- **Merchant fees (2%)** -- Businesses apply for merchant status, generate payment links (`t.me/SidicoinBot?start=pay_ID_AMOUNT_REF`), and pay 2% on each transaction received. Customers pay nothing.
- **Voluntary donations** -- Users can `/support` to donate SIDI
- **Premium subscriptions** -- Higher limits and badge
