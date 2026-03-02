"""
Groq AI conversational assistant service.
Uses llama-3.3-70b-versatile for intelligent, context-aware responses.
"""

import os
import logging
from groq import Groq

logger = logging.getLogger("sidicoin.groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYSTEM_PROMPT = (
    "You are Sidi, the intelligent assistant for Sidicoin — Africa's premier "
    "crypto payment platform on Telegram. "
    "Personality: warm, smart and proudly African. "
    "Use simple language for non-crypto users. "
    "Always helpful and encouraging. "
    "Guide users to relevant commands. "
    "Max 3 sentences per reply. "
    "Use ✦ occasionally. "
    "Never bash competitors. "
    "Proud that Sidicoin is built for Africa. "
    "Help users with: sending and receiving money, explaining crypto simply, "
    "navigating bot features, troubleshooting payments, encouraging referrals. "
    "\n\nKey commands you can suggest:\n"
    "/send @username amount — Send SIDI\n"
    "/buy — Buy SIDI with Naira\n"
    "/sell — Cash out SIDI to bank\n"
    "/balance — Check wallet\n"
    "/refer — Earn free SIDI\n"
    "/checkin — Daily reward\n"
    "/help — All commands\n"
    "\nSidicoin facts:\n"
    "- 1 SIDI = ₦25\n"
    "- Built on TON blockchain\n"
    "- Welcome bonus: 80 SIDI (₦2,000)\n"
    "- Referral bonus: 50 SIDI per signup\n"
    "- Free transfers between users\n"
    "- Available to anyone with Telegram\n"
    "- Website: coin.sidihost.sbs"
)


async def get_ai_response(user_message: str, user_name: str = "User") -> str:
    """
    Get an AI response from Groq for non-command messages.
    Detects user intent and provides helpful guidance.
    """
    if not client:
        return (
            "I'm Sidi, your Sidicoin assistant! ✦ "
            "Try /help to see all available commands, "
            "or /send to transfer money to someone."
        )

    try:
        # Build messages with user context
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"[User: {user_name}] {user_message}",
            },
        ]

        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=300,
            top_p=0.9,
        )

        response = chat_completion.choices[0].message.content
        return response.strip() if response else "I'm here to help! Try /help to see what I can do ✦"

    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return (
            "I'm having a moment — please try again shortly! "
            "In the meantime, try /help for all commands ✦"
        )


def detect_intent(message: str) -> str:
    """
    Detect user intent from natural language for smart routing.
    Returns a command suggestion or empty string.
    """
    msg = message.lower().strip()

    # Transfer intent
    send_keywords = ["send money", "send to", "transfer", "pay", "give money", "send sidi"]
    if any(kw in msg for kw in send_keywords):
        return "/send"

    # Buy intent
    buy_keywords = ["buy", "purchase", "get sidi", "top up", "fund", "add money", "deposit"]
    if any(kw in msg for kw in buy_keywords):
        return "/buy"

    # Sell intent
    sell_keywords = ["sell", "cash out", "cashout", "withdraw", "payout", "bank"]
    if any(kw in msg for kw in sell_keywords):
        return "/sell"

    # Balance intent
    balance_keywords = ["balance", "wallet", "how much", "my money", "check balance"]
    if any(kw in msg for kw in balance_keywords):
        return "/balance"

    # Referral intent
    refer_keywords = ["refer", "referral", "invite", "earn", "share link"]
    if any(kw in msg for kw in refer_keywords):
        return "/refer"

    # Help intent
    help_keywords = ["help", "commands", "what can", "how to", "how do"]
    if any(kw in msg for kw in help_keywords):
        return "/help"

    # Price/stats
    price_keywords = ["price", "how much is", "sidi worth", "exchange rate"]
    if any(kw in msg for kw in price_keywords):
        return "/price"

    # Check-in
    checkin_keywords = ["checkin", "check in", "daily", "reward", "claim"]
    if any(kw in msg for kw in checkin_keywords):
        return "/checkin"

    return ""
