"""
Bot handler registration module.
Registers all command handlers, callback handlers, and message handlers
onto the Dispatcher so main.py stays clean.
"""

import logging
from aiogram import Dispatcher

from bot.commands import router as commands_router
from bot.group_commands import group_router

logger = logging.getLogger("sidicoin.handler")


def register_all_handlers(dp: Dispatcher) -> None:
    """
    Register all bot routers with the dispatcher.
    Order matters:
      1. Private commands router (handles DM commands, callbacks, text)
      2. Group router (handles group tips, giveaways, rain, AI mentions)
    """
    dp.include_router(commands_router)
    dp.include_router(group_router)
    logger.info("All bot handlers registered (private + group)")
