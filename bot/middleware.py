"""
Aiogram middleware for ban checking, rate limiting, and activity tracking.
Runs before every message and callback query handler.
Optimized for both private chats and group chats.
"""

import time
import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.enums import ChatType

from services.redis import get_user, check_rate_limit, save_user

logger = logging.getLogger("sidicoin.middleware")

# Group chat types
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


def _is_group(event: TelegramObject) -> bool:
    """Check if the event is from a group/supergroup."""
    if isinstance(event, Message):
        return event.chat.type in _GROUP_TYPES
    elif isinstance(event, CallbackQuery) and event.message:
        return event.message.chat.type in _GROUP_TYPES
    return False


class BanCheckMiddleware(BaseMiddleware):
    """
    Check if user is banned before processing any command.
    Optimized: in groups, only checks ban status (no last_active update)
    to minimize Redis calls on high-traffic group chats.
    """

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
            is_group = _is_group(event)

            # In groups, only check ban for commands/callbacks that move money
            # (tip, giveaway, rain). Skip the Redis call for plain messages.
            if is_group and isinstance(event, Message):
                text = (event.text or "").strip().lower()
                is_transactional = text.startswith(("/tip", "/giveaway", "/rain"))
                if not is_transactional:
                    # Let it through without ban check -- the group activity
                    # tracker in group_commands.py handles tracking cheaply
                    return await handler(event, data)

            user = get_user(user_id)
            if user and user.get("is_banned"):
                ban_text = "Your account has been suspended. Contact support."
                if isinstance(event, Message):
                    await event.answer(ban_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(ban_text, show_alert=True)
                return  # Stop processing

            # Update last_active only in private chats and only if stale (>5 min)
            if user and not is_group:
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

    # Group-specific transactional commands
    GROUP_TX_COMMANDS = ("/tip", "/giveaway", "/rain")

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
            if not should_limit and _is_group(event):
                should_limit = any(
                    text_lower.startswith(cmd) for cmd in self.GROUP_TX_COMMANDS
                )

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
                    "Please wait a bit before trying again."
                )
                if isinstance(event, Message):
                    await event.answer(limit_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(limit_text, show_alert=True)
                return

        return await handler(event, data)
