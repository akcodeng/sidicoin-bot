"""
Input validation utilities for Sidicoin bot.
"""

import re
import os
from difflib import SequenceMatcher

SIDI_PRICE_NGN = float(os.getenv("SIDI_PRICE_NGN", "25"))
FREE_DAILY_LIMIT = 50_000
PREMIUM_DAILY_LIMIT = 500_000
LARGE_TRANSFER_THRESHOLD = 10_000
RATE_LIMIT_PER_HOUR = 10


def is_valid_username(username: str) -> bool:
    """Check if a string is a valid Telegram username (with or without @)."""
    clean = username.lstrip("@")
    if len(clean) < 3 or len(clean) > 32:
        return False
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9_]{2,31}$", clean))


def clean_username(username: str) -> str:
    """Remove @ prefix and lowercase a username."""
    return username.lstrip("@").lower()


def is_valid_amount(text: str) -> tuple[bool, float]:
    """
    Parse and validate an amount string.
    Accepts: '500', '500 SIDI', '₦12500', '12500 NGN'.
    Returns (is_valid, sidi_amount).
    """
    text = text.strip().upper()

    # Handle NGN/₦ prefixed amounts
    ngn_match = re.match(r"[₦N]?\s*([0-9,]+(?:\.\d{1,2})?)\s*(?:NGN|NAIRA)?$", text)
    if ngn_match:
        try:
            naira = float(ngn_match.group(1).replace(",", ""))
            if naira <= 0:
                return False, 0.0
            sidi = naira / SIDI_PRICE_NGN
            return True, sidi
        except ValueError:
            return False, 0.0

    # Handle SIDI amounts
    sidi_match = re.match(r"([0-9,]+(?:\.\d{1,2})?)\s*(?:SIDI)?$", text)
    if sidi_match:
        try:
            amount = float(sidi_match.group(1).replace(",", ""))
            if amount <= 0:
                return False, 0.0
            return True, amount
        except ValueError:
            return False, 0.0

    return False, 0.0


def check_daily_limit(
    daily_tx_total: float, amount: float, is_premium: bool
) -> tuple[bool, float]:
    """
    Check if a transfer is within daily limits.
    Returns (within_limit, remaining).
    """
    limit = PREMIUM_DAILY_LIMIT if is_premium else FREE_DAILY_LIMIT
    remaining = limit - daily_tx_total
    if amount > remaining:
        return False, remaining
    return True, remaining - amount


def is_large_transfer(amount: float) -> bool:
    """Check if a transfer amount exceeds the large transfer threshold."""
    return amount > LARGE_TRANSFER_THRESHOLD


def find_similar_usernames(target: str, known_usernames: list[str], threshold: float = 0.6) -> list[str]:
    """Find usernames similar to the target for typo detection."""
    target_clean = clean_username(target)
    similar = []
    for uname in known_usernames:
        uname_clean = clean_username(uname)
        ratio = SequenceMatcher(None, target_clean, uname_clean).ratio()
        if ratio >= threshold and target_clean != uname_clean:
            similar.append(uname)
    return similar[:3]


def calculate_fee(amount_sidi: float, is_premium: bool, tx_type: str = "buy") -> float:
    """
    Calculate fee in SIDI.
    Buy/Sell: 1.5% free, 0.8% premium.
    Send local: 0% always (premium), 0% (free local).
    Send cross-border: 0.5% free, 0% premium.
    """
    if tx_type == "send":
        return 0.0
    elif tx_type == "send_cross":
        if is_premium:
            return 0.0
        return amount_sidi * 0.005
    elif tx_type in ("buy", "sell"):
        rate = 0.008 if is_premium else 0.015
        return amount_sidi * rate
    return 0.0


def calculate_fee_naira(amount_naira: float, is_premium: bool, tx_type: str = "buy") -> float:
    """Calculate fee in NGN for buy/sell operations."""
    if tx_type in ("buy", "sell"):
        rate = 0.008 if is_premium else 0.015
        return amount_naira * rate
    return 0.0


def is_valid_bank_account(account_number: str) -> bool:
    """Validate Nigerian bank account number (10 digits)."""
    return bool(re.match(r"^\d{10}$", account_number.strip()))


def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent injection."""
    # Remove any HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Limit length
    return text[:500].strip()
