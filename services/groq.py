"""
Groq AI conversational assistant service.
Uses llama-3.3-70b-versatile for intelligent, context-aware responses.
Uses AsyncGroq to avoid blocking the event loop in production.
"""

import os
import logging
import asyncio
from functools import partial

from groq import Groq

logger = logging.getLogger("sidicoin.groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Use sync client but run in thread executor to avoid blocking
_sync_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_PROMPT = (
    "You are Sidi, the intelligent assistant for Sidicoin -- the digital money "
    "transfer platform on Telegram. Sidicoin lets anyone send, receive, and "
    "manage money instantly using just a Telegram username. "
    "Personality: warm, smart and proudly African, going global. "
    "Use simple everyday language. Never use the word 'cryptocurrency' or 'crypto'. "
    "SIDI is a digital balance, like airtime credit or mobile money. "
    "Always helpful and encouraging. "
    "Guide users to relevant commands. "
    "Max 3 sentences per reply. "
    "Use \u2726 occasionally. "
    "Never bash competitors. "
    "Help users with: sending and receiving money, understanding SIDI, "
    "navigating bot features, troubleshooting payments, encouraging referrals, "
    "escrow trades, and supporting the platform. "
    "\n\nKey commands you can suggest:\n"
    "/send @username amount -- Send SIDI\n"
    "/buy -- Buy SIDI (zero fees)\n"
    "/sell -- Cash out SIDI to bank (zero fees)\n"
    "/balance -- Check wallet\n"
    "/escrow -- Safe P2P trades\n"
    "/refer -- Earn free SIDI\n"
    "/checkin -- Monthly check-in (up to 44 SIDI)\n"
    "/support -- Help keep Sidicoin free\n"
    "/help -- All commands\n"
    "\nSidicoin facts:\n"
    "- 1 SIDI = \u20a625 (stable digital currency, not volatile)\n"
    "- Zero fees on all transfers, buy, and sell\n"
    "- Works in 13+ countries (Nigeria, Kenya, Ghana, South Africa, etc.)\n"
    "- Escrow system for safe P2P trading\n"
    "- Telegram OTP verification for security\n"
    "- Available to anyone with Telegram worldwide\n"
    "- Website: coin.sidihost.sbs"
)


def _sync_chat(messages: list[dict]) -> str:
    """Synchronous Groq API call (runs in thread executor)."""
    chat_completion = _sync_client.chat.completions.create(
        messages=messages,
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=300,
        top_p=0.9,
    )
    response = chat_completion.choices[0].message.content
    return response.strip() if response else "I'm here to help! Try /help to see what I can do ✦"


async def get_ai_response(user_message: str, user_name: str = "User") -> str:
    """
    Get an AI response from Groq for non-command messages.
    Runs the sync Groq client in a thread executor to avoid blocking.
    Includes 3-retry logic with exponential backoff.
    """
    if not _sync_client:
        return (
            "I'm Sidi, your Sidicoin assistant! ✦ "
            "Try /help to see all available commands, "
            "or /send to transfer money to someone."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[User: {user_name}] {user_message}"},
    ]

    for attempt in range(3):
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, partial(_sync_chat, messages))
            return response
        except Exception as e:
            logger.error(f"Groq API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

    return (
        "I'm having a moment — please try again shortly! "
        "In the meantime, try /help for all commands ✦"
    )


def detect_intent(message: str) -> str:
    """
    Detect user intent from natural language for smart routing.
    Returns a command suggestion or empty string.
    Uses keyword matching first for speed, no API call needed.
    """
    msg = message.lower().strip()

    # Transfer intent
    send_keywords = [
        "send money", "send to", "transfer", "pay", "give money", "send sidi",
        "send coin", "send some", "want to send", "how to send",
    ]
    if any(kw in msg for kw in send_keywords):
        return "/send"

    # Buy intent
    buy_keywords = [
        "buy", "purchase", "get sidi", "top up", "fund", "add money",
        "deposit", "want sidi", "need sidi", "how to buy",
    ]
    if any(kw in msg for kw in buy_keywords):
        return "/buy"

    # Sell intent
    sell_keywords = [
        "sell", "cash out", "cashout", "withdraw", "payout", "bank",
        "convert to naira", "get naira", "need cash", "how to sell",
    ]
    if any(kw in msg for kw in sell_keywords):
        return "/sell"

    # Balance intent
    balance_keywords = [
        "balance", "wallet", "how much", "my money", "check balance",
        "what do i have", "my sidi", "my coin",
    ]
    if any(kw in msg for kw in balance_keywords):
        return "/balance"

    # Referral intent
    refer_keywords = [
        "refer", "referral", "invite", "earn", "share link",
        "how to earn", "free sidi", "invite friend",
    ]
    if any(kw in msg for kw in refer_keywords):
        return "/refer"

    # Help intent
    help_keywords = ["help", "commands", "what can", "how to", "how do", "guide"]
    if any(kw in msg for kw in help_keywords):
        return "/help"

    # Price/stats
    price_keywords = ["price", "how much is", "sidi worth", "exchange rate", "rate"]
    if any(kw in msg for kw in price_keywords):
        return "/price"

    # Check-in
    checkin_keywords = ["checkin", "check in", "daily", "reward", "claim", "free money"]
    if any(kw in msg for kw in checkin_keywords):
        return "/checkin"

    # Settings
    settings_keywords = ["settings", "my account", "profile", "bank details", "update bank"]
    if any(kw in msg for kw in settings_keywords):
        return "/settings"

    # Premium
    premium_keywords = ["premium", "upgrade", "vip", "lower fees", "higher limit"]
    if any(kw in msg for kw in premium_keywords):
        return "/premium"

    # Escrow
    escrow_keywords = ["escrow", "safe trade", "p2p", "protect", "scam", "dispute"]
    if any(kw in msg for kw in escrow_keywords):
        return "/escrow"

    # Support
    support_keywords = ["donate", "support", "contribute", "tip"]
    if any(kw in msg for kw in support_keywords):
        return "/support"

    return ""
