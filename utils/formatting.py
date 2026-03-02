"""
Formatting utilities for Sidicoin bot messages.
All messages use Telegram HTML parse mode.
"""

import os
from datetime import datetime, timezone, timedelta

WAT = timezone(timedelta(hours=1))
SIDI_PRICE_NGN = float(os.getenv("SIDI_PRICE_NGN", "25"))


def fmt_number(n) -> str:
    """Format a number with commas: 1000 -> 1,000."""
    try:
        num = float(n)
        if num == int(num):
            return f"{int(num):,}"
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return str(n)


def sidi_to_naira(sidi_amount: float) -> float:
    """Convert SIDI amount to NGN."""
    return sidi_amount * SIDI_PRICE_NGN


def naira_to_sidi(naira_amount: float) -> float:
    """Convert NGN amount to SIDI."""
    return naira_amount / SIDI_PRICE_NGN


def fmt_sidi(amount: float) -> str:
    """Format SIDI amount with naira equivalent: '500 SIDI (₦12,500)'."""
    naira = sidi_to_naira(amount)
    return f"{fmt_number(amount)} SIDI (₦{fmt_number(naira)})"


def fmt_naira(amount: float) -> str:
    """Format naira amount: '₦12,500'."""
    return f"₦{fmt_number(amount)}"


def fmt_timestamp(ts=None) -> str:
    """Format a timestamp to human-readable WAT string."""
    if ts is None:
        dt = datetime.now(WAT)
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=WAT)
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=WAT)
        except ValueError:
            return ts
    elif isinstance(ts, datetime):
        dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=WAT)
    else:
        return str(ts)
    return dt.strftime("%b %d, %Y %I:%M %p WAT")


def fmt_date(ts=None) -> str:
    """Format a timestamp to date only."""
    if ts is None:
        dt = datetime.now(WAT)
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=WAT)
    else:
        dt = datetime.now(WAT)
    return dt.strftime("%b %d, %Y")


def time_greeting(name: str) -> str:
    """Return time-of-day greeting in WAT (UTC+1)."""
    hour = datetime.now(WAT).hour
    if 5 <= hour < 12:
        return f"Good morning, {name} ☀️"
    elif 12 <= hour < 17:
        return f"Good afternoon, {name} 👋"
    elif 17 <= hour < 21:
        return f"Good evening, {name} 🌆"
    else:
        return f"Hey {name}, up late? 🌙"


def generate_receipt(
    tx_type: str,
    sender: str,
    recipient: str,
    sidi_amount: float,
    fee: float,
    reference: str,
    status: str = "✅ Confirmed",
) -> str:
    """Generate a formatted transaction receipt."""
    naira = sidi_to_naira(sidi_amount)
    timestamp = fmt_timestamp()
    return (
        f"━━━━━━━━━━━━━━━\n"
        f"✦ SIDICOIN RECEIPT\n"
        f"Type: {tx_type}\n"
        f"From: @{sender}\n"
        f"To: @{recipient}\n"
        f"Amount: <b>{fmt_number(sidi_amount)} SIDI</b>\n"
        f"Value: {fmt_naira(naira)}\n"
        f"Fee: {fmt_naira(fee)}\n"
        f"Status: {status}\n"
        f"Time: {timestamp}\n"
        f"Ref: <code>{reference}</code>\n"
        f"━━━━━━━━━━━━━━━\n"
        f'<a href="https://coin.sidihost.sbs">coin.sidihost.sbs</a> ✦'
    )


def generate_tx_reference() -> str:
    """Generate a unique transaction reference."""
    import uuid
    short = uuid.uuid4().hex[:12].upper()
    return f"SIDI-{short}"


DIVIDER = "━━━━━━━━━━━━━━━"
