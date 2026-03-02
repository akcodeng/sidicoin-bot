"""
Bot handler registration module.
Registers all command handlers, callback handlers, and message handlers
onto the Dispatcher so main.py stays clean.
"""

import logging
from aiogram import Dispatcher

from bot.commands import router as commands_router

logger = logging.getLogger("sidicoin.handler")


def register_all_handlers(dp: Dispatcher) -> None:
    """
    Register all bot routers with the dispatcher.
    Order matters — commands first, then callbacks, then catch-all text.
    The commands router already contains all handlers in the correct order.
    """
    dp.include_router(commands_router)
    logger.info("All bot handlers registered successfully")
