"""
Sidicoin Telegram Bot — main.py
FastAPI entry point with webhook routes and scheduled jobs.
Production domain: coin.sidihost.sbs
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Suppress noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)
logger = logging.getLogger("sidicoin")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://coin.sidihost.sbs")
PORT = int(os.getenv("PORT", "8000"))

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone="Africa/Lagos")


def setup_scheduler():
    """Register all scheduled jobs (WAT = UTC+1)."""
    from services.notifications import (
        send_daily_checkin_reminders,
        send_premium_expiry_alerts,
        send_reengagement_messages,
        send_streak_warnings,
        reset_daily_stats,
    )

    # Every day at 9am WAT — daily check-in reminder
    scheduler.add_job(
        send_daily_checkin_reminders,
        CronTrigger(hour=9, minute=0),
        args=[bot],
        id="daily_checkin_reminder",
        replace_existing=True,
    )

    # Every hour — premium expiry alerts (3 days before)
    scheduler.add_job(
        send_premium_expiry_alerts,
        IntervalTrigger(hours=1),
        args=[bot],
        id="premium_expiry_alerts",
        replace_existing=True,
    )

    # Every day at 10am WAT — re-engagement for inactive users (3+ days)
    scheduler.add_job(
        send_reengagement_messages,
        CronTrigger(hour=10, minute=0),
        args=[bot],
        id="reengagement_messages",
        replace_existing=True,
    )

    # Every 6 hours — streak-about-to-break warnings
    scheduler.add_job(
        send_streak_warnings,
        IntervalTrigger(hours=6),
        args=[bot],
        id="streak_warnings",
        replace_existing=True,
    )

    # Midnight WAT — reset daily stats and archive
    scheduler.add_job(
        reset_daily_stats,
        CronTrigger(hour=0, minute=0),
        args=[bot],
        id="reset_daily_stats",
        replace_existing=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    from bot.handler import register_all_handlers
    from bot.middleware import BanCheckMiddleware, RateLimitMiddleware

    # Register middleware (order: ban check first, then rate limit)
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())

    # Register all bot handlers
    register_all_handlers(dp)

    # Set Telegram webhook
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/telegram"
    await bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )
    logger.info(f"Telegram webhook set to {webhook_url}")

    # Start scheduler
    setup_scheduler()
    scheduler.start()
    logger.info("APScheduler started")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Bot shutdown complete")


app = FastAPI(title="Sidicoin Bot", version="1.0.0", lifespan=lifespan)

# ── Mount routes ──────────────────────────────────────────────
from routes.telegram import router as telegram_router
from routes.korapay_webhook import router as korapay_router
from routes.flutterwave_webhook import router as flutterwave_router
from routes.admin import router as admin_router

app.include_router(telegram_router)
app.include_router(korapay_router)
app.include_router(flutterwave_router)
app.include_router(admin_router)


@app.get("/")
async def root():
    return {
        "service": "Sidicoin Bot",
        "status": "running",
        "domain": "coin.sidihost.sbs",
    }


@app.get("/health")
async def health():
    """Health check with Redis connectivity verification."""
    redis_ok = False
    try:
        from services.redis import redis
        redis.ping()
        redis_ok = True
    except Exception:
        pass

    status = "ok" if redis_ok else "degraded"
    return {
        "status": status,
        "redis": "connected" if redis_ok else "error",
        "domain": "coin.sidihost.sbs",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
