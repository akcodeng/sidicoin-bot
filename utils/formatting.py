"""
Formatting utilities for SidiApp bot messages.
All messages use Telegram HTML parse mode.
Beautiful, branded, consistent formatting throughout.
"""

import os
from datetime import datetime, timezone, timedelta

WAT = timezone(timedelta(hours=1))
SIDI_PRICE_NGN = float(os.getenv("SIDI_PRICE_NGN", "25"))
USD_RATE = 1600.0  # NGN/USD approximate


# =====================================================================
#  NUMBER / CURRENCY FORMATTING
# =====================================================================

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
    return round(sidi_amount * SIDI_PRICE_NGN, 2)


def naira_to_sidi(naira_amount: float) -> float:
    """Convert NGN amount to SIDI."""
    return round(naira_amount / SIDI_PRICE_NGN, 2)


def sidi_to_usd(sidi_amount: float) -> float:
    """Convert SIDI to approximate USD."""
    return round(sidi_to_naira(sidi_amount) / USD_RATE, 6)


def fmt_sidi(amount: float) -> str:
    """Format SIDI with naira equivalent: '500 SIDI (~₦12,500)'."""
    naira = sidi_to_naira(amount)
    return f"{fmt_number(amount)} SIDI (~{fmt_naira(naira)})"


def fmt_naira(amount: float) -> str:
    """Format naira: '₦12,500'."""
    return f"\u20a6{fmt_number(amount)}"


def fmt_usd(amount: float) -> str:
    """Format USD: '$7.81'."""
    return f"${amount:,.2f}" if amount >= 0.01 else f"${amount:,.6f}"


# =====================================================================
#  TIME / DATE FORMATTING
# =====================================================================

def fmt_timestamp(ts=None) -> str:
    """Format a timestamp to human-readable WAT string."""
    if ts is None:
        dt = datetime.now(WAT)
    elif isinstance(ts, (int, float)):
        if ts == 0:
            return "N/A"
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
    return dt.strftime("%b %d, %Y at %I:%M %p WAT")


def fmt_date(ts=None) -> str:
    """Format a timestamp to date only."""
    if ts is None:
        dt = datetime.now(WAT)
    elif isinstance(ts, (int, float)):
        if ts == 0:
            return "N/A"
        dt = datetime.fromtimestamp(ts, tz=WAT)
    else:
        dt = datetime.now(WAT)
    return dt.strftime("%b %d, %Y")


def fmt_relative_time(ts: int) -> str:
    """Format a timestamp as relative time: '2 hours ago', 'just now'."""
    now = int(datetime.now(WAT).timestamp())
    diff = now - ts
    if diff < 60:
        return "just now"
    elif diff < 3600:
        m = diff // 60
        return f"{m} min{'s' if m > 1 else ''} ago"
    elif diff < 86400:
        h = diff // 3600
        return f"{h} hour{'s' if h > 1 else ''} ago"
    elif diff < 604800:
        d = diff // 86400
        return f"{d} day{'s' if d > 1 else ''} ago"
    else:
        return fmt_date(ts)


def time_greeting(name: str) -> str:
    """Return time-of-day greeting in WAT (UTC+1)."""
    hour = datetime.now(WAT).hour
    if 5 <= hour < 12:
        return f"Good morning, {name}"
    elif 12 <= hour < 17:
        return f"Good afternoon, {name}"
    elif 17 <= hour < 21:
        return f"Good evening, {name}"
    else:
        return f"Hey {name}, burning the midnight oil?"


# =====================================================================
#  DIVIDERS AND BRAND ELEMENTS
# =====================================================================

DIVIDER = "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
THIN_DIVIDER = "\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508"
BRAND = '<a href="https://coin.sidihost.sbs">coin.sidihost.sbs</a>'
STAR = "\u2726"  # ✦


# =====================================================================
#  RECEIPT GENERATOR
# =====================================================================

def generate_receipt(
    tx_type: str,
    sender: str,
    recipient: str,
    sidi_amount: float,
    fee: float,
    reference: str,
    status: str = "Confirmed",
) -> str:
    """Generate a beautifully formatted transaction receipt."""
    naira = sidi_to_naira(sidi_amount)
    timestamp = fmt_timestamp()

    # Build direction-aware labels
    if tx_type.lower() in ("transfer", "send"):
        icon = "\U0001f4e4"  # 📤
        direction = "Sent"
    elif tx_type.lower() in ("receive", "received"):
        icon = "\U0001f4e5"  # 📥
        direction = "Received"
    elif tx_type.lower() == "buy":
        icon = "\U0001f4b3"  # 💳
        direction = "Purchase"
    elif tx_type.lower() in ("sell", "cashout"):
        icon = "\U0001f4b0"  # 💰
        direction = "Cashout"
    else:
        icon = "\U0001f4cb"  # 📋
        direction = tx_type

    fee_line = f"Free \u2705" if fee == 0 else fmt_naira(fee)

    return (
        f"\n{DIVIDER}\n"
        f"     {STAR} <b>SIDICOIN RECEIPT</b> {STAR}\n"
        f"{DIVIDER}\n\n"
        f"  {icon} <b>{direction}</b>\n\n"
        f"  From     @{sender}\n"
        f"  To       @{recipient}\n"
        f"  Amount   <b>{fmt_number(sidi_amount)} SIDI</b>\n"
        f"  Value    {fmt_naira(naira)}\n"
        f"  Fee      {fee_line}\n"
        f"  Status   \u2705 {status}\n"
        f"  Time     {timestamp}\n"
        f"  Ref      <code>{reference}</code>\n\n"
        f"{DIVIDER}\n"
        f"  {BRAND} {STAR}\n"
        f"{DIVIDER}"
    )


def generate_mini_receipt(tx_type: str, amount: float, ref: str) -> str:
    """Compact receipt for inline display."""
    naira = sidi_to_naira(amount)
    return (
        f"{STAR} <b>{tx_type}</b> | "
        f"<b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)}) | "
        f"Ref: <code>{ref}</code>"
    )


def generate_downloadable_receipt(
    tx_type: str,
    sender: str,
    recipient: str,
    sidi_amount: float,
    fee: float,
    reference: str,
    bank_info: str = "",
    status: str = "Confirmed",
) -> str:
    """
    Generate a plain-text receipt for file download.
    This is a .txt that users can save/share outside Telegram.
    """
    naira = sidi_to_naira(sidi_amount)
    timestamp = fmt_timestamp()
    fee_str = "Free" if fee == 0 else f"N{fmt_number(fee)}"
    naira_str = f"N{fmt_number(naira)}"

    lines = [
        "",
        "  ================================================",
        "       SIDICOIN - TRANSACTION RECEIPT",
        "  ================================================",
        "",
        f"  Type:        {tx_type}",
        f"  From:        @{sender}",
        f"  To:          @{recipient}",
        f"  Amount:      {fmt_number(sidi_amount)} SIDI",
        f"  Value:       {naira_str}",
        f"  Fee:         {fee_str}",
    ]

    if bank_info:
        lines.append(f"  Bank:        {bank_info}")

    lines.extend([
        f"  Status:      {status}",
        f"  Date:        {timestamp}",
        f"  Reference:   {reference}",
        "",
        "  ================================================",
        "  SidiApp - Instant money transfers across Africa",
        "  https://coin.sidihost.sbs",
        "  ================================================",
        "",
    ])

    return "\n".join(lines)


# =====================================================================
#  REFERENCE GENERATOR
# =====================================================================

def generate_tx_reference() -> str:
    """Generate a unique 16+ char transaction reference (Korapay needs 8+)."""
    import uuid
    short = uuid.uuid4().hex[:12].upper()
    return f"SIDI-{short}"


# =====================================================================
#  PROGRESS BAR
# =====================================================================

def progress_bar(current: float, total: float, width: int = 10) -> str:
    """Generate a text-based progress bar."""
    if total <= 0:
        pct = 0.0
    else:
        pct = min(current / total, 1.0)
    filled = int(pct * width)
    empty = width - filled
    bar = "\u2588" * filled + "\u2591" * empty
    return f"{bar} {pct * 100:.0f}%"


def streak_fire(streak: int) -> str:
    """Generate streak indicator with fire icons."""
    if streak <= 0:
        return ""
    fires = min(streak, 7)
    return "\U0001f525" * fires + (f" x{streak}" if streak > 7 else "")
