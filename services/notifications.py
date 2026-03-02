"""
Scheduled notification jobs for SidiApp bot.
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

logger = logging.getLogger("sidiapp.notifications")


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
    Send check-in reminders at 9am WAT to users who haven't checked in today.
    Uses the monthly progressive system (10 per month).
    """
    logger.info("Running check-in reminder job")
    now = int(time.time())
    user_ids = get_all_user_ids()
    sent_count = 0

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            # Check if already used all 10 monthly check-ins
            current_month = time.strftime("%Y-%m", time.gmtime(now + 3600))
            stored_month = user.get("monthly_checkin_month", "")
            monthly_count = int(user.get("monthly_checkin_count", 0))
            if stored_month == current_month and monthly_count >= 10:
                continue  # All check-ins used this month

            last_checkin = int(user.get("daily_checkin_last", 0))
            # Check if last checkin was not today (more than 18 hours ago)
            if now - last_checkin > 64800:  # 18 hours
                streak = int(user.get("checkin_streak", 0))
                name = user.get("full_name", "there")
                remaining = 10 - monthly_count if stored_month == current_month else 10

                if streak > 0:
                    text = (
                        f"\u2600\ufe0f Good morning, {name}!\n\n"
                        f"Don't break your <b>{streak}-day streak</b>! "
                        f"You have <b>{remaining} check-ins</b> left this month.\n\n"
                        f"Type /checkin to claim your reward \u2726"
                    )
                else:
                    text = (
                        f"\u2600\ufe0f Good morning, {name}!\n\n"
                        f"Earn free SIDI! You have <b>{remaining} check-ins</b> "
                        f"left this month. Rewards grow bigger each time!\n\n"
                        f"Type /checkin to start earning \u2726"
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
                    f"\u26a0\ufe0f {name}, your SidiApp Premium \u2726 expires in "
                    f"<b>{days_left} day{'s' if days_left != 1 else ''}</b>!\n\n"
                    f"Renew now to keep your:\n"
                    f"\u2022 500K SIDI daily limit\n"
                    f"\u2022 \u2726 Premium badge\n"
                    f"\u2022 Priority support\n"
                    f"\u2022 Escrow priority\n\n"
                    f"Type /premium to renew \u2726"
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


async def send_low_balance_reminders(bot: Bot):
    """
    Remind users with low balance who haven't topped up in 7+ days.
    Runs daily at 11am WAT.
    """
    logger.info("Running low-balance reminder job")
    now = int(time.time())
    seven_days_ago = now - (7 * 86400)
    user_ids = get_all_user_ids()
    sent_count = 0

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            balance = float(user.get("sidi_balance", 0))
            last_buy = int(user.get("last_buy_timestamp", 0))
            name = user.get("full_name", "there")

            # Low balance: < 10 SIDI and haven't bought in 7+ days
            if balance < 10 and (last_buy == 0 or last_buy < seven_days_ago):
                # Don't send if we sent a re-engagement recently
                last_active = int(user.get("last_active", 0))
                if last_active > seven_days_ago:
                    # They're active but low balance
                    text = (
                        f"{name}, your balance is low "
                        f"(<b>{fmt_number(balance)} SIDI</b>).\n\n"
                        f"Top up with /buy -- zero fees, instant credit.\n"
                        f"You can also earn free SIDI with /checkin \u2726"
                    )
                    if await _safe_send(bot, uid, text):
                        sent_count += 1

        except Exception as e:
            logger.error(f"Low balance reminder error for {uid}: {e}")

    logger.info(f"Sent {sent_count} low-balance reminders")


async def send_game_reminders(bot: Bot):
    """
    Remind active gamers about games. Runs at 2pm WAT.
    """
    logger.info("Running game reminder job")
    now = int(time.time())
    user_ids = get_all_user_ids()
    sent_count = 0

    for uid in user_ids:
        try:
            user = get_user(uid)
            if not user or user.get("is_banned"):
                continue

            games_played = int(user.get("games_played", 0))
            balance = float(user.get("sidi_balance", 0))

            # Only remind users who have played before and have balance
            if games_played >= 3 and balance >= 5:
                games_won = int(user.get("games_won", 0))
                name = user.get("full_name", "there")

                text = (
                    f"{name}, ready for another round?\n\n"
                    f"Your stats: <b>{games_won}/{games_played}</b> wins.\n"
                    f"Type /game to play \u2726"
                )

                if await _safe_send(bot, uid, text):
                    sent_count += 1

        except Exception as e:
            logger.error(f"Game reminder error for {uid}: {e}")

    logger.info(f"Sent {sent_count} game reminders")


async def send_escrow_expiry_alerts(bot: Bot):
    """
    Alert users about escrows that are about to expire or have been pending too long.
    Runs every 6 hours.
    """
    logger.info("Running escrow expiry alert job")
    now = int(time.time())
    user_ids = get_all_user_ids()

    from services.redis import get_user_escrows, get_escrow

    for uid in user_ids:
        try:
            escrows = get_user_escrows(uid)
            for esc in escrows:
                status = esc.get("status", "")
                created = int(esc.get("created_at", 0))
                age_hours = (now - created) / 3600

                if status == "pending" and age_hours > 24:
                    # Pending for over 24hrs, remind buyer to fund
                    buyer_id = esc.get("buyer_id", "")
                    if buyer_id:
                        esc_id = esc.get("escrow_id", "")
                        amount = float(esc.get("amount_sidi", 0))
                        await _safe_send(
                            bot, buyer_id,
                            f"Your escrow <code>{esc_id}</code> "
                            f"(<b>{fmt_number(amount)} SIDI</b>) is "
                            f"still pending. Fund it to proceed.\n\n"
                            f"Type /escrow to manage \u2726"
                        )

                elif status == "funded" and age_hours > 48:
                    # Funded for over 48hrs, remind seller to deliver
                    seller_id = esc.get("seller_id", "")
                    if seller_id:
                        esc_id = esc.get("escrow_id", "")
                        await _safe_send(
                            bot, seller_id,
                            f"Escrow <code>{esc_id}</code> has been "
                            f"funded for over 48 hours. Please deliver "
                            f"to avoid a dispute.\n\n"
                            f"Type /escrow to manage \u2726"
                        )

        except Exception as e:
            logger.error(f"Escrow expiry alert error for {uid}: {e}")


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


async def reset_daily_stats(bot: Bot):
    """
    Reset daily counters at midnight WAT.
    Archives yesterday's stats before zeroing.
    """
    logger.info("Running daily stats reset")
    try:
        from services.redis import get_all_stats, redis, increment_stat
        stats = get_all_stats()

        # Archive yesterday's stats
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400 + 3600))
        daily_volume = stats.get("daily_volume_ngn", 0)
        daily_tx = stats.get("daily_tx_count", 0)

        if daily_volume > 0 or daily_tx > 0:
            redis.hset(f"archive_{yesterday}", mapping={
                "volume_ngn": str(daily_volume),
                "tx_count": str(daily_tx),
            })
            redis.expire(f"archive_{yesterday}", 90 * 86400)  # Keep 90 days

        # Reset daily counters
        redis.hset("stats", mapping={
            "daily_volume_ngn": "0",
            "daily_tx_count": "0",
        })

        logger.info(f"Daily stats reset. Yesterday: vol={daily_volume}, tx={daily_tx}")

        # Notify admin with daily summary
        import os
        admin_id = os.getenv("ADMIN_TELEGRAM_ID", "")
        if admin_id and (daily_volume > 0 or daily_tx > 0):
            from utils.formatting import fmt_naira, fmt_number
            await _safe_send(
                bot, admin_id,
                f"📊 <b>Daily Summary — {yesterday}</b>\n\n"
                f"Volume: {fmt_naira(daily_volume)}\n"
                f"Transactions: {fmt_number(daily_tx)}\n"
                f"Total Holders: {fmt_number(stats.get('total_holders', 0))}\n"
                f"Circulating: {fmt_number(stats.get('circulating_supply', 0))} SIDI"
            )
    except Exception as e:
        logger.error(f"Daily stats reset error: {e}")
