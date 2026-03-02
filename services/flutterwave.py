"""
Flutterwave payment service for international collections and payouts.
Supports cards (Visa/Mastercard globally), mobile money (M-Pesa, MTN),
bank transfers across Africa, and USD/GBP/EUR payouts.

Korapay is kept for NGN-only operations. Flutterwave handles international.

API docs: https://developer.flutterwave.com/reference
"""

import os
import hmac
import hashlib
import logging
import time

import httpx

logger = logging.getLogger("sidicoin.flutterwave")

FLW_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLW_PUBLIC_KEY = os.getenv("FLUTTERWAVE_PUBLIC_KEY", "")
FLW_WEBHOOK_HASH = os.getenv("FLUTTERWAVE_WEBHOOK_HASH", "")
FLW_BASE_URL = "https://api.flutterwave.com/v3"

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
        "methods": ["mobile_money_ghana", "card"],
        "payout_type": "mobile_money",
        "min_payout": 1,
    },
    "KE": {
        "currency": "KES",
        "name": "Kenya",
        "flag": "\U0001f1f0\U0001f1ea",
        "methods": ["mpesa", "card"],
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
        "methods": ["mobile_money_tanzania", "card"],
        "payout_type": "mobile_money",
        "min_payout": 100,
    },
    "UG": {
        "currency": "UGX",
        "name": "Uganda",
        "flag": "\U0001f1fa\U0001f1ec",
        "methods": ["mobile_money_uganda", "card"],
        "payout_type": "mobile_money",
        "min_payout": 500,
    },
    "RW": {
        "currency": "RWF",
        "name": "Rwanda",
        "flag": "\U0001f1f7\U0001f1fc",
        "methods": ["mobile_money_rwanda", "card"],
        "payout_type": "mobile_money",
        "min_payout": 100,
    },
    "CM": {
        "currency": "XAF",
        "name": "Cameroon",
        "flag": "\U0001f1e8\U0001f1f2",
        "methods": ["mobile_money_franco", "card"],
        "payout_type": "mobile_money",
        "min_payout": 100,
    },
    "CI": {
        "currency": "XOF",
        "name": "Ivory Coast",
        "flag": "\U0001f1e8\U0001f1ee",
        "methods": ["mobile_money_franco", "card"],
        "payout_type": "mobile_money",
        "min_payout": 100,
    },
    "SN": {
        "currency": "XOF",
        "name": "Senegal",
        "flag": "\U0001f1f8\U0001f1f3",
        "methods": ["mobile_money_franco", "card"],
        "payout_type": "mobile_money",
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
# In production, you'd fetch these from Flutterwave's rates API
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
    secret = os.getenv("FLUTTERWAVE_SECRET_KEY", FLW_SECRET_KEY)
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


async def _request(
    method: str, endpoint: str, data: dict = None, retries: int = 3
) -> dict:
    """Make an HTTP request to Flutterwave API with retry + backoff."""
    url = f"{FLW_BASE_URL}{endpoint}"
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
                    return {"status": "error", "message": f"Unsupported method: {method}"}

                body = resp.json()
                logger.info(
                    f"Flutterwave {method} {endpoint} -> {resp.status_code}: "
                    f"{body.get('message', '')}"
                )

                if resp.status_code in (200, 201):
                    return body

                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return {
                        "status": "error",
                        "message": body.get("message", f"HTTP {resp.status_code}"),
                        "data": body.get("data"),
                    }

                last_error = body.get("message", f"HTTP {resp.status_code}")

        except httpx.TimeoutException:
            last_error = "Request timed out"
            logger.warning(f"Flutterwave timeout (attempt {attempt + 1}/{retries})")
        except Exception as e:
            last_error = str(e)
            logger.error(f"Flutterwave error (attempt {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            import asyncio
            await asyncio.sleep(1.5 ** attempt)

    return {"status": "error", "message": last_error or "Max retries exceeded"}


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
        "fr": "CI",  # French -> Ivory Coast (large French-speaking market)
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
    # Try exact match first, then prefix
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
    Create a Flutterwave payment link (Standard).
    Works for cards, mobile money, bank transfer, USSD, etc.

    Returns: {success, link, reference}
    """
    payload = {
        "tx_ref": reference,
        "amount": round(float(amount), 2),
        "currency": currency.upper(),
        "redirect_url": redirect_url,
        "payment_options": payment_type,
        "customer": {
            "name": customer_name or "Sidicoin User",
            "email": customer_email,
        },
        "customizations": {
            "title": "Sidicoin",
            "description": narration,
            "logo": "https://coin.sidihost.sbs/logo.png",
        },
        "meta": meta or {},
    }

    result = await _request("POST", "/payments", payload)

    if result.get("status") == "success" and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "link": data.get("link", ""),
            "reference": reference,
        }

    return {
        "success": False,
        "message": result.get("message", "Could not create payment link"),
    }


async def create_charge(
    reference: str,
    amount: float,
    currency: str,
    payment_type: str,
    customer_email: str = "user@sidicoin.app",
    customer_phone: str = "",
    customer_name: str = "",
    meta: dict = None,
) -> dict:
    """
    Direct charge API for specific payment methods.
    For NGN bank transfers, use Korapay instead.
    This is mainly for mobile money charges.
    """
    endpoint_map = {
        "mpesa": "/charges?type=mpesa",
        "mobile_money_ghana": "/charges?type=mobile_money_ghana",
        "mobile_money_uganda": "/charges?type=mobile_money_uganda",
        "mobile_money_tanzania": "/charges?type=mobile_money_tanzania",
        "mobile_money_rwanda": "/charges?type=mobile_money_rwanda",
        "mobile_money_franco": "/charges?type=mobile_money_franco",
    }

    endpoint = endpoint_map.get(payment_type)
    if not endpoint:
        return {"success": False, "message": f"Unsupported charge type: {payment_type}"}

    payload = {
        "tx_ref": reference,
        "amount": round(float(amount), 2),
        "currency": currency.upper(),
        "email": customer_email,
        "phone_number": customer_phone,
        "fullname": customer_name or "Sidicoin User",
        "meta": meta or {},
    }

    result = await _request("POST", endpoint, payload)

    if result.get("status") == "success":
        data = result.get("data", {})
        return {
            "success": True,
            "status": data.get("status", "pending"),
            "reference": reference,
            "message": data.get("message", ""),
            "data": data,
        }

    return {
        "success": False,
        "message": result.get("message", "Charge failed"),
    }


async def verify_transaction(transaction_id: str) -> dict:
    """Verify a Flutterwave transaction by ID."""
    result = await _request("GET", f"/transactions/{transaction_id}/verify")

    if result.get("status") == "success" and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "status": data.get("status", ""),
            "amount": float(data.get("amount", 0)),
            "currency": data.get("currency", ""),
            "tx_ref": data.get("tx_ref", ""),
            "flw_ref": data.get("flw_ref", ""),
        }

    return {"success": False, "message": result.get("message", "Verification failed")}


# =====================================================================
#  PAYOUTS -- Send money (Withdraw from SIDI wallet)
# =====================================================================

async def create_transfer(
    reference: str,
    amount: float,
    currency: str,
    beneficiary_name: str,
    account_number: str = "",
    bank_code: str = "",
    account_bank: str = "",
    meta: dict = None,
    destination_branch_code: str = "",
    debit_currency: str = "NGN",
    narration: str = "Sidicoin Withdrawal",
) -> dict:
    """
    Send money to a bank account or mobile money wallet.
    Works internationally.
    """
    payload = {
        "account_bank": account_bank or bank_code,
        "account_number": account_number,
        "amount": round(float(amount), 2),
        "narration": narration,
        "currency": currency.upper(),
        "reference": reference,
        "beneficiary_name": beneficiary_name,
        "debit_currency": debit_currency,
        "meta": meta or [],
    }

    if destination_branch_code:
        payload["destination_branch_code"] = destination_branch_code

    result = await _request("POST", "/transfers", payload)

    if result.get("status") == "success":
        data = result.get("data", {})
        return {
            "success": True,
            "id": data.get("id", ""),
            "reference": reference,
            "status": data.get("status", "NEW"),
            "amount": float(data.get("amount", amount)),
            "currency": data.get("currency", currency),
        }

    return {
        "success": False,
        "message": result.get("message", "Transfer failed"),
    }


async def create_mobile_money_transfer(
    reference: str,
    amount: float,
    currency: str,
    phone_number: str,
    network: str,
    beneficiary_name: str,
    narration: str = "Sidicoin Withdrawal",
) -> dict:
    """Send money via mobile money (M-Pesa, MTN, etc.)."""
    # Mobile money bank codes by network/country
    network_bank_map = {
        "mpesa_ke": "MPS",
        "mtn_gh": "MTN",
        "vodafone_gh": "VDF",
        "tigo_gh": "TGO",
        "mtn_ug": "MPS",
        "airtel_ug": "MPS",
        "mpesa_tz": "MPS",
        "tigo_tz": "MPS",
        "mtn_rw": "MPS",
        "mtn_cm": "FMM",
        "orange_cm": "FMM",
        "mtn_ci": "FMM",
        "orange_ci": "FMM",
        "wave_sn": "FMM",
        "orange_sn": "FMM",
    }

    account_bank = network_bank_map.get(network.lower(), "MPS")

    return await create_transfer(
        reference=reference,
        amount=amount,
        currency=currency,
        beneficiary_name=beneficiary_name,
        account_number=phone_number,
        account_bank=account_bank,
        narration=narration,
    )


# =====================================================================
#  BANK LIST
# =====================================================================

async def get_banks(country: str = "NG") -> list[dict]:
    """Get list of banks for a country."""
    result = await _request("GET", f"/banks/{country.upper()}")

    if result.get("status") == "success" and result.get("data"):
        return [
            {"name": b.get("name", ""), "code": b.get("code", "")}
            for b in result["data"]
        ]
    return []


async def resolve_account(account_number: str, bank_code: str) -> dict:
    """Verify/resolve a bank account."""
    payload = {
        "account_number": account_number,
        "account_bank": bank_code,
    }

    result = await _request("POST", "/accounts/resolve", payload)

    if result.get("status") == "success" and result.get("data"):
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
    Verify Flutterwave webhook.
    Flutterwave sends a 'verif-hash' header that should match your secret hash.
    """
    secret_hash = os.getenv("FLUTTERWAVE_WEBHOOK_HASH", FLW_WEBHOOK_HASH)
    if not secret_hash or not signature:
        logger.warning("Flutterwave webhook: missing hash or signature")
        return False
    return hmac.compare_digest(signature, secret_hash)


# =====================================================================
#  EXCHANGE RATE (live fetch)
# =====================================================================

async def get_exchange_rate(from_currency: str, to_currency: str, amount: float = 1.0) -> dict:
    """
    Get live exchange rate from Flutterwave.
    Falls back to static rates if API fails.
    """
    try:
        result = await _request("GET", f"/rates", {
            "from": from_currency.upper(),
            "to": to_currency.upper(),
            "amount": amount,
        })

        if result.get("status") == "success" and result.get("data"):
            data = result["data"]
            return {
                "success": True,
                "rate": float(data.get("rate", 0)),
                "source": data.get("source", {}),
                "destination": data.get("destination", {}),
            }
    except Exception as e:
        logger.error(f"Exchange rate API error: {e}")

    # Fallback to static rates
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
