"""
Input validation utilities for SidiApp bot.
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
    Accepts: '500', '500 SIDI', '₦12500', '12500 NGN', 'N5000', '5k', '5K SIDI'.
    Returns (is_valid, sidi_amount).
    """
    text = text.strip().upper()

    # Handle shorthand multipliers: 5K -> 5000, 2.5K -> 2500
    text = re.sub(r"(\d+(?:\.\d+)?)\s*K\b", lambda m: str(float(m.group(1)) * 1000), text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*M\b", lambda m: str(float(m.group(1)) * 1_000_000), text)

    # Handle NGN/₦ prefixed amounts
    ngn_match = re.match(r"[₦N]?\s*([0-9,]+(?:\.\d{1,2})?)\s*(?:NGN|NAIRA)?$", text)
    if ngn_match:
        try:
            naira = float(ngn_match.group(1).replace(",", ""))
            if naira <= 0:
                return False, 0.0
            if naira > 100_000_000:  # Sanity check: 100M NGN max
                return False, 0.0
            sidi = naira / SIDI_PRICE_NGN
            return True, round(sidi, 2)
        except ValueError:
            return False, 0.0

    # Handle SIDI amounts
    sidi_match = re.match(r"([0-9,]+(?:\.\d{1,2})?)\s*(?:SIDI|COIN)?$", text)
    if sidi_match:
        try:
            amount = float(sidi_match.group(1).replace(",", ""))
            if amount <= 0:
                return False, 0.0
            if amount > 10_000_000_000:  # Cannot exceed total supply
                return False, 0.0
            return True, round(amount, 2)
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
    SidiApp charges ZERO fees on all operations.
    """
    return 0.0


def calculate_fee_naira(amount_naira: float, is_premium: bool, tx_type: str = "buy") -> float:
    """Calculate fee in NGN. SidiApp charges ZERO fees."""
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
