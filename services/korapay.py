"""
Korapay payment service for NGN collections (buy SIDI) and disbursements (sell SIDI).
Handles virtual account generation, bank verification, and payouts.
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

HEADERS = {
    "Authorization": f"Bearer {KORAPAY_SECRET_KEY}",
    "Content-Type": "application/json",
}


async def _request(method: str, endpoint: str, data: dict = None, retries: int = 3) -> dict:
    """Make an HTTP request to Korapay API with retry logic."""
    url = f"{KORAPAY_BASE_URL}{endpoint}"
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    response = await client.get(url, headers=HEADERS, params=data)
                elif method == "POST":
                    response = await client.post(url, headers=HEADERS, json=data)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                result = response.json()
                if response.status_code in (200, 201):
                    return result
                else:
                    logger.error(f"Korapay API error ({response.status_code}): {result}")
                    if attempt == retries - 1:
                        return {"status": False, "message": result.get("message", "API error")}
        except httpx.TimeoutException:
            logger.warning(f"Korapay request timeout (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                return {"status": False, "message": "Request timed out"}
        except Exception as e:
            logger.error(f"Korapay request error (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return {"status": False, "message": str(e)}

        # Exponential backoff
        await _sleep(2 ** attempt)

    return {"status": False, "message": "Max retries exceeded"}


async def _sleep(seconds: float):
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)


# ── Collections (Buy SIDI) ────────────────────────────────────

async def create_virtual_account(
    reference: str,
    amount: float,
    customer_name: str,
    customer_email: str = "user@sidicoin.app",
    narration: str = "Sidicoin Purchase",
) -> dict:
    """
    Create a temporary virtual bank account for payment collection.
    Returns bank details or error.
    """
    payload = {
        "reference": reference,
        "amount": amount,
        "currency": "NGN",
        "customer": {
            "name": customer_name,
            "email": customer_email,
        },
        "narration": narration,
        "notification_url": "https://coin.sidihost.sbs/webhook/korapay",
        "type": "bank_transfer",
    }

    result = await _request("POST", "/charges/initialize", payload)

    if result.get("status") is True or result.get("data"):
        data = result.get("data", {})
        bank_info = data.get("bank_account", {})
        return {
            "success": True,
            "bank_name": bank_info.get("bank_name", ""),
            "account_number": bank_info.get("account_number", ""),
            "account_name": bank_info.get("account_name", "Sidicoin"),
            "reference": reference,
            "amount": amount,
            "expiry": data.get("expiry_date", ""),
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "Could not generate payment details"),
        }


# ── Verify payment status ─────────────────────────────────────

async def verify_charge(reference: str) -> dict:
    """Verify the status of a charge/payment."""
    result = await _request("GET", f"/charges/{reference}")

    if result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "status": data.get("status", ""),
            "amount": float(data.get("amount", 0)),
            "reference": data.get("reference", reference),
            "paid_at": data.get("paid_at", ""),
        }

    return {"success": False, "message": result.get("message", "Verification failed")}


# ── Bank Verification ─────────────────────────────────────────

async def get_bank_list() -> list[dict]:
    """Get list of supported Nigerian banks."""
    result = await _request("GET", "/misc/banks", {"countryCode": "NG"})

    if result.get("data"):
        banks = result["data"]
        return [{"name": b.get("name", ""), "code": b.get("code", "")} for b in banks]

    return []


async def verify_bank_account(bank_code: str, account_number: str) -> dict:
    """
    Verify a bank account and return the account holder's name.
    """
    payload = {
        "bank": bank_code,
        "account": account_number,
        "currency": "NGN",
    }

    result = await _request("POST", "/misc/banks/resolve", payload)

    if result.get("data"):
        data = result["data"]
        return {
            "success": True,
            "account_name": data.get("account_name", ""),
            "account_number": data.get("account_number", account_number),
            "bank_code": bank_code,
        }

    return {
        "success": False,
        "message": result.get("message", "Could not verify account"),
    }


# ── Disbursements (Sell SIDI / Cashout) ───────────────────────

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
    """
    payload = {
        "reference": reference,
        "destination": {
            "type": "bank_account",
            "amount": amount,
            "currency": "NGN",
            "narration": narration,
            "bank_account": {
                "bank": bank_code,
                "account": account_number,
                "account_name": account_name,
            },
            "customer": {
                "name": account_name,
                "email": "user@sidicoin.app",
            },
        },
    }

    result = await _request("POST", "/transactions/disburse", payload)

    if result.get("data") or result.get("status") is True:
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


# ── Webhook verification ──────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify Korapay webhook HMAC-SHA512 signature.
    """
    if not KORAPAY_WEBHOOK_SECRET or not signature:
        return False

    expected = hmac.new(
        KORAPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected.lower(), signature.lower())


# ── Common bank codes mapping ─────────────────────────────────

COMMON_BANKS = {
    "access": "044",
    "access bank": "044",
    "gtb": "058",
    "gtbank": "058",
    "guaranty trust": "058",
    "first bank": "011",
    "firstbank": "011",
    "uba": "033",
    "united bank for africa": "033",
    "zenith": "057",
    "zenith bank": "057",
    "kuda": "50211",
    "kuda bank": "50211",
    "opay": "999992",
    "palmpay": "999991",
    "moniepoint": "50515",
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
    "jaiz": "301",
    "jaiz bank": "301",
    "suntrust": "100",
    "globus": "00103",
    "globus bank": "00103",
    "taj": "302",
    "taj bank": "302",
    "lotus": "303",
    "lotus bank": "303",
}


def get_bank_code(bank_name: str) -> str:
    """Get bank code from a common bank name. Returns empty string if not found."""
    return COMMON_BANKS.get(bank_name.lower().strip(), "")
