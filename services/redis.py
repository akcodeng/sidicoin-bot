"""
Upstash Redis REST API service for all user data and state management.
All user data stored as JSON under key user_{telegram_id}.
Global keys: all_users (set), stats (hash), leaderboard (sorted set).
"""

import os
import json
import time
import logging
import functools
from typing import Any, Optional

from upstash_redis import Redis

logger = logging.getLogger("sidicoin.redis")

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

redis = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)


def _retry(max_retries: int = 3, default=None):
    """Decorator for retrying Redis operations with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait = 0.1 * (2 ** attempt)
                        time.sleep(wait)
                        logger.warning(
                            f"Redis retry {attempt + 1}/{max_retries} for {func.__name__}: {e}"
                        )
            logger.error(f"Redis {func.__name__} failed after {max_retries} retries: {last_error}")
            return default
        return wrapper
    return decorator

# ── Default user data template ─────────────────────────────────

MAX_REFERRALS = 5  # Max referrals per user
WELCOME_BONUS_SIDI = 10.0  # 250 naira = 10 SIDI at 25 NGN/SIDI
WELCOME_BONUS_HOLD_DAYS = 2  # Days before welcome bonus can be withdrawn
DAILY_CHECKIN_FREE = 2.0  # 50 naira = 2 SIDI
DAILY_CHECKIN_PREMIUM = 5.0  # Premium daily checkin

DEFAULT_USER = {
    "telegram_id": "",
    "username": "",
    "full_name": "",
    "photo_url": "",
    "wallet_address": "",
    "private_key": "",
    "sidi_balance": 0.0,
    "is_premium": False,
    "premium_expiry": 0,
    "referral_code": "",
    "referred_by": "",
    "referral_count": 0,
    "referral_earnings": 0.0,
    "referral_earnings_locked": 0.0,  # Locked until referral makes a transaction
    "referral_earnings_unlocked": 0.0,  # Unlocked by referral transactions
    "total_sent": 0.0,
    "total_received": 0.0,
    "total_bought_ngn": 0.0,
    "total_sold_ngn": 0.0,
    "daily_checkin_last": 0,
    "checkin_streak": 0,
    "transactions": [],
    "saved_contacts": [],
    "bank_name": "",
    "bank_code": "",
    "bank_account": "",
    "bank_account_name": "",
    "daily_tx_total": 0.0,
    "daily_tx_date": "",
    "joined_date": 0,
    "is_banned": False,
    "last_active": 0,
    "welcome_bonus_claimed": False,
    "welcome_bonus_hold_until": 0,  # Welcome bonus withdrawal lock (2 days)
    "cashout_hold_until": 0,
    "pending_action": "",
    "pending_data": {},
    # Anti-fraud fields
    "device_fingerprint": "",  # Hash of user metadata for multi-account detection
    "flagged_multi_account": False,
    "linked_accounts": [],  # Suspected linked accounts
}


def _user_key(telegram_id: int | str) -> str:
    return f"user_{telegram_id}"


def _rate_key(telegram_id: int | str) -> str:
    return f"rate_{telegram_id}"


# ── User CRUD ──────────────────────────────────────────────────

@_retry(max_retries=3, default=None)
def get_user(telegram_id: int | str) -> Optional[dict]:
    """Fetch a user from Redis. Returns None if not found."""
    data = redis.get(_user_key(telegram_id))
    if data is None:
        return None
    if isinstance(data, str):
        return json.loads(data)
    if isinstance(data, dict):
        return data
    return None


@_retry(max_retries=3, default=False)
def save_user(telegram_id: int | str, user_data: dict) -> bool:
    """Save user data to Redis."""
    user_data["last_active"] = int(time.time())
    redis.set(_user_key(telegram_id), json.dumps(user_data))
    # Also add to all_users set
    redis.sadd("all_users", str(telegram_id))
    # Update leaderboard
    redis.zadd("leaderboard", {str(telegram_id): float(user_data.get("sidi_balance", 0))})
    # Update username index for O(1) lookups
    username = user_data.get("username", "")
    if username:
        redis.set(f"uname_{username.lower()}", str(telegram_id))
    return True


def user_exists(telegram_id: int | str) -> bool:
    """Check if a user exists in Redis."""
    try:
        return redis.exists(_user_key(telegram_id)) == 1
    except Exception:
        return False


def create_user(
    telegram_id: int | str,
    username: str,
    full_name: str,
    photo_url: str,
    wallet_address: str,
    encrypted_private_key: str,
    referred_by: str = "",
) -> dict:
    """Create a new user with default values and welcome bonus."""
    now = int(time.time())
    user = {**DEFAULT_USER}
    user.update({
        "telegram_id": str(telegram_id),
        "username": username,
        "full_name": full_name,
        "photo_url": photo_url,
        "wallet_address": wallet_address,
        "private_key": encrypted_private_key,
        "sidi_balance": WELCOME_BONUS_SIDI,  # 250 naira = 10 SIDI
        "referral_code": f"ref_{telegram_id}",
        "referred_by": referred_by,
        "joined_date": now,
        "last_active": now,
        "welcome_bonus_claimed": True,
        "welcome_bonus_hold_until": now + (WELCOME_BONUS_HOLD_DAYS * 86400),  # 2 days lock
        "cashout_hold_until": now + (WELCOME_BONUS_HOLD_DAYS * 86400),  # 2 days lock
    })
    save_user(telegram_id, user)

    # Add welcome bonus transaction
    add_transaction(telegram_id, {
        "type": "bonus",
        "amount": WELCOME_BONUS_SIDI,
        "description": f"Welcome Bonus ({WELCOME_BONUS_SIDI} SIDI = \u20a6250)",
        "timestamp": now,
        "reference": "WELCOME-BONUS",
    })

    # Increment total holders count
    increment_stat("total_holders", 1)
    increment_stat("circulating_supply", WELCOME_BONUS_SIDI)

    return user


# ── Balance operations ─────────────────────────────────────────

def get_balance(telegram_id: int | str) -> float:
    """Get user's SIDI balance."""
    user = get_user(telegram_id)
    if user:
        return float(user.get("sidi_balance", 0))
    return 0.0


def update_balance(telegram_id: int | str, amount: float) -> bool:
    """Add (positive) or deduct (negative) from user balance."""
    user = get_user(telegram_id)
    if not user:
        return False
    new_balance = float(user.get("sidi_balance", 0)) + amount
    if new_balance < 0:
        return False
    user["sidi_balance"] = new_balance
    save_user(telegram_id, user)
    return True


def transfer_sidi(
    sender_id: int | str,
    recipient_id: int | str,
    amount: float,
    fee: float = 0.0,
) -> bool:
    """Transfer SIDI from sender to recipient. Fee goes to fee wallet."""
    sender = get_user(sender_id)
    recipient = get_user(recipient_id)
    if not sender or not recipient:
        return False

    total_deduction = amount + fee
    if float(sender.get("sidi_balance", 0)) < total_deduction:
        return False

    sender["sidi_balance"] = float(sender["sidi_balance"]) - total_deduction
    sender["total_sent"] = float(sender.get("total_sent", 0)) + amount

    # Update daily tx tracking
    today = time.strftime("%Y-%m-%d")
    if sender.get("daily_tx_date") != today:
        sender["daily_tx_total"] = 0.0
        sender["daily_tx_date"] = today
    sender["daily_tx_total"] = float(sender.get("daily_tx_total", 0)) + amount

    recipient["sidi_balance"] = float(recipient["sidi_balance"]) + amount
    recipient["total_received"] = float(recipient.get("total_received", 0)) + amount

    # Add to saved contacts
    _add_saved_contact(sender, recipient)

    save_user(sender_id, sender)
    save_user(recipient_id, recipient)

    # Track fees
    if fee > 0:
        increment_stat("total_fees_sidi", fee)

    # Update daily volume stats
    from utils.formatting import sidi_to_naira
    increment_stat("daily_volume_ngn", sidi_to_naira(amount))
    increment_stat("daily_tx_count", 1)

    return True


def _add_saved_contact(sender: dict, recipient: dict):
    """Add recipient to sender's saved contacts (max 20)."""
    contacts = sender.get("saved_contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    # Remove existing entry for this recipient
    contacts = [c for c in contacts if c.get("telegram_id") != recipient["telegram_id"]]

    contacts.insert(0, {
        "telegram_id": recipient["telegram_id"],
        "username": recipient.get("username", ""),
        "full_name": recipient.get("full_name", ""),
        "last_transfer": int(time.time()),
    })

    sender["saved_contacts"] = contacts[:20]


# ── Transactions ───────────────────────────────────────────────

def add_transaction(telegram_id: int | str, tx: dict) -> bool:
    """Add a transaction to user's history (keep last 50)."""
    user = get_user(telegram_id)
    if not user:
        return False
    txns = user.get("transactions", [])
    if not isinstance(txns, list):
        txns = []
    txns.insert(0, tx)
    user["transactions"] = txns[:50]
    save_user(telegram_id, user)
    return True


def get_transactions(telegram_id: int | str, tx_type: str = "all") -> list[dict]:
    """Get user transactions, optionally filtered by type."""
    user = get_user(telegram_id)
    if not user:
        return []
    txns = user.get("transactions", [])
    if not isinstance(txns, list):
        return []
    if tx_type == "all":
        return txns
    return [t for t in txns if t.get("type") == tx_type]


# ── Pending state (conversation flows) ────────────────────────

def set_pending_action(telegram_id: int | str, action: str, data: dict = None) -> bool:
    """Set the pending action and data for multi-step flows."""
    user = get_user(telegram_id)
    if not user:
        return False
    user["pending_action"] = action
    user["pending_data"] = data or {}
    save_user(telegram_id, user)
    return True


def get_pending_action(telegram_id: int | str) -> tuple[str, dict]:
    """Get current pending action and data."""
    user = get_user(telegram_id)
    if not user:
        return "", {}
    return user.get("pending_action", ""), user.get("pending_data", {})


def clear_pending_action(telegram_id: int | str) -> bool:
    """Clear pending action after completion or cancellation."""
    user = get_user(telegram_id)
    if not user:
        return False
    user["pending_action"] = ""
    user["pending_data"] = {}
    save_user(telegram_id, user)
    return True


# ── Referral system ────────────────────────────────────────────

def can_refer(referrer_id: int | str) -> bool:
    """Check if the referrer has not exceeded the 5 referral limit."""
    user = get_user(referrer_id)
    if not user:
        return False
    return int(user.get("referral_count", 0)) < MAX_REFERRALS


def credit_referrer(referrer_id: int | str, amount: float, reason: str) -> bool:
    """
    Credit the referrer with bonus SIDI.
    For signup: earnings are LOCKED until the referred user makes a transaction.
    For transaction: unlock previous locked earnings + add bonus.
    Max 5 referrals enforced.
    """
    user = get_user(referrer_id)
    if not user:
        return False

    if reason == "signup":
        # Enforce 5 referral cap
        current_count = int(user.get("referral_count", 0))
        if current_count >= MAX_REFERRALS:
            return False
        # Add to LOCKED balance (not spendable until referral transacts)
        user["referral_earnings_locked"] = float(user.get("referral_earnings_locked", 0)) + amount
        user["referral_earnings"] = float(user.get("referral_earnings", 0)) + amount
        user["referral_count"] = current_count + 1
        # Do NOT add to sidi_balance -- it stays locked
    elif reason == "referral_tx_unlock":
        # Unlock locked referral earnings when referred user transacts
        locked = float(user.get("referral_earnings_locked", 0))
        if locked > 0:
            unlock_amount = min(locked, amount)
            user["referral_earnings_locked"] = locked - unlock_amount
            user["referral_earnings_unlocked"] = float(user.get("referral_earnings_unlocked", 0)) + unlock_amount
            user["sidi_balance"] = float(user.get("sidi_balance", 0)) + unlock_amount
            amount = unlock_amount  # Only credit what was unlocked
        else:
            return False  # Nothing to unlock
    else:
        # Other referral bonuses (legacy)
        user["sidi_balance"] = float(user.get("sidi_balance", 0)) + amount
        user["referral_earnings"] = float(user.get("referral_earnings", 0)) + amount

    save_user(referrer_id, user)

    add_transaction(referrer_id, {
        "type": "referral_bonus",
        "amount": amount,
        "description": f"Referral bonus: {reason}",
        "timestamp": int(time.time()),
        "reference": f"REF-{reason.upper()}-{int(time.time())}",
    })

    if reason != "signup":
        # Only add to circulating supply when actually credited to balance
        increment_stat("circulating_supply", amount)
    return True


def unlock_referral_earnings_on_tx(user_id: int | str) -> None:
    """
    Called when a user performs a transaction (send/buy/sell).
    If they were referred by someone, unlock that referrer's locked earnings.
    """
    user = get_user(user_id)
    if not user:
        return
    referred_by = user.get("referred_by", "")
    if not referred_by:
        return
    # Check if already unlocked (flag in user data)
    if user.get("referral_tx_unlocked"):
        return
    try:
        referrer_id = int(referred_by)
        referrer = get_user(referrer_id)
        if referrer:
            # Unlock the referral bonus (10 SIDI signup bonus)
            credit_referrer(referrer_id, 10.0, "referral_tx_unlock")
            # Mark this user as having unlocked their referrer's bonus
            user["referral_tx_unlocked"] = True
            save_user(user_id, user)
    except (ValueError, Exception) as e:
        logger.error(f"Unlock referral earnings error: {e}")


# ── Premium ────────────────────────────────────────────────────

def activate_premium(telegram_id: int | str) -> bool:
    """Activate premium for 30 days."""
    user = get_user(telegram_id)
    if not user:
        return False
    now = int(time.time())
    user["is_premium"] = True
    user["premium_expiry"] = now + (30 * 86400)
    save_user(telegram_id, user)
    return True


def check_premium_status(user: dict) -> bool:
    """Check if premium is still active."""
    if not user.get("is_premium"):
        return False
    expiry = int(user.get("premium_expiry", 0))
    if expiry == 0:
        return False
    if int(time.time()) > expiry:
        return False
    return True


# ── Daily Check-in ─────────────────────────────────────────────

def process_checkin(telegram_id: int | str) -> tuple[bool, str, float, int]:
    """
    Process daily check-in.
    Returns (success, message, amount_earned, streak).
    """
    user = get_user(telegram_id)
    if not user:
        return False, "User not found", 0.0, 0

    now = int(time.time())
    last_checkin = int(user.get("daily_checkin_last", 0))
    streak = int(user.get("checkin_streak", 0))

    # Check if already checked in today
    if last_checkin > 0:
        last_dt = time.gmtime(last_checkin + 3600)  # WAT offset
        now_dt = time.gmtime(now + 3600)
        if (last_dt.tm_year == now_dt.tm_year and
                last_dt.tm_yday == now_dt.tm_yday):
            return False, "You already checked in today. Come back tomorrow! ✦", 0.0, streak

    # Check if streak continues (within 48 hours)
    if last_checkin > 0 and (now - last_checkin) < 172800:
        streak += 1
    else:
        streak = 1

    # Calculate reward (50 naira = 2 SIDI daily for free, 5 SIDI for premium)
    is_premium = check_premium_status(user)
    base_reward = DAILY_CHECKIN_PREMIUM if is_premium else DAILY_CHECKIN_FREE
    bonus = 0.0
    bonus_msg = ""

    if streak == 7:
        bonus = 10.0  # 250 naira bonus
        bonus_msg = "\n\U0001f525 7 day streak! You are committed. +10 SIDI bonus added \u2726"
    elif streak % 7 == 0 and streak > 7:
        bonus = 10.0
        bonus_msg = f"\n\U0001f525 {streak} day streak! +10 SIDI bonus \u2726"

    total_reward = base_reward + bonus

    user["sidi_balance"] = float(user.get("sidi_balance", 0)) + total_reward
    user["daily_checkin_last"] = now
    user["checkin_streak"] = streak
    save_user(telegram_id, user)

    add_transaction(telegram_id, {
        "type": "checkin",
        "amount": total_reward,
        "description": f"Daily check-in (Day {streak})",
        "timestamp": now,
        "reference": f"CHECKIN-{now}",
    })

    increment_stat("circulating_supply", total_reward)
    return True, bonus_msg, total_reward, streak


# ── Rate limiting ──────────────────────────────────────────────

def check_rate_limit(telegram_id: int | str) -> bool:
    """Check if user is within rate limit (10 tx/hour). Returns True if allowed."""
    try:
        key = _rate_key(telegram_id)
        count = redis.get(key)
        if count is None:
            redis.setex(key, 3600, "1")
            return True
        if int(count) >= 10:
            return False
        redis.incr(key)
        return True
    except Exception as e:
        logger.error(f"Rate limit check error: {e}")
        return True  # Allow on error


def increment_rate_count(telegram_id: int | str) -> None:
    """Increment the rate limit counter for a user."""
    try:
        key = _rate_key(telegram_id)
        count = redis.get(key)
        if count is None:
            redis.setex(key, 3600, "1")
        else:
            redis.incr(key)
    except Exception as e:
        logger.error(f"Rate limit increment error: {e}")


# ── Stats ──────────────────────────────────────────────────────

def increment_stat(key: str, amount: float = 1) -> None:
    """Increment a global stat."""
    try:
        redis.hincrbyfloat("stats", key, amount)
    except Exception as e:
        logger.error(f"Stat increment error for {key}: {e}")


def get_stat(key: str) -> float:
    """Get a global stat value."""
    try:
        val = redis.hget("stats", key)
        return float(val) if val else 0.0
    except Exception:
        return 0.0


def get_all_stats() -> dict:
    """Get all global stats."""
    try:
        data = redis.hgetall("stats")
        return {k: float(v) for k, v in data.items()} if data else {}
    except Exception:
        return {}


# ── Leaderboard ────────────────────────────────────────────────

def get_leaderboard(limit: int = 10) -> list[tuple[str, float]]:
    """Get top holders by balance (descending)."""
    try:
        result = redis.zrange("leaderboard", 0, limit - 1, withscores=True, rev=True)
        if result is None:
            return []
        return [(str(member), float(score)) for member, score in result]
    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        return []


def get_user_rank(telegram_id: int | str) -> int:
    """Get user's rank on leaderboard (1-indexed)."""
    try:
        rank = redis.zrevrank("leaderboard", str(telegram_id))
        return int(rank) + 1 if rank is not None else 0
    except Exception:
        return 0


# ── All users iteration ───────────────────────────────────────

def get_all_user_ids() -> list[str]:
    """Get all registered user IDs."""
    try:
        members = redis.smembers("all_users")
        if members is None:
            return []
        return [str(m) for m in members]
    except Exception as e:
        logger.error(f"Get all users error: {e}")
        return []


def _update_username_index(telegram_id: int | str, username: str) -> None:
    """Maintain a username -> telegram_id index for O(1) lookups."""
    if username:
        try:
            redis.set(f"uname_{username.lower()}", str(telegram_id))
        except Exception as e:
            logger.error(f"Username index error: {e}")


def find_user_by_username(username: str) -> Optional[dict]:
    """
    Find a user by their Telegram username.
    Uses username index for O(1) lookup, falls back to linear scan.
    """
    clean = username.lstrip("@").lower()
    if not clean:
        return None

    # Try fast index lookup first
    try:
        uid = redis.get(f"uname_{clean}")
        if uid:
            user = get_user(str(uid))
            if user and user.get("username", "").lower() == clean:
                return user
    except Exception:
        pass

    # Fallback: linear scan (updates index as it goes)
    for uid in get_all_user_ids():
        user = get_user(uid)
        if user and user.get("username", "").lower() == clean:
            _update_username_index(uid, clean)
            return user
    return None


# ── Suspicious activity detection ──────────────────────────────

def track_large_transfer(telegram_id: int | str) -> int:
    """Track large transfers. Returns count in last hour."""
    try:
        key = f"large_tx_{telegram_id}"
        count = redis.get(key)
        if count is None:
            redis.setex(key, 3600, "1")
            return 1
        new_count = int(count) + 1
        redis.incr(key)
        return new_count
    except Exception:
        return 1


# ── Bank details ───────────────────────────────────────────────

def update_bank_details(
    telegram_id: int | str,
    bank_name: str,
    bank_code: str,
    bank_account: str,
    bank_account_name: str,
) -> bool:
    """Update user's saved bank details."""
    user = get_user(telegram_id)
    if not user:
        return False
    user["bank_name"] = bank_name
    user["bank_code"] = bank_code
    user["bank_account"] = bank_account
    user["bank_account_name"] = bank_account_name
    save_user(telegram_id, user)
    return True


# ── Korapay payment tracking ──────────────────────────────────

def store_pending_payment(reference: str, data: dict) -> bool:
    """Store a pending Korapay payment for webhook matching."""
    try:
        redis.setex(f"payment_{reference}", 3600, json.dumps(data))
        return True
    except Exception as e:
        logger.error(f"Store payment error: {e}")
        return False


def get_pending_payment(reference: str) -> Optional[dict]:
    """Retrieve a pending payment by reference."""
    try:
        data = redis.get(f"payment_{reference}")
        if data is None:
            return None
        if isinstance(data, str):
            return json.loads(data)
        if isinstance(data, dict):
            return data
        return None
    except Exception as e:
        logger.error(f"Get payment error: {e}")
        return None


def delete_pending_payment(reference: str) -> bool:
    """Delete a pending payment after processing."""
    try:
        redis.delete(f"payment_{reference}")
        return True
    except Exception:
        return False


# ── Anti-fraud / Multi-account detection ───────────────────────

def generate_device_fingerprint(user_data: dict) -> str:
    """
    Generate a fingerprint from user metadata to detect multi-accounts.
    Uses: first_name + last_name pattern, language_code, user_id patterns.
    """
    import hashlib
    parts = [
        str(user_data.get("first_name", "")).lower().strip(),
        str(user_data.get("last_name", "")).lower().strip(),
        str(user_data.get("language_code", "")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def check_multi_account(telegram_id: int | str, fingerprint: str) -> dict:
    """
    Check if a fingerprint matches any existing users (multi-account detection).
    Returns: {"is_suspicious": bool, "linked_accounts": [user_ids], "reason": str}
    """
    result = {"is_suspicious": False, "linked_accounts": [], "reason": ""}

    try:
        # Check fingerprint index
        existing_ids = redis.smembers(f"fp_{fingerprint}")
        if existing_ids:
            other_ids = [str(uid) for uid in existing_ids if str(uid) != str(telegram_id)]
            if other_ids:
                result["is_suspicious"] = True
                result["linked_accounts"] = other_ids[:5]
                result["reason"] = "matching_fingerprint"

        # Register this user's fingerprint
        redis.sadd(f"fp_{fingerprint}", str(telegram_id))
    except Exception as e:
        logger.error(f"Multi-account check error: {e}")

    return result


def flag_suspicious_account(telegram_id: int | str, linked_ids: list, reason: str) -> bool:
    """Flag an account as suspicious multi-account."""
    user = get_user(telegram_id)
    if not user:
        return False
    user["flagged_multi_account"] = True
    user["linked_accounts"] = linked_ids[:5]
    save_user(telegram_id, user)
    return True


def is_account_flagged(telegram_id: int | str) -> bool:
    """Check if an account is flagged for multi-account abuse."""
    user = get_user(telegram_id)
    if not user:
        return False
    return bool(user.get("flagged_multi_account", False))


def check_withdrawal_locks(telegram_id: int | str) -> dict:
    """
    Check all withdrawal locks for a user.
    Returns: {"can_withdraw": bool, "reason": str, "remaining_secs": int}
    """
    user = get_user(telegram_id)
    if not user:
        return {"can_withdraw": False, "reason": "User not found", "remaining_secs": 0}

    now = int(time.time())

    # Check multi-account flag
    if user.get("flagged_multi_account"):
        return {
            "can_withdraw": False,
            "reason": "Account flagged for security review. Contact support.",
            "remaining_secs": 0,
        }

    # Check banned status
    if user.get("is_banned"):
        return {
            "can_withdraw": False,
            "reason": "Account suspended.",
            "remaining_secs": 0,
        }

    # Check welcome bonus hold (2 days)
    welcome_hold = int(user.get("welcome_bonus_hold_until", 0))
    if welcome_hold > now:
        return {
            "can_withdraw": False,
            "reason": "welcome_hold",
            "remaining_secs": welcome_hold - now,
        }

    # Check general cashout hold
    cashout_hold = int(user.get("cashout_hold_until", 0))
    if cashout_hold > now:
        return {
            "can_withdraw": False,
            "reason": "cashout_hold",
            "remaining_secs": cashout_hold - now,
        }

    return {"can_withdraw": True, "reason": "", "remaining_secs": 0}
