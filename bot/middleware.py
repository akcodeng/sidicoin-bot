"""
Aiogram middleware for ban checking and rate limiting.
Runs before every message and callback query handler.
"""

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from services.redis import get_user, check_rate_limit

logger = logging.getLogger("sidicoin.middleware")


class BanCheckMiddleware(BaseMiddleware):
    """Check if user is banned before processing any command."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract user ID from either Message or CallbackQuery
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

        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Rate limit: 10 transactions per hour per user."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Only rate-limit actual transaction commands, not all messages
        if isinstance(event, Message) and event.text:
            tx_commands = ["/send", "/buy", "/sell"]
            text_lower = event.text.lower().strip()
            is_tx = any(text_lower.startswith(cmd) for cmd in tx_commands)
            if is_tx and event.from_user:
                if not check_rate_limit(event.from_user.id):
                    await event.answer(
                        "⚠️ You've reached the transaction limit (10/hour). "
                        "Please wait a bit before trying again ✦"
                    )
                    return

        return await handler(event, data)
