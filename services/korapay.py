"""
Korapay payment service for NGN collections (buy SIDI) and disbursements (sell SIDI).
Handles dynamic bank transfer accounts, bank verification, and payouts.

Correct Korapay API endpoints (as of 2026):
- Bank Transfer (collection): POST /charges/bank_transfer
- Charge query: GET /charges/:reference
- Resolve bank account: POST /misc/banks/resolve
- Disburse (payout): POST /transactions/disburse
- Bank list: GET /misc/banks?countryCode=NG
"""

import os
import hmac
import hashlib
import logging
import time

import httpx

logger = logging.getLogger("sidicoin.korapay")

KORAPAY_SECRET_KEY = os.getenv("KORAPAY_SECRET_KEY", "")
KORAPAY_PUBLIC_KEY = os.getenv("KORAPAY_PUBLIC_KEY", "")
KORAPAY_WEBHOOK_SECRET = os.getenv("KORAPAY_WEBHOOK_SECRET", "")
KORAPAY_BASE_URL = "https://api.korapay.com/merchant/api/v1"


def _headers() -> dict:
    """Build auth headers fresh every time (env may reload)."""
    secret = os.getenv("KORAPAY_SECRET_KEY", KORAPAY_SECRET_KEY)
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


async def _request(
    method: str, endpoint: str, data: dict = None, retries: int = 3
) -> dict:
    """Make an HTTP request to Korapay API with retry + exponential backoff."""
    url = f"{KORAPAY_BASE_URL}{endpoint}"
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
                    f"Korapay {method} {endpoint} -> {resp.status_code}: "
                    f"{body.get('message', '')}"
                )

                if resp.status_code in (200, 201):
                    return body

                # 4xx client errors should not be retried (except 429)
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    return {
                        "status": False,
                        "message": body.get("message", f"HTTP {resp.status_code}"),
                        "data": body.get("data"),
                    }

                last_error = body.get("message", f"HTTP {resp.status_code}")

        except httpx.TimeoutException:
            last_error = "Request timed out"
            logger.warning(f"Korapay timeout (attempt {attempt + 1}/{retries})")
        except Exception as e:
            last_error = str(e)
            logger.error(f"Korapay error (attempt {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            import asyncio
            await asyncio.sleep(1.5 ** attempt)

    return {"status": False, "message": last_error or "Max retries exceeded"}


# =====================================================================
#  COLLECTIONS  --  Buy SIDI (Bank Transfer)
# =====================================================================

async def create_bank_transfer_charge(
    reference: str,
    amount: float,
    customer_name: str,
    customer_email: str = "user@sidicoin.app",
    narration: str = "Sidicoin Purchase",
) -> dict:
    """
    Create a dynamic one-time bank account for payment collection.
    Uses Korapay Pay with Bank Transfer API.

    POST /charges/bank_transfer
    Ref: https://developers.korapay.com/docs/bank-transfers

    Returns dict with success, bank_name, account_number, etc.
    """
    # Reference must be at least 8 characters per Korapay docs
    if len(reference) < 8:
        reference = f"SIDI-{reference}"

    # Per Korapay docs: amount is Number type
    charge_amount = round(float(amount), 2)

    payload = {
        "reference": reference,
        "amount": charge_amount,
        "currency": "NGN",
        "narration": narration,
        "notification_url": "https://coin.sidihost.sbs/webhook/korapay",
        "customer": {
            "name": customer_name or "Sidicoin User",
            "email": customer_email,
        },
        "merchant_bears_cost": False,
    }

    logger.info(f"Creating bank transfer charge: ref={reference}, amount={charge_amount}")

    result = await _request("POST", "/charges/bank_transfer", payload)

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        bank = data.get("bank_account", {})
        fee = float(data.get("fee", 0))
        vat = float(data.get("vat", 0))
        total_fee = fee + vat

        return {
            "success": True,
            "bank_name": bank.get("bank_name", "Wema Bank"),
            "account_number": bank.get("account_number", ""),
            "account_name": bank.get("account_name", "Sidicoin"),
            "bank_code": bank.get("bank_code", ""),
            "reference": data.get("reference", reference),
            "amount": float(data.get("amount_expected", charge_amount)),
            "fee": total_fee,
            "expiry": bank.get("expiry_date_in_utc", ""),
            "status": data.get("status", "processing"),
        }

    return {
        "success": False,
        "message": result.get("message", "Could not generate payment account"),
    }


# Keep backward-compatible alias
create_virtual_account = create_bank_transfer_charge


# =====================================================================
#  VERIFY CHARGE STATUS
# =====================================================================

async def verify_charge(reference: str) -> dict:
    """Verify the status of a charge via the Charge Query API."""
    result = await _request("GET", f"/charges/{reference}")

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "status": data.get("status", ""),
            "amount": float(data.get("amount", 0)),
            "amount_paid": float(data.get("amount_paid", 0)),
            "fee": float(data.get("fee", 0)),
            "reference": data.get("reference", reference),
        }

    return {"success": False, "message": result.get("message", "Verification failed")}


# =====================================================================
#  BANK VERIFICATION
# =====================================================================

async def get_bank_list() -> list[dict]:
    """Get list of supported Nigerian banks."""
    result = await _request("GET", "/misc/banks", {"countryCode": "NG"})

    if result.get("data") and isinstance(result["data"], list):
        return [
            {"name": b.get("name", ""), "code": b.get("code", "")}
            for b in result["data"]
        ]
    return []


async def verify_bank_account(bank_code: str, account_number: str) -> dict:
    """
    Resolve/verify a bank account and return the account holder's name.
    POST /misc/banks/resolve
    """
    payload = {
        "bank": bank_code,
        "account": account_number,
        "currency": "NG",
    }

    logger.info(f"Resolving bank account: bank={bank_code}, account={account_number}")

    result = await _request("POST", "/misc/banks/resolve", payload)

    logger.info(f"Resolve result: status={result.get('status')}, data={result.get('data')}")

    if result.get("status") is True and result.get("data"):
        data = result["data"]
        account_name = data.get("account_name", "")
        if account_name:
            return {
                "success": True,
                "account_name": account_name,
                "account_number": data.get("account_number", account_number),
                "bank_name": data.get("bank_name", ""),
                "bank_code": data.get("bank_code", bank_code),
            }
        else:
            return {
                "success": False,
                "message": "Account name not returned. Check account number.",
            }

    return {
        "success": False,
        "message": result.get("message", "Could not verify account. Check bank code and account number."),
    }


# =====================================================================
#  DISBURSEMENTS  --  Sell SIDI / Cashout
# =====================================================================

async def process_payout(
    reference: str,
    amount: float,
    bank_code: str,
    account_number: str,
    account_name: str,
    narration: str = "Sidicoin Cashout",
) -> dict:
    """
    Send money to a bank account via Korapay disbursement.
    POST /transactions/disburse
    """
    # Per Korapay docs: destination.amount is Number type, two decimal places
    payout_amount = round(float(amount), 2)

    payload = {
        "reference": reference,
        "destination": {
            "type": "bank_account",
            "amount": payout_amount,
            "currency": "NGN",
            "narration": narration,
            "bank_account": {
                "bank": bank_code,
                "account": account_number,
            },
            "customer": {
                "name": account_name,
                "email": "user@sidicoin.app",
            },
        },
    }

    logger.info(f"Payout request: ref={reference}, amount={payout_amount}, bank={bank_code}, acct={account_number}")

    result = await _request("POST", "/transactions/disburse", payload)

    if result.get("status") is True or result.get("data"):
        data = result.get("data", {})
        return {
            "success": True,
            "reference": data.get("reference", reference),
            "status": data.get("status", "processing"),
            "amount": amount,
        }

    return {
        "success": False,
        "message": result.get("message", "Payout failed"),
    }


# =====================================================================
#  WEBHOOK SIGNATURE VERIFICATION
# =====================================================================

def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify Korapay webhook HMAC-SHA512 signature.
    The signature header is 'x-korapay-signature'.
    """
    secret = os.getenv("KORAPAY_WEBHOOK_SECRET", KORAPAY_WEBHOOK_SECRET)
    if not secret or not signature:
        logger.warning("Webhook verification: missing secret or signature")
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected.lower(), signature.lower())


# =====================================================================
#  COMMON BANK CODES  (Nigerian banks)
# =====================================================================

COMMON_BANKS = {
    "access": "044",
    "access bank": "044",
    "gtb": "058",
    "gt bank": "058",
    "gtbank": "058",
    "guaranty trust": "058",
    "guaranty trust bank": "058",
    "first bank": "011",
    "firstbank": "011",
    "uba": "033",
    "united bank for africa": "033",
    "zenith": "057",
    "zenith bank": "057",
    "kuda": "50211",
    "kuda bank": "50211",
    "kuda mfb": "50211",
    "opay": "999992",
    "palmpay": "999991",
    "moniepoint": "50515",
    "moniepoint mfb": "50515",
    "wema": "035",
    "wema bank": "035",
    "stanbic": "221",
    "stanbic ibtc": "221",
    "sterling": "232",
    "sterling bank": "232",
    "union": "032",
    "union bank": "032",
    "fidelity": "070",
    "fidelity bank": "070",
    "fcmb": "214",
    "polaris": "076",
    "polaris bank": "076",
    "ecobank": "050",
    "keystone": "082",
    "keystone bank": "082",
    "heritage": "030",
    "heritage bank": "030",
    "unity": "215",
    "unity bank": "215",
    "providus": "101",
    "providus bank": "101",
    "titan trust": "102",
    "titan trust bank": "102",
    "jaiz": "301",
    "jaiz bank": "301",
    "suntrust": "100",
    "globus": "00103",
    "globus bank": "00103",
    "taj": "302",
    "taj bank": "302",
    "lotus": "303",
    "lotus bank": "303",
    "9mobile": "120001",
    "9psb": "120001",
    "sparkle": "51310",
    "sparkle mfb": "51310",
    "carbon": "565",
    "rubies": "125",
    "rubies bank": "125",
    "vfd": "566",
    "vfd mfb": "566",
}


def get_bank_code(bank_name: str) -> str:
    """Get bank code from a common bank name. Returns empty string if not found."""
    return COMMON_BANKS.get(bank_name.lower().strip(), "")
