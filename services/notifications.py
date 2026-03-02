"""
Scheduled notification jobs for Sidicoin bot.
Runs via APScheduler from main.py.
All times in WAT (UTC+1 / Africa/Lagos).
"""

import time
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from services.redis import (
    get_all_user_ids,
    get_user,
    check_premium_status,
)
from utils.formatting import fmt_number, sidi_to_naira, fmt_naira

logger = logging.getLogger("sidicoin.notifications")


async def _safe_send(bot: Bot, chat_id: str, text: str, **kwargs) -> bool:
    """Send a message safely, catching blocked/deleted users."""
    try:
        await bot.send_message(chat_id=int(chat_id), text=text, **kwargs)
        return True
    except TelegramForbiddenError:
        logger.info(f"User {chat_id} has blocked the bot")
        return False
    except TelegramBadRequest as e:
        logger.warning(f"Bad request sending to {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return False


async def send_daily_checkin_reminders(bot: Bot):
    """
    Send daily check-in reminders at 9am WAT to users who haven't checked in.
    """
    logger.info("Running daily check-in reminder job")
    now = int(time.time())
    user_ids = get_all_user_ids()
    sent_count = 0

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            last_checkin = int(user.get("daily_checkin_last", 0))
            # Check if last checkin was not today (more than 18 hours ago)
            if now - last_checkin > 64800:  # 18 hours
                streak = int(user.get("checkin_streak", 0))
                name = user.get("full_name", "there")

                if streak > 0:
                    text = (
                        f"☀️ Good morning, {name}!\n\n"
                        f"Don't break your <b>{streak}-day streak</b>! "
                        f"Check in now to earn free SIDI.\n\n"
                        f"Type /checkin to claim your daily reward ✦"
                    )
                else:
                    text = (
                        f"☀️ Good morning, {name}!\n\n"
                        f"Start your day with free SIDI! "
                        f"Check in daily to build your streak and earn more.\n\n"
                        f"Type /checkin to claim your reward ✦"
                    )

                if await _safe_send(bot, uid, text):
                    sent_count += 1

        except Exception as e:
            logger.error(f"Check-in reminder error for {uid}: {e}")

    logger.info(f"Sent {sent_count} check-in reminders")


async def send_premium_expiry_alerts(bot: Bot):
    """
    Check premium accounts expiring in 3 days and send reminders.
    Runs every hour.
    """
    logger.info("Running premium expiry alert job")
    now = int(time.time())
    three_days = 3 * 86400
    user_ids = get_all_user_ids()

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or not user.get("is_premium"):
                continue

            expiry = int(user.get("premium_expiry", 0))
            time_left = expiry - now

            # Alert if expiring within 3 days but not yet expired
            if 0 < time_left <= three_days:
                days_left = time_left // 86400
                name = user.get("full_name", "there")

                text = (
                    f"⚠️ {name}, your Sidicoin Premium ✦ expires in "
                    f"<b>{days_left} day{'s' if days_left != 1 else ''}</b>!\n\n"
                    f"Renew now to keep your:\n"
                    f"• 500K SIDI daily limit\n"
                    f"• 0.8% reduced fees\n"
                    f"• 25 SIDI daily check-in\n"
                    f"• ✦ Premium badge\n\n"
                    f"Type /premium to renew ✦"
                )

                await _safe_send(bot, uid, text)

        except Exception as e:
            logger.error(f"Premium expiry alert error for {uid}: {e}")


async def send_reengagement_messages(bot: Bot):
    """
    Send re-engagement messages to users inactive for 3+ days.
    Runs daily at 10am WAT.
    """
    logger.info("Running re-engagement job")
    now = int(time.time())
    three_days_ago = now - (3 * 86400)
    user_ids = get_all_user_ids()
    sent_count = 0

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            last_active = int(user.get("last_active", 0))
            if 0 < last_active < three_days_ago:
                name = user.get("full_name", "there")
                balance = float(user.get("sidi_balance", 0))
                naira_value = sidi_to_naira(balance)

                text = (
                    f"Hey {name}, your <b>{fmt_number(balance)} SIDI</b> "
                    f"({fmt_naira(naira_value)}) is waiting for you ✦\n\n"
                    f"Don't forget to /checkin for free daily SIDI!"
                )

                if await _safe_send(bot, uid, text):
                    sent_count += 1

        except Exception as e:
            logger.error(f"Re-engagement error for {uid}: {e}")

    logger.info(f"Sent {sent_count} re-engagement messages")


async def send_streak_warnings(bot: Bot):
    """
    Warn users whose streak is about to break (18hrs since last check-in).
    Runs every 6 hours.
    """
    logger.info("Running streak warning job")
    now = int(time.time())
    user_ids = get_all_user_ids()

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            streak = int(user.get("checkin_streak", 0))
            if streak < 2:
                continue

            last_checkin = int(user.get("daily_checkin_last", 0))
            time_since = now - last_checkin

            # Warn if between 18-24 hours since last check-in
            if 64800 <= time_since <= 86400:
                name = user.get("full_name", "there")
                hours_left = max(1, (86400 - time_since) // 3600)

                text = (
                    f"⚠️ {name}, your <b>{streak}-day streak</b> expires in "
                    f"~{hours_left} hour{'s' if hours_left != 1 else ''}!\n\n"
                    f"Type /checkin now to keep it alive ✦"
                )

                await _safe_send(bot, uid, text)

        except Exception as e:
            logger.error(f"Streak warning error for {uid}: {e}")


async def notify_user(bot: Bot, telegram_id: int | str, text: str, reply_markup=None) -> bool:
    """Send a notification to a specific user."""
    return await _safe_send(bot, str(telegram_id), text, reply_markup=reply_markup)


async def notify_admin(bot: Bot, text: str) -> bool:
    """Send a notification to the admin."""
    import os
    admin_id = os.getenv("ADMIN_TELEGRAM_ID", "")
    if not admin_id:
        return False
    return await _safe_send(bot, admin_id, text)
