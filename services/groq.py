"""
Groq AI conversational assistant service.
Uses llama-3.3-70b-versatile for intelligent, context-aware responses.
Supports real-time streaming via Telegram editMessageText.
"""

import os
import logging
import asyncio
import time
from functools import partial

from groq import Groq

logger = logging.getLogger("sidicoin.groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_sync_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Minimum interval between edits (Telegram rate limit: ~1 edit/sec)
STREAM_EDIT_INTERVAL = 1.0
# Typing cursor shown during streaming
STREAM_CURSOR = " \u25cf"

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


GROUP_SYSTEM_PROMPT = (
    "You are Sidi, the AI assistant for Sidicoin -- a digital money platform on Telegram. "
    "You are in a GROUP CHAT. Be concise and helpful. "
    "Max 2 sentences. Don't be spammy. "
    "SIDI is digital money (like mobile money), not crypto. "
    "Group commands: /tip @user amount, /giveaway amount winners, /rain amount, "
    "/verify, /whois @user, /pick. "
    "Private commands: /send, /buy, /sell, /balance, /escrow, /game. "
    "Be warm, smart, and helpful. Use simple language."
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


def _sync_stream(messages: list[dict]):
    """Synchronous Groq streaming call -- yields token chunks."""
    stream = _sync_client.chat.completions.create(
        messages=messages,
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=300,
        top_p=0.9,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def stream_ai_response(message, user_message: str, user_name: str = "User",
                              suffix: str = "", reply_markup=None,
                              group_mode: bool = False):
    """
    Stream an AI response in real time by editing the Telegram message.

    1. Sends initial "thinking..." placeholder
    2. Streams tokens from Groq
    3. Edits the message every ~1 second with accumulated text + cursor
    4. Final edit removes cursor and adds suffix/keyboard

    Args:
        message: aiogram Message object (the loading message to edit)
        user_message: The user's question
        user_name: Display name for context
        suffix: Optional text to append after the AI response (e.g. intent hint)
        reply_markup: Keyboard to attach to the final message
        group_mode: Use shorter group-aware prompt
    """
    from aiogram.exceptions import TelegramBadRequest

    if not _sync_client:
        fallback = (
            "I'm Sidi, your Sidicoin assistant! \u2726 "
            "Try /help to see all available commands, "
            "or /send to transfer money to someone."
        )
        final_text = f"{fallback}\n\n{suffix}" if suffix else fallback
        try:
            await message.edit_text(final_text, reply_markup=reply_markup)
        except TelegramBadRequest:
            pass
        return

    prompt = GROUP_SYSTEM_PROMPT if group_mode else SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"[User: {user_name}] {user_message}"},
    ]

    accumulated = ""
    last_edit_time = 0.0
    last_edit_text = ""

    try:
        loop = asyncio.get_event_loop()

        # Run the sync stream generator in a thread, collecting chunks via a queue
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def _producer():
            try:
                for token in _sync_stream(messages):
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            except Exception as e:
                logger.error(f"Groq stream error: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        asyncio.get_event_loop().run_in_executor(None, _producer)

        while True:
            token = await queue.get()
            if token is sentinel:
                break

            accumulated += token
            now = time.monotonic()

            # Edit at most once per STREAM_EDIT_INTERVAL
            if now - last_edit_time >= STREAM_EDIT_INTERVAL:
                display_text = accumulated.strip() + STREAM_CURSOR
                if display_text != last_edit_text and len(display_text) > 2:
                    try:
                        await message.edit_text(display_text)
                        last_edit_text = display_text
                        last_edit_time = now
                    except TelegramBadRequest:
                        pass
                    except Exception as e:
                        logger.debug(f"Stream edit error: {e}")

    except Exception as e:
        logger.error(f"Streaming error: {e}", exc_info=True)
        if not accumulated:
            accumulated = (
                "I'm having a moment -- please try again shortly! "
                "In the meantime, try /help for all commands \u2726"
            )

    # Final edit: remove cursor, add suffix and keyboard
    final_text = accumulated.strip()
    if suffix:
        final_text = f"{final_text}\n\n{suffix}"
    if not final_text:
        final_text = "I'm here to help! Try /help \u2726"

    try:
        await message.edit_text(final_text, reply_markup=reply_markup)
    except TelegramBadRequest:
        pass


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
