"""
Telegram OTP verification service.
Sends 6-digit codes via Telegram DM for high-risk actions.
Codes expire in 5 minutes, max 3 attempts per code.
"""

import os
import json
import time
import random
import logging
from typing import Optional

from upstash_redis import Redis

logger = logging.getLogger("sidicoin.otp")

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

redis = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)

OTP_TTL = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 3
OTP_COOLDOWN = 60  # 60 seconds between OTPs
OTP_FLAG_THRESHOLD = 5  # Flag account after 5 cumulative failures
LARGE_SEND_THRESHOLD = 5000.0  # SIDI amount that triggers OTP on sends
SESSION_TIMEOUT = 1800  # 30 minutes inactivity triggers re-verification


def _otp_key(telegram_id: int | str) -> str:
    return f"otp_{telegram_id}"


def _otp_failure_key(telegram_id: int | str) -> str:
    return f"otp_fail_{telegram_id}"


def _session_key(telegram_id: int | str) -> str:
    return f"otp_session_{telegram_id}"


def generate_otp(telegram_id: int | str, action: str, action_data: dict = None) -> dict:
    """
    Generate a 6-digit OTP and store in Redis.
    Returns {"success": True, "code": "123456"} or {"success": False, "message": "..."}.
    """
    tid = str(telegram_id)

    # Check cooldown
    try:
        existing = redis.get(_otp_key(tid))
        if existing:
            if isinstance(existing, str):
                existing = json.loads(existing)
            created_at = int(existing.get("created_at", 0))
            elapsed = int(time.time()) - created_at
            if elapsed < OTP_COOLDOWN:
                remaining = OTP_COOLDOWN - elapsed
                return {
                    "success": False,
                    "message": f"Please wait {remaining}s before requesting a new code.",
                    "cooldown": True,
                }
    except Exception as e:
        logger.error(f"OTP cooldown check error: {e}")

    # Generate code
    code = f"{random.randint(100000, 999999)}"
    now = int(time.time())

    otp_data = {
        "code": code,
        "action": action,
        "action_data": action_data or {},
        "attempts": 0,
        "created_at": now,
    }

    try:
        redis.set(_otp_key(tid), json.dumps(otp_data))
        redis.expire(_otp_key(tid), OTP_TTL)
        return {"success": True, "code": code}
    except Exception as e:
        logger.error(f"OTP generate error: {e}")
        return {"success": False, "message": "Could not generate verification code."}


def verify_otp(telegram_id: int | str, entered_code: str) -> dict:
    """
    Verify OTP code.
    Returns {"success": True, "action": "...", "action_data": {...}} on success.
    Returns {"success": False, "message": "...", "locked": bool} on failure.
    """
    tid = str(telegram_id)

    try:
        raw = redis.get(_otp_key(tid))
        if not raw:
            return {"success": False, "message": "No active code. Request a new one.", "locked": False}

        if isinstance(raw, str):
            otp_data = json.loads(raw)
        elif isinstance(raw, dict):
            otp_data = raw
        else:
            return {"success": False, "message": "Invalid OTP data.", "locked": False}

        stored_code = str(otp_data.get("code", ""))
        attempts = int(otp_data.get("attempts", 0))

        # Check if max attempts exceeded
        if attempts >= OTP_MAX_ATTEMPTS:
            redis.delete(_otp_key(tid))
            _increment_failures(tid)
            return {
                "success": False,
                "message": "Too many attempts. Request a new code.",
                "locked": True,
            }

        # Verify
        if entered_code.strip() == stored_code:
            # Success -- clear OTP and mark session as verified
            action = otp_data.get("action", "")
            action_data = otp_data.get("action_data", {})
            redis.delete(_otp_key(tid))
            _mark_session_verified(tid)
            return {
                "success": True,
                "action": action,
                "action_data": action_data,
            }
        else:
            # Wrong code -- increment attempts
            otp_data["attempts"] = attempts + 1
            redis.set(_otp_key(tid), json.dumps(otp_data))
            redis.expire(_otp_key(tid), OTP_TTL)
            remaining = OTP_MAX_ATTEMPTS - (attempts + 1)
            return {
                "success": False,
                "message": f"Wrong code. {remaining} attempt{'s' if remaining != 1 else ''} left.",
                "locked": False,
            }

    except Exception as e:
        logger.error(f"OTP verify error: {e}")
        return {"success": False, "message": "Verification error. Try again.", "locked": False}


def _increment_failures(telegram_id: str):
    """Track cumulative OTP failures for suspicious activity."""
    try:
        key = _otp_failure_key(telegram_id)
        count = redis.incr(key)
        redis.expire(key, 86400)  # Reset daily
        return int(count)
    except Exception as e:
        logger.error(f"OTP failure tracking error: {e}")
        return 0


def get_otp_failure_count(telegram_id: int | str) -> int:
    """Get cumulative OTP failure count (resets daily)."""
    try:
        val = redis.get(_otp_failure_key(str(telegram_id)))
        return int(val) if val else 0
    except Exception:
        return 0


def is_account_otp_flagged(telegram_id: int | str) -> bool:
    """Check if user has exceeded OTP failure threshold."""
    return get_otp_failure_count(telegram_id) >= OTP_FLAG_THRESHOLD


def _mark_session_verified(telegram_id: str):
    """Mark user session as OTP-verified for the session timeout period."""
    try:
        redis.set(_session_key(telegram_id), str(int(time.time())))
        redis.expire(_session_key(telegram_id), SESSION_TIMEOUT)
    except Exception as e:
        logger.error(f"Session mark error: {e}")


def is_session_verified(telegram_id: int | str) -> bool:
    """Check if user has a recent OTP verification (within session timeout)."""
    try:
        val = redis.get(_session_key(str(telegram_id)))
        if not val:
            return False
        verified_at = int(val)
        return (int(time.time()) - verified_at) < SESSION_TIMEOUT
    except Exception:
        return False


def needs_otp(telegram_id: int | str, action: str, amount: float = 0) -> bool:
    """
    Determine if an action requires OTP verification.
    Skip if session is recently verified (within 30 min).
    """
    # Always require OTP for these
    always_otp = ["sell_confirm", "bank_change", "escrow_fund"]
    if action in always_otp:
        if is_session_verified(telegram_id):
            return False
        return True

    # Large sends
    if action == "send_confirm" and amount >= LARGE_SEND_THRESHOLD:
        if is_session_verified(telegram_id):
            return False
        return True

    return False


ACTION_DESCRIPTIONS = {
    "sell_confirm": "Cash out SIDI to your bank",
    "escrow_fund": "Fund an escrow transaction",
    "send_confirm": "Send a large transfer",
    "bank_change": "Update your bank details",
}


async def send_otp_message(bot, telegram_id: int | str, action: str, action_data: dict = None) -> dict:
    """
    Generate OTP and send it to user via Telegram DM.
    Returns generate_otp result.
    """
    result = generate_otp(telegram_id, action, action_data)
    if not result.get("success"):
        return result

    code = result["code"]
    description = ACTION_DESCRIPTIONS.get(action, "perform this action")

    try:
        await bot.send_message(
            chat_id=int(telegram_id),
            text=(
                f"\U0001f510 <b>Verification Code</b>\n\n"
                f"Your code to {description}:\n\n"
                f"  <code>{code}</code>\n\n"
                f"  Expires in 5 minutes\n"
                f"  Do NOT share this code\n\n"
                f"Type the 6-digit code below to confirm."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"OTP send message error: {e}")
        return {"success": False, "message": "Could not send verification code."}

    return result
