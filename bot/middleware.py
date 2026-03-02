"""
Aiogram middleware for ban checking, rate limiting, and activity tracking.
Runs before every message and callback query handler.
"""

import time
import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from services.redis import get_user, check_rate_limit, save_user

logger = logging.getLogger("sidicoin.middleware")


class BanCheckMiddleware(BaseMiddleware):
    """Check if user is banned before processing any command."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            user = get_user(user_id)
            if user and user.get("is_banned"):
                ban_text = "Your account has been suspended. Contact support ✦"
                if isinstance(event, Message):
                    await event.answer(ban_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(ban_text, show_alert=True)
                return  # Stop processing

            # Update last_active timestamp (avoid saving on every single event
            # to reduce Redis calls -- only update if stale by > 5 minutes)
            if user:
                last_active = int(user.get("last_active", 0))
                now = int(time.time())
                if now - last_active > 300:
                    user["last_active"] = now
                    save_user(user_id, user)

        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Rate limit: 10 transactions per hour per user."""

    # Commands and callback actions that count as transactions
    TX_COMMANDS = ("/send", "/buy", "/sell")
    TX_CALLBACKS = (
        "send_confirm", "buy_proceed", "sell_confirm",
        "premium_upgrade",
        "escrow_fund_", "merchant_pay_",
    )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        should_limit = False

        if isinstance(event, Message) and event.text and event.from_user:
            text_lower = event.text.lower().strip()
            should_limit = any(text_lower.startswith(cmd) for cmd in self.TX_COMMANDS)

        elif isinstance(event, CallbackQuery) and event.from_user and event.data:
            should_limit = any(
                event.data == cb or event.data.startswith(cb)
                for cb in self.TX_CALLBACKS
            )

        if should_limit:
            user_id = event.from_user.id
            if not check_rate_limit(user_id):
                limit_text = (
                    "You've reached the transaction limit (10/hour). "
                    "Please wait a bit before trying again ✦"
                )
                if isinstance(event, Message):
                    await event.answer(limit_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(limit_text, show_alert=True)
                return

        return await handler(event, data)
