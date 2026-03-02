"""
Paystack payment service for international collections and payouts.
Supports cards (Visa/Mastercard), bank transfers, mobile money,
and payouts across Nigeria, Ghana, Kenya, South Africa.

Korapay is kept for NGN bank transfer collections.
Paystack handles cards, mobile money, and international payments.

API docs: https://paystack.com/docs/api
"""

import os
import hmac
import hashlib
import logging
import time

import httpx

logger = logging.getLogger("sidicoin.paystack")

PSK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PSK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PSK_BASE_URL = "https://api.paystack.co"

# Supported countries with their currency and payment methods
COUNTRY_CONFIG = {
    "NG": {
        "currency": "NGN",
        "name": "Nigeria",
        "flag": "\U0001f1f3\U0001f1ec",
        "methods": ["bank_transfer", "card", "ussd"],
        "payout_type": "bank",
        "min_payout": 100,  # NGN
    },
    "GH": {
        "currency": "GHS",
        "name": "Ghana",
        "flag": "\U0001f1ec\U0001f1ed",
        "methods": ["mobile_money", "card"],
        "payout_type": "mobile_money",
        "min_payout": 1,
    },
    "KE": {
        "currency": "KES",
        "name": "Kenya",
        "flag": "\U0001f1f0\U0001f1ea",
        "methods": ["mobile_money", "card"],
        "payout_type": "mobile_money",
        "min_payout": 10,
    },
    "ZA": {
        "currency": "ZAR",
        "name": "South Africa",
        "flag": "\U0001f1ff\U0001f1e6",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 10,
    },
    "TZ": {
        "currency": "TZS",
        "name": "Tanzania",
        "flag": "\U0001f1f9\U0001f1ff",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 100,
    },
    "UG": {
        "currency": "UGX",
        "name": "Uganda",
        "flag": "\U0001f1fa\U0001f1ec",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 500,
    },
    "RW": {
        "currency": "RWF",
        "name": "Rwanda",
        "flag": "\U0001f1f7\U0001f1fc",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 100,
    },
    "CI": {
        "currency": "XOF",
        "name": "Ivory Coast",
        "flag": "\U0001f1e8\U0001f1ee",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 100,
    },
    "SN": {
        "currency": "XOF",
        "name": "Senegal",
        "flag": "\U0001f1f8\U0001f1f3",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 100,
    },
    # International (card-only)
    "US": {
        "currency": "USD",
        "name": "United States",
        "flag": "\U0001f1fa\U0001f1f8",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 1,
    },
    "GB": {
        "currency": "GBP",
        "name": "United Kingdom",
        "flag": "\U0001f1ec\U0001f1e7",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 1,
    },
    "EU": {
        "currency": "EUR",
        "name": "Europe",
        "flag": "\U0001f1ea\U0001f1fa",
        "methods": ["card"],
        "payout_type": "bank",
        "min_payout": 1,
    },
}

# Default for unknown countries
DEFAULT_COUNTRY = {
    "currency": "USD",
    "name": "International",
    "flag": "\U0001f30d",
    "methods": ["card"],
    "payout_type": "bank",
    "min_payout": 1,
}

# Approximate exchange rates to NGN (updated periodically)
RATES_TO_NGN = {
    "NGN": 1.0,
    "USD": 1600.0,
    "GBP": 2000.0,
    "EUR": 1750.0,
    "GHS": 100.0,
    "KES": 10.0,
    "ZAR": 85.0,
    "TZS": 0.6,
    "UGX": 0.42,
    "RWF": 1.2,
    "XAF": 2.65,
    "XOF": 2.65,
}


def _headers() -> dict:
    secret = os.getenv("PAYSTACK_SECRET_KEY", PSK_SECRET_KEY)
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


async def _request(
    method: str, endpoint: str, data: dict = None, retries: int = 3
) -> dict:
    """Make an HTTP request to Paystack API with retry + backoff."""
    url = f"{PSK_BASE_URL}{endpoint}"
    headers = _headers()
    last_error = None

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers, params=data)
                elif method.upper() == "POST":
                    resp = await client.post(url, headers=headers, json=data)
                else:
                    return {"status": False, "message": f"Unsupported method: {method}"}

                body = resp.json()
                logger.info(
                    f"Paystack {method} {endpoint} -> {resp.status_code}: "
                    f"{body.get('message', '')}"
                )

                if resp.status_code in (200, 201):
                    return body

                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return {
                        "status": False,
                        "message": body.get("message", f"HTTP {resp.status_code}"),
                        "data": body.get("data"),
                    }

                last_error = body.get("message", f"HTTP {resp.status_code}")

        except httpx.TimeoutException:
            last_error = "Request timed out"
            logger.warning(f"Paystack timeout (attempt {attempt + 1}/{retries})")
        except Exception as e:
            last_error = str(e)
            logger.error(f"Paystack error (attempt {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            import asyncio
            await asyncio.sleep(1.5 ** attempt)

    return {"status": False, "message": last_error or "Max retries exceeded"}


def get_country_config(country_code: str) -> dict:
    """Get config for a country code (2-letter ISO)."""
    return COUNTRY_CONFIG.get(country_code.upper(), DEFAULT_COUNTRY)


def convert_to_ngn(amount: float, currency: str) -> float:
    """Convert an amount in local currency to NGN equivalent."""
    rate = RATES_TO_NGN.get(currency.upper(), 1600.0)
    return round(amount * rate, 2)


def convert_from_ngn(ngn_amount: float, currency: str) -> float:
    """Convert NGN to local currency."""
    rate = RATES_TO_NGN.get(currency.upper(), 1600.0)
    if rate <= 0:
        return 0.0
    return round(ngn_amount / rate, 2)


def detect_country_from_language(language_code: str) -> str:
    """
    Best-effort detection of user's country from Telegram language_code.
    Returns 2-letter ISO country code.
    """
    lang_map = {
        "en": "NG",  # Default English to Nigeria (primary market)
        "fr": "CI",  # French -> Ivory Coast
        "sw": "KE",  # Swahili -> Kenya
        "ha": "NG",  # Hausa -> Nigeria
        "yo": "NG",  # Yoruba -> Nigeria
        "ig": "NG",  # Igbo -> Nigeria
        "zu": "ZA",  # Zulu -> South Africa
        "af": "ZA",  # Afrikaans -> South Africa
        "am": "NG",  # Amharic -> default NG
        "pt": "NG",  # Portuguese -> default NG
        "ar": "NG",  # Arabic -> default NG
        "de": "EU",  # German -> Europe
        "es": "EU",  # Spanish -> Europe
        "it": "EU",  # Italian -> Europe
        "nl": "EU",  # Dutch -> Europe
        "rw": "RW",  # Kinyarwanda -> Rwanda
    }
    if not language_code:
        return "NG"
    code = language_code.lower().strip()
    if code in lang_map:
        return lang_map[code]
    prefix = code.split("-")[0] if "-" in code else code[:2]
    return lang_map.get(prefix, "NG")


# =====================================================================
#  COLLECTIONS -- Receive money (Fund SIDI wallet)
# =====================================================================

async def create_payment_link(
    reference: str,
    amount: float,
    currency: str,
    customer_name: str,
    customer_email: str = "user@sidicoin.app",
    payment_type: str = "card",
    redirect_url: str = "https://coin.sidihost.sbs/payment/complete",
    narration: str = "Sidicoin Purchase",
    meta: dict = None,
) -> dict:
    """
    Initialize a Paystack transaction and return the checkout URL.
    Paystack amounts are in kobo (NGN * 100) / pesewas (GHS * 100).

    Returns: {success, link, reference}
    """
    # Paystack expects amount in smallest currency unit (kobo/pesewas)
    amount_minor = int(round(float(amount) * 100))

    channels = []
    if "card" in payment_type:
        channels.append("card")
    if "bank" in payment_type or "bank_transfer" in payment_type:
        channels.append("bank_transfer")
        channels.append("bank")
    if "mobile" in payment_type:
        channels.append("mobile_money")
    if "ussd" in payment_type:
        channels.append("ussd")
    if not channels:
        channels = ["card", "bank", "bank_transfer", "ussd", "mobile_money"]

    payload = {
        "reference": reference,
        "amount": amount_minor,
        "currency": currency.upper(),
        "email": customer_email,
        "callback_url": redirect_url,
        "channels": channels,
        "metadata": {
            "customer_name": customer_name or "Sidicoin User",
            "custom_fields": [
                {"display_name": "Platform", "variable_name": "platform", "value": "Sidicoin"},
            ],
            **(meta or {}),
        },
    }

    result = await _request("POST", "/transaction/initialize", payload)

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "link": data.get("authorization_url", ""),
            "access_code": data.get("access_code", ""),
            "reference": data.get("reference", reference),
        }

    return {
        "success": False,
        "message": result.get("message", "Could not initialize payment"),
    }


async def verify_transaction(reference: str) -> dict:
    """Verify a Paystack transaction by reference."""
    result = await _request("GET", f"/transaction/verify/{reference}")

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        # Paystack returns amount in kobo, convert back
        amount = float(data.get("amount", 0)) / 100.0
        return {
            "success": True,
            "status": data.get("status", ""),
            "amount": amount,
            "currency": data.get("currency", ""),
            "reference": data.get("reference", ""),
            "gateway_response": data.get("gateway_response", ""),
            "channel": data.get("channel", ""),
        }

    return {"success": False, "message": result.get("message", "Verification failed")}


# =====================================================================
#  PAYOUTS -- Send money (Withdraw from SIDI wallet)
# =====================================================================

async def create_transfer_recipient(
    name: str,
    account_number: str,
    bank_code: str,
    currency: str = "NGN",
    recipient_type: str = "nuban",
) -> dict:
    """
    Create a transfer recipient (required before transfers).
    For mobile money, use type='mobile_money' and pass phone as account_number.
    """
    payload = {
        "type": recipient_type,
        "name": name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": currency.upper(),
    }

    result = await _request("POST", "/transferrecipient", payload)

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "recipient_code": data.get("recipient_code", ""),
            "name": data.get("name", name),
        }

    return {
        "success": False,
        "message": result.get("message", "Could not create recipient"),
    }


async def create_transfer(
    reference: str,
    amount: float,
    currency: str,
    recipient_code: str,
    reason: str = "Sidicoin Withdrawal",
) -> dict:
    """
    Initiate a transfer to a recipient.
    Amount is in the major currency unit (NGN, not kobo).
    """
    amount_minor = int(round(float(amount) * 100))

    payload = {
        "source": "balance",
        "amount": amount_minor,
        "reference": reference,
        "recipient": recipient_code,
        "reason": reason,
        "currency": currency.upper(),
    }

    result = await _request("POST", "/transfer", payload)

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "transfer_code": data.get("transfer_code", ""),
            "reference": reference,
            "status": data.get("status", "pending"),
            "amount": float(data.get("amount", amount * 100)) / 100.0,
            "currency": data.get("currency", currency),
        }

    return {
        "success": False,
        "message": result.get("message", "Transfer failed"),
    }


# =====================================================================
#  BANK LIST
# =====================================================================

async def get_banks(country: str = "nigeria") -> list[dict]:
    """Get list of banks for a country."""
    result = await _request("GET", f"/bank", {"country": country.lower()})

    if result.get("status") is True and result.get("data"):
        return [
            {"name": b.get("name", ""), "code": b.get("code", "")}
            for b in result["data"]
        ]
    return []


async def resolve_account(account_number: str, bank_code: str) -> dict:
    """Verify/resolve a bank account number."""
    result = await _request(
        "GET", "/bank/resolve",
        {"account_number": account_number, "bank_code": bank_code},
    )

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "account_name": data.get("account_name", ""),
            "account_number": data.get("account_number", account_number),
        }

    return {
        "success": False,
        "message": result.get("message", "Could not resolve account"),
    }


# =====================================================================
#  WEBHOOK VERIFICATION
# =====================================================================

def verify_webhook(raw_body: bytes, signature: str) -> bool:
    """
    Verify Paystack webhook using HMAC SHA-512.
    Paystack sends x-paystack-signature header.
    """
    secret = os.getenv("PAYSTACK_SECRET_KEY", PSK_SECRET_KEY)
    if not secret or not signature:
        logger.warning("Paystack webhook: missing secret or signature")
        return False

    computed = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


# =====================================================================
#  EXCHANGE RATE
# =====================================================================

def get_exchange_rate(from_currency: str, to_currency: str, amount: float = 1.0) -> dict:
    """
    Convert between currencies using static rates.
    Paystack doesn't have a public rates API, so we use static rates
    that should be updated periodically.
    """
    from_rate = RATES_TO_NGN.get(from_currency.upper(), 1.0)
    to_rate = RATES_TO_NGN.get(to_currency.upper(), 1.0)
    if to_rate > 0:
        rate = from_rate / to_rate
    else:
        rate = 0.0

    return {
        "success": True,
        "rate": rate,
        "source": {"currency": from_currency, "amount": amount},
        "destination": {"currency": to_currency, "amount": round(amount * rate, 2)},
    }
