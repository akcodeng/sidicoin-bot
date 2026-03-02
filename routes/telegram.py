"""
Telegram webhook route.
Receives incoming updates from Telegram and feeds them to aiogram's dispatcher.
Endpoint: POST /webhook/telegram
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from aiogram.types import Update

router = APIRouter()
logger = logging.getLogger("sidicoin.routes.telegram")


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Receive Telegram webhook updates.
    The bot and dispatcher are initialised in main.py lifespan
    and imported here to process each update.
    """
    try:
        from main import bot, dp

        body = await request.json()
        update = Update.model_validate(body, context={"bot": bot})

        # Feed update to the dispatcher
        await dp.feed_update(bot=bot, update=update)

        return JSONResponse(content={"ok": True}, status_code=200)

    except Exception as e:
        logger.error(f"Telegram webhook error: {e}", exc_info=True)
        # Always return 200 to Telegram to avoid retries on our errors
        return JSONResponse(content={"ok": True}, status_code=200)
