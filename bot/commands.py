"""
All Sidicoin bot command handlers.
Every command shows a loading state first, then edits with the result.
All messages use HTML parse mode with branded formatting.
Beautiful, consistent, and professional throughout.
"""

import os
import time
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.exceptions import TelegramBadRequest

from services.redis import (
    get_user, save_user, create_user, user_exists,
    get_balance, update_balance, transfer_sidi,
    add_transaction, get_transactions,
    set_pending_action, get_pending_action, clear_pending_action,
    credit_referrer, activate_premium, check_premium_status,
    process_checkin, get_leaderboard, get_user_rank,
    get_all_user_ids, find_user_by_username,
    get_stat, get_all_stats, increment_stat,
    store_pending_payment, track_large_transfer, increment_rate_count,
    update_bank_details,
)
from services.ton import create_wallet, format_wallet_address
from services.korapay import (
    create_bank_transfer_charge, verify_bank_account,
    process_payout, get_bank_code, COMMON_BANKS,
)
from services.groq import get_ai_response, detect_intent
from services.notifications import notify_user, notify_admin
from utils.formatting import (
    fmt_number, sidi_to_naira, naira_to_sidi, fmt_sidi, fmt_naira,
    fmt_timestamp, fmt_date, fmt_relative_time, time_greeting,
    generate_receipt, generate_mini_receipt, generate_tx_reference,
    progress_bar, streak_fire,
    DIVIDER, THIN_DIVIDER, BRAND, STAR, SIDI_PRICE_NGN,
)
from utils.validation import (
    is_valid_username, clean_username, is_valid_amount,
    check_daily_limit, is_large_transfer, calculate_fee,
    calculate_fee_naira, is_valid_bank_account, sanitize_input,
    find_similar_usernames, FREE_DAILY_LIMIT, PREMIUM_DAILY_LIMIT,
)
from bot.keyboards import (
    home_keyboard, welcome_keyboard, balance_keyboard,
    send_confirm_keyboard, send_large_confirm_keyboard,
    after_send_keyboard, received_money_keyboard,
    buy_confirm_keyboard, buy_payment_keyboard, after_buy_keyboard,
    sell_confirm_keyboard, sell_bank_confirm_keyboard, after_sell_keyboard,
    history_filter_keyboard, refer_keyboard, premium_keyboard,
    premium_payment_keyboard, leaderboard_keyboard, settings_keyboard,
    help_keyboard, contacts_keyboard, cancel_keyboard,
    home_button_keyboard, onboarding_step1_keyboard,
    onboarding_step2_keyboard, onboarding_step3_keyboard,
)

logger = logging.getLogger("sidicoin.commands")
router = Router()

ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")
SIDI_FEE_WALLET = os.getenv("SIDI_FEE_WALLET", "")


# =====================================================================
#  UTILITY HELPERS
# =====================================================================

async def _get_bot_username(bot: Bot) -> str:
    """Get bot username for referral links."""
    me = await bot.get_me()
    return me.username or ""


def _account_badge(user: dict) -> str:
    """Return account type display string."""
    if check_premium_status(user):
        return f"Premium {STAR}"
    return "Free"


def _get_daily_remaining(user: dict) -> float:
    """Get remaining daily transfer limit."""
    is_prem = check_premium_status(user)
    limit = PREMIUM_DAILY_LIMIT if is_prem else FREE_DAILY_LIMIT
    today = time.strftime("%Y-%m-%d")
    if user.get("daily_tx_date") != today:
        return float(limit)
    return max(0.0, float(limit) - float(user.get("daily_tx_total", 0)))


def _transfer_count(user: dict) -> int:
    """Count total send transactions."""
    txns = user.get("transactions", [])
    if not isinstance(txns, list):
        return 0
    return sum(1 for t in txns if t.get("type") == "send")


def _safe_escape(text: str) -> str:
    """Escape < and > in user-generated text for HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =====================================================================
#  /start
# =====================================================================

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    """Handle /start -- new user onboarding or returning user welcome."""
    try:
        user_id = message.from_user.id
        from_user = message.from_user
        username = from_user.username or f"user_{user_id}"
        full_name = f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
        first_name = from_user.first_name or username

        # Check for referral code
        referred_by = ""
        if command.args and command.args.startswith("ref_"):
            referred_by = command.args.replace("ref_", "")

        existing_user = get_user(user_id)

        if existing_user:
            # -- Returning user --
            balance = float(existing_user.get("sidi_balance", 0))
            naira = sidi_to_naira(balance)
            greeting = time_greeting(first_name)
            badge = _account_badge(existing_user)
            remaining = _get_daily_remaining(existing_user)

            text = (
                f"{STAR} <b>{greeting}</b>\n\n"
                f"Welcome back to Sidicoin.\n\n"
                f"{DIVIDER}\n"
                f"  <b>Your Wallet</b>\n\n"
                f"  \U0001f48e  <b>{fmt_number(balance)} SIDI</b>\n"
                f"  \U0001f4b5  {fmt_naira(naira)}\n"
                f"  \U0001f3c6  {badge} Account\n"
                f"  \U0001f4ca  {fmt_number(remaining)} SIDI daily limit left\n"
                f"{DIVIDER}\n\n"
                f"What would you like to do? {STAR}"
            )
            await message.answer(text, reply_markup=home_keyboard())
            return

        # -- New user --
        loading_msg = await message.answer(
            f"\u26a1 Setting up your Sidicoin wallet..."
        )

        # Create TON wallet
        wallet_address, encrypted_key = create_wallet()

        # Create user record
        user = create_user(
            telegram_id=user_id,
            username=username,
            full_name=full_name,
            photo_url="",
            wallet_address=wallet_address,
            encrypted_private_key=encrypted_key,
            referred_by=referred_by,
        )

        # Credit referrer if applicable
        referrer_name_display = ""
        if referred_by:
            try:
                referrer_id = int(referred_by)
                if user_exists(referrer_id):
                    credit_referrer(referrer_id, 50.0, "signup")
                    referrer = get_user(referrer_id)
                    if referrer:
                        referrer_name_display = referrer.get("full_name", "")
                        await notify_user(
                            bot, referrer_id,
                            f"{STAR} <b>Referral Bonus!</b>\n\n"
                            f"<b>{_safe_escape(first_name)}</b> just joined Sidicoin "
                            f"through your referral link.\n\n"
                            f"+<b>50 SIDI</b> ({fmt_naira(sidi_to_naira(50))}) "
                            f"added to your wallet.\n\n"
                            f"Keep sharing, keep earning {STAR}"
                        )
            except (ValueError, Exception) as e:
                logger.error(f"Referral credit error: {e}")

        # Build beautiful welcome message
        referral_line = ""
        if referred_by and referrer_name_display:
            referral_line = (
                f"\n\U0001f91d You joined through <b>{_safe_escape(referrer_name_display)}</b>'s "
                f"referral. You both earned bonus SIDI!\n"
            )
        elif referred_by:
            referral_line = (
                f"\n\U0001f91d You joined through a referral link. "
                f"You both earned bonus SIDI!\n"
            )

        welcome_text = (
            f"{STAR} <b>Welcome to Sidicoin, {_safe_escape(first_name)}</b>\n\n"
            f"Your wallet is ready.\n"
            f"Your money moves instantly across Africa.\n"
            f"{referral_line}\n"
            f"{DIVIDER}\n"
            f"  <b>Your Welcome Gift</b>\n\n"
            f"  \U0001f48e  <b>80 SIDI</b>\n"
            f"  \U0001f4b5  {fmt_naira(2000)}\n"
            f"  \u2705  Ready to send, spend or save\n"
            f"{DIVIDER}\n\n"
            f"Sidicoin lets you send money to anyone in Africa using "
            f"just their Telegram @username \u2014 instantly, for free.\n\n"
            f"Type /help to see everything you can do {STAR}"
        )

        try:
            await loading_msg.edit_text(welcome_text, reply_markup=welcome_keyboard())
        except TelegramBadRequest:
            await message.answer(welcome_text, reply_markup=welcome_keyboard())

        # Send onboarding step 1
        onboard_text = (
            f"{STAR} <b>Let's get you started</b>\n\n"
            f"Sidicoin is the easiest way to move\n"
            f"money across Africa.\n\n"
            f"\u2022 No bank transfers\n"
            f"\u2022 No long account numbers\n"
            f"\u2022 No hidden fees\n\n"
            f"Just a Telegram @username and you're done."
        )
        await message.answer(onboard_text, reply_markup=onboarding_step1_keyboard())

    except Exception as e:
        logger.error(f"/start error: {e}", exc_info=True)
        await message.answer(
            f"Something went wrong on our end. Please try again in a moment {STAR}",
            reply_markup=home_button_keyboard(),
        )


# =====================================================================
#  /balance
# =====================================================================

@router.message(Command("balance", "wallet"))
async def cmd_balance(message: Message):
    """Show detailed wallet balance."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"You don't have a wallet yet. Type /start to create one {STAR}")
            return

        loading = await message.answer("\U0001f4ca Fetching your wallet...")
        await _show_balance(loading, user)
    except Exception as e:
        logger.error(f"/balance error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


async def _show_balance(msg: Message, user: dict):
    """Edit message with beautifully formatted balance details."""
    balance = float(user.get("sidi_balance", 0))
    naira = sidi_to_naira(balance)
    username = user.get("username", "")
    full_name = user.get("full_name", "")
    total_sent = float(user.get("total_sent", 0))
    total_received = float(user.get("total_received", 0))
    remaining = _get_daily_remaining(user)
    badge = _account_badge(user)
    is_prem = check_premium_status(user)
    limit = PREMIUM_DAILY_LIMIT if is_prem else FREE_DAILY_LIMIT
    used = float(limit) - remaining

    text = (
        f"{STAR} <b>{_safe_escape(full_name)}'s Wallet</b>\n"
        f"@{username}\n\n"
        f"{DIVIDER}\n\n"
        f"  \U0001f48e <b>{fmt_number(balance)} SIDI</b>\n"
        f"  \U0001f4b5 {fmt_naira(naira)}\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"  \U0001f4e4 Sent       {fmt_number(total_sent)} SIDI\n"
        f"  \U0001f4e5 Received   {fmt_number(total_received)} SIDI\n"
        f"  \U0001f3c6 Account    {badge}\n"
        f"  \U0001f4ca Daily      {progress_bar(used, float(limit))}  "
        f"{fmt_number(remaining)} left\n\n"
        f"{DIVIDER}"
    )
    try:
        await msg.edit_text(text, reply_markup=balance_keyboard())
    except TelegramBadRequest:
        pass


# =====================================================================
#  /send
# =====================================================================

@router.message(Command("send"))
async def cmd_send(message: Message, bot: Bot):
    """Handle /send -- direct or guided flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        text = message.text.strip()
        parts = text.split()

        # METHOD 1: Direct /send @username 500
        if len(parts) >= 3:
            recipient_username = parts[1]
            amount_text = " ".join(parts[2:])
            valid, amount = is_valid_amount(amount_text)
            if valid and is_valid_username(recipient_username):
                await _process_send_flow(message, bot, user, recipient_username, amount)
                return

        # METHOD 2: Guided flow
        await message.answer(
            f"{STAR} <b>Send SIDI</b>\n\n"
            f"Who would you like to send to?\n\n"
            f"Enter their Telegram @username:",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "send_username")

    except Exception as e:
        logger.error(f"/send error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


async def _process_send_flow(message: Message, bot: Bot, sender: dict, recipient_username: str, amount: float):
    """Process the send confirmation and execution."""
    sender_id = sender["telegram_id"]
    clean_user = clean_username(recipient_username)

    # Check recipient exists
    recipient = find_user_by_username(clean_user)
    if not recipient:
        all_ids = get_all_user_ids()
        all_users = []
        for uid in all_ids[:200]:
            u = get_user(uid)
            if u and u.get("username"):
                all_users.append(u["username"])

        similar = find_similar_usernames(clean_user, all_users)
        bot_username = await _get_bot_username(bot)

        suggest_text = ""
        if similar:
            suggest_text = "\n\nDid you mean: " + ", ".join(f"@{s}" for s in similar[:3])

        invite_link = f"https://t.me/{bot_username}?start=ref_{sender_id}"
        await message.answer(
            f"@{clean_user} hasn't joined Sidicoin yet.{suggest_text}\n\n"
            f"Invite them:\n<code>{invite_link}</code> {STAR}",
            reply_markup=home_button_keyboard(),
        )
        return

    if str(recipient["telegram_id"]) == str(sender_id):
        await message.answer(f"You can't send SIDI to yourself {STAR}", reply_markup=home_button_keyboard())
        return

    # Check balance
    balance = float(sender.get("sidi_balance", 0))
    if balance < amount:
        await message.answer(
            f"Insufficient balance.\n\n"
            f"You have <b>{fmt_number(balance)} SIDI</b> "
            f"but tried to send <b>{fmt_number(amount)} SIDI</b>.\n\n"
            f"Top up with /buy {STAR}",
            reply_markup=home_button_keyboard(),
        )
        return

    # Check daily limit
    is_premium = check_premium_status(sender)
    within_limit, remaining = check_daily_limit(
        float(sender.get("daily_tx_total", 0)), amount, is_premium
    )
    if not within_limit:
        limit = PREMIUM_DAILY_LIMIT if is_premium else FREE_DAILY_LIMIT
        await message.answer(
            f"Daily transfer limit reached.\n\n"
            f"Limit: {fmt_number(limit)} SIDI\n"
            f"Remaining: {fmt_number(remaining)} SIDI\n\n"
            f"{'Upgrade to Premium for 500K/day: /premium' if not is_premium else 'Try again tomorrow'} {STAR}",
            reply_markup=home_button_keyboard(),
        )
        return

    naira = sidi_to_naira(amount)
    r_name = recipient.get("full_name", recipient.get("username", ""))
    r_uname = recipient.get("username", clean_user)

    # Store pending send data
    set_pending_action(int(sender_id), "send_confirm", {
        "recipient_id": recipient["telegram_id"],
        "recipient_username": r_uname,
        "recipient_name": r_name,
        "amount": amount,
    })

    # Large transfer warning
    keyboard = send_confirm_keyboard()
    warning = ""
    if is_large_transfer(amount):
        warning = f"\n\u26a0\ufe0f <b>Large transfer</b> \u2014 double-check the details.\n"
        keyboard = send_large_confirm_keyboard()

    confirm_text = (
        f"{STAR} <b>Transfer Summary</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  To       @{r_uname}\n"
        f"  Name     {_safe_escape(r_name)}\n"
        f"  Amount   <b>{fmt_number(amount)} SIDI</b>\n"
        f"  Value    {fmt_naira(naira)}\n"
        f"  Fee      Free \u2705\n"
        f"  Speed    Instant \u26a1\n\n"
        f"{DIVIDER}"
        f"{warning}\n"
        f"Confirm this transfer?"
    )
    await message.answer(confirm_text, reply_markup=keyboard)


# =====================================================================
#  /buy
# =====================================================================

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    """Start buy SIDI flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        is_prem = check_premium_status(user)
        fee_label = "0.8%" if is_prem else "1.5%"

        await message.answer(
            f"{STAR} <b>Buy SIDI</b>\n\n"
            f"How much would you like to buy?\n\n"
            f"Enter amount in SIDI or Naira:\n\n"
            f"  <code>500</code>        \u2192 500 SIDI\n"
            f"  <code>2000 SIDI</code>  \u2192 2,000 SIDI\n"
            f"  <code>5000 NGN</code>   \u2192 {fmt_naira(5000)} worth\n"
            f"  <code>5k</code>         \u2192 5,000 SIDI\n\n"
            f"Fee: {fee_label}",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "buy_amount")

    except Exception as e:
        logger.error(f"/buy error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /sell
# =====================================================================

@router.message(Command("sell", "cashout"))
async def cmd_sell(message: Message):
    """Start sell/cashout flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        balance = float(user.get("sidi_balance", 0))
        if balance <= 0:
            await message.answer(
                f"You don't have any SIDI to cash out.\n"
                f"Buy some first with /buy {STAR}",
                reply_markup=home_button_keyboard(),
            )
            return

        is_prem = check_premium_status(user)
        fee_label = "0.8%" if is_prem else "1.5%"

        await message.answer(
            f"{STAR} <b>Cash Out SIDI</b>\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?\n"
            f"Fee: {fee_label}",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "sell_amount")

    except Exception as e:
        logger.error(f"/sell error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /history
# =====================================================================

@router.message(Command("history"))
async def cmd_history(message: Message):
    """Show transaction history."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return
        await _show_history(message, user, "all")
    except Exception as e:
        logger.error(f"/history error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


async def _show_history(target, user: dict, tx_filter: str):
    """Display beautifully formatted transaction history with filter."""
    txns = user.get("transactions", [])
    if not isinstance(txns, list):
        txns = []

    if tx_filter == "sent":
        txns = [t for t in txns if t.get("type") == "send"]
    elif tx_filter == "received":
        txns = [t for t in txns if t.get("type") == "receive"]
    elif tx_filter == "buysell":
        txns = [t for t in txns if t.get("type") in ("buy", "sell")]

    if not txns:
        text = (
            f"{STAR} <b>Transaction History</b>\n\n"
            f"No transactions yet.\n"
            f"Start with /send or /buy {STAR}"
        )
        if isinstance(target, Message):
            await target.answer(text, reply_markup=history_filter_keyboard())
        elif isinstance(target, CallbackQuery):
            try:
                await target.message.edit_text(text, reply_markup=history_filter_keyboard())
            except TelegramBadRequest:
                pass
        return

    filter_label = {"all": "All", "sent": "Sent", "received": "Received", "buysell": "Buy/Sell"}.get(tx_filter, "All")
    lines = [f"{STAR} <b>Transaction History</b>  \u2022  {filter_label}\n", DIVIDER]

    # Type icons for beautiful display
    type_icons = {
        "send": "\U0001f4e4",
        "receive": "\U0001f4e5",
        "buy": "\U0001f4b3",
        "sell": "\U0001f4b0",
        "bonus": "\U0001f381",
        "checkin": "\u2705",
        "referral_bonus": "\U0001f91d",
        "premium": "\u2b50",
        "debit": "\u26a0\ufe0f",
    }

    for tx in txns[:20]:
        tx_type = tx.get("type", "")
        amount = float(tx.get("amount", 0))
        ts = tx.get("timestamp", 0)
        time_str = fmt_relative_time(ts) if ts else ""
        other = tx.get("other_username", "")
        icon = type_icons.get(tx_type, "\u2022")

        if tx_type == "send":
            lines.append(f"{icon} Sent <b>{fmt_number(amount)} SIDI</b> to @{other}")
            lines.append(f"     {fmt_naira(sidi_to_naira(amount))} \u2022 {time_str}")
        elif tx_type == "receive":
            lines.append(f"{icon} Received <b>{fmt_number(amount)} SIDI</b> from @{other}")
            lines.append(f"     {fmt_naira(sidi_to_naira(amount))} \u2022 {time_str}")
        elif tx_type == "buy":
            lines.append(f"{icon} Bought <b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"     {fmt_naira(sidi_to_naira(amount))} \u2022 {time_str}")
        elif tx_type == "sell":
            desc = tx.get("description", "")
            lines.append(f"{icon} Cashed out <b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"     {desc} \u2022 {time_str}")
        elif tx_type in ("bonus", "referral_bonus", "checkin"):
            desc = tx.get("description", tx_type.title())
            lines.append(f"{icon} {desc}: +<b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"     {time_str}")
        elif tx_type == "premium":
            lines.append(f"{icon} Premium activated")
            lines.append(f"     {time_str}")
        else:
            desc = tx.get("description", "Transaction")
            lines.append(f"{icon} {desc}: {fmt_number(amount)} SIDI \u2022 {time_str}")

        lines.append("")  # spacer between entries

    lines.append(DIVIDER)
    text = "\n".join(lines)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=history_filter_keyboard())
    elif isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=history_filter_keyboard())
        except TelegramBadRequest:
            pass


# =====================================================================
#  /contacts
# =====================================================================

@router.message(Command("contacts"))
async def cmd_contacts(message: Message):
    """Show saved contacts."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        contacts = user.get("saved_contacts", [])
        if not contacts:
            await message.answer(
                f"{STAR} <b>Saved Contacts</b>\n\n"
                f"No saved contacts yet.\n"
                f"Send SIDI to someone and they'll appear here {STAR}",
                reply_markup=home_button_keyboard(),
            )
            return

        lines = [f"{STAR} <b>Saved Contacts</b>\n", DIVIDER, ""]
        for i, c in enumerate(contacts[:10], 1):
            name = c.get("full_name", "")
            uname = c.get("username", "")
            last = c.get("last_transfer", 0)
            time_str = fmt_relative_time(last) if last else ""
            lines.append(f"  {i}. <b>{_safe_escape(name)}</b> (@{uname})")
            if time_str:
                lines.append(f"      Last: {time_str}")
            lines.append("")

        lines.append(DIVIDER)
        lines.append(f"\nTap a contact to send SIDI instantly {STAR}")
        text = "\n".join(lines)
        await message.answer(text, reply_markup=contacts_keyboard(contacts))

    except Exception as e:
        logger.error(f"/contacts error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /refer
# =====================================================================

@router.message(Command("refer", "referral"))
async def cmd_refer(message: Message, bot: Bot):
    """Show referral info and link."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        bot_username = await _get_bot_username(bot)
        ref_link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}"
        count = int(user.get("referral_count", 0))
        earned = float(user.get("referral_earnings", 0))

        text = (
            f"{STAR} <b>Refer & Earn</b>\n\n"
            f"Your link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>Rewards</b>\n\n"
            f"  \U0001f91d Per signup    +<b>50 SIDI</b> ({fmt_naira(sidi_to_naira(50))})\n"
            f"  \U0001f4b3 Per purchase  +<b>10 SIDI</b> ({fmt_naira(sidi_to_naira(10))})\n"
            f"  \u267e\ufe0f  Forever       Earn on every purchase they make\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  <b>Your Stats</b>\n\n"
            f"  \U0001f465 Referrals    <b>{count}</b>\n"
            f"  \U0001f48e Earned       <b>{fmt_number(earned)} SIDI</b> ({fmt_naira(sidi_to_naira(earned))})\n\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=refer_keyboard(ref_link))

    except Exception as e:
        logger.error(f"/refer error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /checkin
# =====================================================================

@router.message(Command("checkin"))
async def cmd_checkin(message: Message):
    """Daily check-in reward."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        success, bonus_msg, amount, streak = process_checkin(message.from_user.id)

        if not success:
            await message.answer(bonus_msg, reply_markup=home_button_keyboard())
            return

        user = get_user(message.from_user.id)
        balance = float(user.get("sidi_balance", 0))
        fires = streak_fire(streak)

        text = (
            f"{STAR} <b>Daily Reward Claimed!</b>\n\n"
            f"+<b>{fmt_number(amount)} SIDI</b> added to your wallet\n\n"
            f"  {fires}  Streak: <b>{streak} days</b>\n"
            f"  \U0001f48e  Balance: <b>{fmt_number(balance)} SIDI</b>\n"
            f"{bonus_msg}"
        )
        await message.answer(text, reply_markup=home_keyboard())

    except Exception as e:
        logger.error(f"/checkin error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /premium
# =====================================================================

@router.message(Command("premium"))
async def cmd_premium(message: Message):
    """Show premium comparison and upgrade option."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        if check_premium_status(user):
            expiry = int(user.get("premium_expiry", 0))
            await message.answer(
                f"{STAR} <b>You're Premium {STAR}</b>\n\n"
                f"Expires: {fmt_timestamp(expiry)}\n\n"
                f"Enjoy lower fees and higher limits {STAR}",
                reply_markup=home_keyboard(),
            )
            return

        text = (
            f"{STAR} <b>Sidicoin Premium</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>Feature</b>          <b>Free</b>     <b>Premium</b>\n\n"
            f"  Daily Limit       50K      <b>500K</b>\n"
            f"  Buy/Sell Fee      1.5%     <b>0.8%</b>\n"
            f"  Daily Check-in    10       <b>25 SIDI</b>\n"
            f"  Badge             \u2014        <b>{STAR}</b>\n"
            f"  Priority Support  \u2014        <b>\u2705</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>{fmt_naira(1500)} per month</b>\n"
            f"  That's just {fmt_naira(50)}/day for 10x the limits"
        )
        await message.answer(text, reply_markup=premium_keyboard())

    except Exception as e:
        logger.error(f"/premium error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /leaderboard
# =====================================================================

@router.message(Command("leaderboard", "top"))
async def cmd_leaderboard(message: Message):
    """Show top holders leaderboard."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        await _show_leaderboard(message, user)

    except Exception as e:
        logger.error(f"/leaderboard error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


async def _show_leaderboard(target, user: dict, is_edit: bool = False):
    """Display leaderboard."""
    leaders = get_leaderboard(5)
    rank = get_user_rank(user["telegram_id"])
    balance = float(user.get("sidi_balance", 0))

    medals = ["\U0001f947", "\U0001f948", "\U0001f949", "4.", "5."]
    lines = [f"{STAR} <b>Top Sidicoin Holders</b>\n", DIVIDER, ""]

    for i, (uid, score) in enumerate(leaders):
        leader_user = get_user(uid)
        uname = leader_user.get("username", uid) if leader_user else uid
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        prem = check_premium_status(leader_user) if leader_user else False
        badge = f" {STAR}" if prem else ""
        lines.append(f"  {medal} @{uname}{badge} \u2014 <b>{fmt_number(score)} SIDI</b>")

    lines.append("")
    lines.append(DIVIDER)
    lines.append(f"\n  Your Rank: <b>#{rank}</b>")
    lines.append(f"  Your Balance: <b>{fmt_number(balance)} SIDI</b> {STAR}")

    text = "\n".join(lines)
    if is_edit and isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=leaderboard_keyboard())
        except TelegramBadRequest:
            pass
    elif isinstance(target, Message):
        await target.answer(text, reply_markup=leaderboard_keyboard())


# =====================================================================
#  /price
# =====================================================================

@router.message(Command("price"))
async def cmd_price(message: Message):
    """Show current SIDI price and market data."""
    try:
        loading = await message.answer("\U0001f4c8 Fetching live data...")

        stats = get_all_stats()
        holders = int(stats.get("total_holders", 0))
        volume = float(stats.get("daily_volume_ngn", 0))
        tx_count = int(stats.get("daily_tx_count", 0))
        cap = SIDI_PRICE_NGN * 10_000_000_000
        usd_rate = 1600
        usd_equiv = SIDI_PRICE_NGN / usd_rate

        text = (
            f"{STAR} <b>Sidicoin Price</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  1 SIDI = <b>{fmt_naira(SIDI_PRICE_NGN)}</b>\n"
            f"  1 SIDI = <b>${usd_equiv:.6f}</b>\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  Holders          {fmt_number(holders)}\n"
            f"  Market Cap       {fmt_naira(cap)}\n"
            f"  Volume Today     {fmt_naira(volume)}\n"
            f"  Tx Today         {fmt_number(tx_count)}\n"
            f"  Blockchain       TON\n\n"
            f"{DIVIDER}\n"
            f"  {BRAND} {STAR}"
        )

        try:
            await loading.edit_text(text, reply_markup=home_button_keyboard(), disable_web_page_preview=True)
        except TelegramBadRequest:
            await message.answer(text, reply_markup=home_button_keyboard(), disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"/price error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /stats
# =====================================================================

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show platform statistics."""
    try:
        stats = get_all_stats()
        holders = int(stats.get("total_holders", 0))
        circulating = float(stats.get("circulating_supply", 0))
        volume = float(stats.get("daily_volume_ngn", 0))
        tx_count = int(stats.get("daily_tx_count", 0))
        fees = float(stats.get("total_fees_sidi", 0))
        supply_pct = (circulating / 10_000_000_000) * 100

        text = (
            f"{STAR} <b>Sidicoin Network Stats</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  Total Supply     10,000,000,000 SIDI\n"
            f"  Circulating      {fmt_number(circulating)} SIDI ({supply_pct:.4f}%)\n"
            f"  Holders          {fmt_number(holders)}\n"
            f"  Tx Today         {fmt_number(tx_count)}\n"
            f"  Volume Today     {fmt_naira(volume)}\n"
            f"  Fees Collected   {fmt_naira(sidi_to_naira(fees))}\n\n"
            f"  Blockchain: TON  |  Ticker: SIDI  |  {fmt_naira(SIDI_PRICE_NGN)}/SIDI\n\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=home_button_keyboard())

    except Exception as e:
        logger.error(f"/stats error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /settings
# =====================================================================

@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Show account settings."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        joined = fmt_date(user.get("joined_date", 0))
        bank = user.get("bank_name", "")
        account = user.get("bank_account", "")
        account_name = user.get("bank_account_name", "")
        bank_display = f"{bank} \u2014 {account} \u2014 {account_name}" if bank and account else "Not set"
        wallet = user.get("wallet_address", "")[:20] + "..." if user.get("wallet_address") else "N/A"

        text = (
            f"{STAR} <b>Account Settings</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f464 {_safe_escape(user.get('full_name', ''))} (@{user.get('username', '')})\n"
            f"  \U0001f3c6 {_account_badge(user)} Account\n"
            f"  \U0001f4c5 Member since {joined}\n"
            f"  \U0001f3e6 Bank: {bank_display}\n"
            f"  \U0001f4ce TON Wallet: <code>{wallet}</code>\n\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=settings_keyboard())

    except Exception as e:
        logger.error(f"/settings error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /help
# =====================================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Show all commands organized by category."""
    text = (
        f"{STAR} <b>Sidicoin Commands</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  <b>\U0001f48e Wallet</b>\n"
        f"  /balance \u2014 Check your SIDI balance\n"
        f"  /settings \u2014 Account & bank settings\n\n"
        f"  <b>\U0001f4e4 Transfers</b>\n"
        f"  /send \u2014 Send SIDI to anyone\n"
        f"  /send @user 500 \u2014 Quick send\n"
        f"  /contacts \u2014 Saved contacts\n\n"
        f"  <b>\U0001f4b0 Money</b>\n"
        f"  /buy \u2014 Buy SIDI with Naira\n"
        f"  /sell \u2014 Cash out to bank\n"
        f"  /history \u2014 Transaction history\n\n"
        f"  <b>\U0001f381 Earn</b>\n"
        f"  /checkin \u2014 Daily free SIDI\n"
        f"  /refer \u2014 Earn 50 SIDI per referral\n"
        f"  /premium \u2014 Lower fees & higher limits\n\n"
        f"  <b>\U0001f4ca Market</b>\n"
        f"  /price \u2014 SIDI price & market data\n"
        f"  /stats \u2014 Platform statistics\n"
        f"  /leaderboard \u2014 Top holders\n\n"
        f"  <b>\u2139\ufe0f Info</b>\n"
        f"  /about \u2014 About Sidicoin\n"
        f"  /help \u2014 This menu\n\n"
        f"{DIVIDER}\n"
        f"  {BRAND} {STAR}"
    )
    await message.answer(text, reply_markup=help_keyboard(), disable_web_page_preview=True)


# =====================================================================
#  /about
# =====================================================================

@router.message(Command("about"))
async def cmd_about(message: Message):
    """About Sidicoin."""
    text = (
        f"{STAR} <b>About Sidicoin</b>\n\n"
        f"Sidicoin (SIDI) is a cryptocurrency built on the TON "
        f"blockchain with one mission \u2014 make financial transfers "
        f"across Africa instant, free and accessible to everyone.\n\n"
        f"{DIVIDER}\n\n"
        f"  \u2022 No bank account required\n"
        f"  \u2022 No crypto knowledge needed\n"
        f"  \u2022 No hidden fees on transfers\n"
        f"  \u2022 Just Telegram and a @username\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"  Supply       10,000,000,000 SIDI\n"
        f"  Price        {fmt_naira(25)} per SIDI\n"
        f"  Blockchain   TON\n"
        f"  Ticker       SIDI\n\n"
        f"{DIVIDER}\n\n"
        f"  Built for Africa. Going global {STAR}\n\n"
        f"  {BRAND}"
    )
    await message.answer(text, reply_markup=home_button_keyboard(), disable_web_page_preview=True)


# =====================================================================
#  ADMIN COMMANDS
# =====================================================================

def _is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_TELEGRAM_ID


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message):
    if not _is_admin(message.from_user.id):
        return
    stats = get_all_stats()
    user_count = len(get_all_user_ids())
    holders = int(stats.get("total_holders", 0))
    circulating = float(stats.get("circulating_supply", 0))
    volume = float(stats.get("daily_volume_ngn", 0))
    tx_count = int(stats.get("daily_tx_count", 0))
    fees = float(stats.get("total_fees_sidi", 0))
    text = (
        f"\U0001f6e1\ufe0f <b>Admin Dashboard</b>\n\n"
        f"Total Users: {fmt_number(user_count)}\n"
        f"Active Holders: {fmt_number(holders)}\n"
        f"Circulating: {fmt_number(circulating)} SIDI\n"
        f"Daily Volume: {fmt_naira(volume)}\n"
        f"Daily Tx: {fmt_number(tx_count)}\n"
        f"Fees: {fmt_number(fees)} SIDI ({fmt_naira(sidi_to_naira(fees))})\n"
        f"Fee Wallet: <code>{SIDI_FEE_WALLET or 'Not set'}</code>"
    )
    await message.answer(text)


@router.message(Command("admin_user"))
async def cmd_admin_user(message: Message):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: /admin_user @username")
        return
    username = clean_username(parts[1])
    user = find_user_by_username(username)
    if not user:
        await message.answer(f"User @{username} not found.")
        return
    import json
    safe_user = {k: v for k, v in user.items() if k != "private_key"}
    safe_user["transactions"] = f"[{len(user.get('transactions', []))} items]"
    safe_user["saved_contacts"] = f"[{len(user.get('saved_contacts', []))} items]"
    text = f"\U0001f6e1\ufe0f <b>User: @{username}</b>\n\n<code>{json.dumps(safe_user, indent=2, default=str)[:3800]}</code>"
    await message.answer(text)


@router.message(Command("admin_credit"))
async def cmd_admin_credit(message: Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer("Usage: /admin_credit @username amount")
        return
    username = clean_username(parts[1])
    try:
        amount = float(parts[2])
    except ValueError:
        await message.answer("Invalid amount.")
        return
    user = find_user_by_username(username)
    if not user:
        await message.answer(f"User @{username} not found.")
        return
    update_balance(user["telegram_id"], amount)
    add_transaction(user["telegram_id"], {
        "type": "bonus", "amount": amount,
        "description": "Admin credit",
        "timestamp": int(time.time()),
        "reference": generate_tx_reference(),
    })
    increment_stat("circulating_supply", amount)
    await message.answer(f"\u2705 Credited {fmt_number(amount)} SIDI to @{username}")
    await notify_user(
        bot, user["telegram_id"],
        f"\U0001f48e +<b>{fmt_number(amount)} SIDI</b> has been added to your wallet {STAR}"
    )


@router.message(Command("admin_debit"))
async def cmd_admin_debit(message: Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer("Usage: /admin_debit @username amount")
        return
    username = clean_username(parts[1])
    try:
        amount = float(parts[2])
    except ValueError:
        await message.answer("Invalid amount.")
        return
    user = find_user_by_username(username)
    if not user:
        await message.answer(f"User @{username} not found.")
        return
    success = update_balance(user["telegram_id"], -amount)
    if not success:
        await message.answer(f"Insufficient balance for @{username}")
        return
    add_transaction(user["telegram_id"], {
        "type": "debit", "amount": amount,
        "description": "Admin debit",
        "timestamp": int(time.time()),
        "reference": generate_tx_reference(),
    })
    await message.answer(f"\u2705 Debited {fmt_number(amount)} SIDI from @{username}")


@router.message(Command("admin_ban"))
async def cmd_admin_ban(message: Message):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: /admin_ban @username")
        return
    username = clean_username(parts[1])
    user = find_user_by_username(username)
    if not user:
        await message.answer(f"User @{username} not found.")
        return
    user["is_banned"] = True
    save_user(user["telegram_id"], user)
    await message.answer(f"\U0001f6ab @{username} has been banned.")


@router.message(Command("admin_unban"))
async def cmd_admin_unban(message: Message):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: /admin_unban @username")
        return
    username = clean_username(parts[1])
    user = find_user_by_username(username)
    if not user:
        await message.answer(f"User @{username} not found.")
        return
    user["is_banned"] = False
    save_user(user["telegram_id"], user)
    await message.answer(f"\u2705 @{username} has been unbanned.")


@router.message(Command("admin_broadcast"))
async def cmd_admin_broadcast(message: Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /admin_broadcast Your message here")
        return
    broadcast_text = parts[1]
    user_ids = get_all_user_ids()
    sent = 0
    failed = 0
    status_msg = await message.answer(f"\U0001f4e1 Broadcasting to {len(user_ids)} users...")
    for uid in user_ids:
        try:
            success = await notify_user(bot, uid, broadcast_text)
            sent += 1 if success else 0
            failed += 0 if success else 1
        except Exception:
            failed += 1
    try:
        await status_msg.edit_text(f"\u2705 Broadcast complete\nSent: {sent} | Failed: {failed}")
    except TelegramBadRequest:
        pass


@router.message(Command("admin_fees"))
async def cmd_admin_fees(message: Message):
    if not _is_admin(message.from_user.id):
        return
    fees = get_stat("total_fees_sidi")
    await message.answer(
        f"\U0001f4b0 <b>Total Fees</b>\n\n"
        f"{fmt_number(fees)} SIDI ({fmt_naira(sidi_to_naira(fees))})\n"
        f"Wallet: <code>{SIDI_FEE_WALLET or 'Not set'}</code>"
    )


@router.message(Command("admin_pending"))
async def cmd_admin_pending(message: Message):
    if not _is_admin(message.from_user.id):
        return
    user_ids = get_all_user_ids()
    pending = []
    for uid in user_ids:
        user = get_user(uid)
        if user and user.get("pending_action"):
            pending.append(f"@{user.get('username', uid)}: {user['pending_action']}")
    if not pending:
        await message.answer("No pending transactions.")
        return
    text = "\U0001f552 <b>Pending Actions</b>\n\n" + "\n".join(pending[:50])
    await message.answer(text)


# =====================================================================
#  CALLBACK QUERY HANDLERS
# =====================================================================

@router.callback_query(F.data == "cmd_home")
async def cb_home(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        naira = sidi_to_naira(balance)
        name = user.get("full_name", "there")
        badge = _account_badge(user)
        text = (
            f"{STAR} <b>{_safe_escape(name)}</b>\n\n"
            f"  \U0001f48e <b>{fmt_number(balance)} SIDI</b>\n"
            f"  \U0001f4b5 {fmt_naira(naira)}\n"
            f"  \U0001f3c6 {badge}"
        )
        await callback.message.edit_text(text, reply_markup=home_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_home error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_balance")
async def cb_balance(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await _show_balance(callback.message, user)
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_balance error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_send")
async def cb_send(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await callback.message.edit_text(
            f"{STAR} <b>Send SIDI</b>\n\n"
            f"Who would you like to send to?\n\n"
            f"Enter their Telegram @username:",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(callback.from_user.id, "send_username")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_send error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_buy")
async def cb_buy(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        is_prem = check_premium_status(user)
        fee_label = "0.8%" if is_prem else "1.5%"
        await callback.message.edit_text(
            f"{STAR} <b>Buy SIDI</b>\n\n"
            f"How much would you like to buy?\n\n"
            f"  <code>500</code>        \u2192 500 SIDI\n"
            f"  <code>2000 SIDI</code>  \u2192 2,000 SIDI\n"
            f"  <code>5000 NGN</code>   \u2192 {fmt_naira(5000)} worth\n"
            f"  <code>5k</code>         \u2192 5,000 SIDI\n\n"
            f"Fee: {fee_label}",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(callback.from_user.id, "buy_amount")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_buy error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_sell")
async def cb_sell(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        if balance <= 0:
            await callback.message.edit_text(
                f"You don't have any SIDI to cash out.\nBuy some with /buy {STAR}",
                reply_markup=home_button_keyboard(),
            )
            await callback.answer()
            return
        is_prem = check_premium_status(user)
        fee_label = "0.8%" if is_prem else "1.5%"
        await callback.message.edit_text(
            f"{STAR} <b>Cash Out SIDI</b>\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?\n"
            f"Fee: {fee_label}",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(callback.from_user.id, "sell_amount")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_sell error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_refer")
async def cb_refer(callback: CallbackQuery, bot: Bot):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        bot_username = await _get_bot_username(bot)
        ref_link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}"
        count = int(user.get("referral_count", 0))
        earned = float(user.get("referral_earnings", 0))
        text = (
            f"{STAR} <b>Refer & Earn</b>\n\n"
            f"Your link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f91d Per signup    +<b>50 SIDI</b>\n"
            f"  \U0001f4b3 Per purchase  +<b>10 SIDI</b>\n\n"
            f"  \U0001f465 Referrals: <b>{count}</b>\n"
            f"  \U0001f48e Earned: <b>{fmt_number(earned)} SIDI</b>\n\n"
            f"{DIVIDER}"
        )
        await callback.message.edit_text(text, reply_markup=refer_keyboard(ref_link))
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_refer error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_help")
async def cb_help(callback: CallbackQuery):
    try:
        text = (
            f"{STAR} <b>Sidicoin Commands</b>\n\n"
            f"  /balance \u2014 Wallet\n"
            f"  /send \u2014 Send SIDI\n"
            f"  /buy \u2014 Buy SIDI\n"
            f"  /sell \u2014 Cash out\n"
            f"  /checkin \u2014 Daily reward\n"
            f"  /refer \u2014 Earn free SIDI\n"
            f"  /history \u2014 Transactions\n"
            f"  /premium \u2014 Upgrade\n"
            f"  /price \u2014 Market data\n"
            f"  /about \u2014 About Sidicoin\n\n"
            f"  {BRAND} {STAR}"
        )
        await callback.message.edit_text(text, reply_markup=help_keyboard(), disable_web_page_preview=True)
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "cmd_settings")
async def cb_settings(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        joined = fmt_date(user.get("joined_date", 0))
        bank = user.get("bank_name", "")
        account = user.get("bank_account", "")
        account_name = user.get("bank_account_name", "")
        bank_display = f"{bank} \u2014 {account} \u2014 {account_name}" if bank and account else "Not set"
        text = (
            f"{STAR} <b>Account Settings</b>\n\n"
            f"  \U0001f464 {_safe_escape(user.get('full_name', ''))} (@{user.get('username', '')})\n"
            f"  \U0001f3c6 {_account_badge(user)}\n"
            f"  \U0001f4c5 Since {joined}\n"
            f"  \U0001f3e6 {bank_display}"
        )
        await callback.message.edit_text(text, reply_markup=settings_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_settings error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_history")
async def cb_history(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await _show_history(callback, user, "all")
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_history error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_checkin")
async def cb_checkin(callback: CallbackQuery):
    """Daily check-in from inline button."""
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        success, bonus_msg, amount, streak = process_checkin(callback.from_user.id)
        if not success:
            await callback.answer(bonus_msg, show_alert=True)
            return
        user = get_user(callback.from_user.id)
        balance = float(user.get("sidi_balance", 0))
        fires = streak_fire(streak)
        text = (
            f"{STAR} <b>Daily Reward Claimed!</b>\n\n"
            f"+<b>{fmt_number(amount)} SIDI</b>\n\n"
            f"  {fires}  Streak: <b>{streak} days</b>\n"
            f"  \U0001f48e  Balance: <b>{fmt_number(balance)} SIDI</b>\n"
            f"{bonus_msg}"
        )
        await callback.message.edit_text(text, reply_markup=home_keyboard())
        await callback.answer(f"+{fmt_number(amount)} SIDI!")
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_checkin error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_leaderboard")
async def cb_leaderboard(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await _show_leaderboard(callback, user, is_edit=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_leaderboard error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cmd_premium")
async def cb_premium(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        if check_premium_status(user):
            expiry = int(user.get("premium_expiry", 0))
            await callback.message.edit_text(
                f"{STAR} <b>You're Premium {STAR}</b>\n\nExpires: {fmt_timestamp(expiry)}",
                reply_markup=home_keyboard(),
            )
            await callback.answer()
            return
        text = (
            f"{STAR} <b>Sidicoin Premium</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>Feature</b>          <b>Free</b>     <b>Premium</b>\n\n"
            f"  Daily Limit       50K      <b>500K</b>\n"
            f"  Buy/Sell Fee      1.5%     <b>0.8%</b>\n"
            f"  Daily Check-in    10       <b>25 SIDI</b>\n"
            f"  Badge             \u2014        <b>{STAR}</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>{fmt_naira(1500)} per month</b>"
        )
        await callback.message.edit_text(text, reply_markup=premium_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# -- History filter callbacks --

@router.callback_query(F.data.startswith("history_"))
async def cb_history_filter(callback: CallbackQuery):
    try:
        filter_type = callback.data.replace("history_", "")
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await _show_history(callback, user, filter_type)
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_history_filter error: {e}")
        await callback.answer("Something went wrong")


# -- Onboarding callbacks --

@router.callback_query(F.data == "onboard_2")
async def cb_onboard_2(callback: CallbackQuery):
    try:
        text = (
            f"{STAR} <b>How It Works</b>\n\n"
            f"Send money to anyone in Africa\n"
            f"using just their Telegram username.\n\n"
            f"<b>Example:</b>\n"
            f"<code>/send @john 5000</code>\n\n"
            f"That's it. No bank details.\n"
            f"No routing numbers. No stress {STAR}"
        )
        await callback.message.edit_text(text, reply_markup=onboarding_step2_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "onboard_3")
async def cb_onboard_3(callback: CallbackQuery):
    try:
        text = (
            f"{STAR} <b>Get Started</b>\n\n"
            f"You have <b>80 SIDI</b> ({fmt_naira(2000)}) ready to go.\n\n"
            f"\U0001f4b3 <b>Buy more SIDI</b> with Naira\n"
            f"\U0001f381 <b>Refer friends</b> to earn 50 SIDI each\n"
            f"\u2705 <b>Check in daily</b> for free SIDI\n\n"
            f"What's your first move?"
        )
        await callback.message.edit_text(text, reply_markup=onboarding_step3_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# =====================================================================
#  SEND FLOW CALLBACKS
# =====================================================================

@router.callback_query(F.data == "send_confirm")
async def cb_send_confirm(callback: CallbackQuery, bot: Bot):
    """Execute confirmed transfer."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "send_confirm" or not data:
            await callback.answer("No pending transfer found")
            return

        try:
            await callback.message.edit_text("\U0001f4e1 Processing your transfer...")
        except TelegramBadRequest:
            pass

        sender = get_user(callback.from_user.id)
        recipient_id = data["recipient_id"]
        amount = float(data["amount"])
        recipient_username = data.get("recipient_username", "")
        recipient_name = data.get("recipient_name", "")

        # Suspicious activity check
        if is_large_transfer(amount):
            count = track_large_transfer(callback.from_user.id)
            if count > 3:
                await notify_admin(
                    bot,
                    f"\u26a0\ufe0f SUSPICIOUS: @{sender.get('username', '')} "
                    f"made {count} large transfers in 1 hour\n"
                    f"Latest: {fmt_number(amount)} SIDI to @{recipient_username}"
                )

        # Execute transfer
        reference = generate_tx_reference()
        success = transfer_sidi(callback.from_user.id, recipient_id, amount)

        if not success:
            await callback.message.edit_text(
                f"Transfer failed \u2014 insufficient balance or error. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        increment_rate_count(callback.from_user.id)

        # Record transactions
        now = int(time.time())
        sender_username = sender.get("username", "")

        add_transaction(callback.from_user.id, {
            "type": "send", "amount": amount,
            "other_username": recipient_username,
            "description": f"Sent to @{recipient_username}",
            "timestamp": now, "reference": reference,
        })
        add_transaction(recipient_id, {
            "type": "receive", "amount": amount,
            "other_username": sender_username,
            "description": f"Received from @{sender_username}",
            "timestamp": now, "reference": reference,
        })

        clear_pending_action(callback.from_user.id)

        # Build receipt
        naira = sidi_to_naira(amount)
        receipt = generate_receipt("Transfer", sender_username, recipient_username, amount, 0, reference)
        sender = get_user(callback.from_user.id)
        new_balance = float(sender.get("sidi_balance", 0))

        sender_text = (
            f"{STAR} <b>Transfer Successful!</b>\n\n"
            f"Sent <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)}) to @{recipient_username}\n"
            f"New Balance: <b>{fmt_number(new_balance)} SIDI</b>\n"
            f"{receipt}"
        )

        try:
            await callback.message.edit_text(sender_text, reply_markup=after_send_keyboard(), disable_web_page_preview=True)
        except TelegramBadRequest:
            pass

        # Notify recipient
        recipient = get_user(recipient_id)
        r_balance = float(recipient.get("sidi_balance", 0)) if recipient else 0

        recipient_text = (
            f"{STAR} <b>You received money!</b>\n\n"
            f"  \U0001f4b0 +<b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n"
            f"  From: @{sender_username}\n"
            f"  Speed: Instant \u26a1\n"
            f"  Balance: <b>{fmt_number(r_balance)} SIDI</b>\n\n"
            f"  Ref: <code>{reference}</code>"
        )
        await notify_user(bot, recipient_id, recipient_text, reply_markup=received_money_keyboard())

        # Smart suggestions
        if new_balance < 50:
            await callback.message.answer(
                f"\U0001f4a1 Balance getting low. Top up with /buy {STAR}",
                reply_markup=home_button_keyboard(),
            )

        # Milestones
        tx_count = _transfer_count(sender)
        name = sender.get("full_name", "there")
        if tx_count == 1:
            await callback.message.answer(
                f"\U0001f389 Your first Sidicoin transfer, {_safe_escape(name)}! "
                f"Welcome to the future of African finance {STAR}"
            )
        elif tx_count == 10:
            await callback.message.answer(
                f"\U0001f525 10 transfers done! True Sidicoin power user, {_safe_escape(name)} {STAR}"
            )

        await callback.answer("Transfer successful!")

    except Exception as e:
        logger.error(f"send_confirm error: {e}", exc_info=True)
        try:
            await callback.message.edit_text(
                f"Something went wrong. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()


@router.callback_query(F.data == "send_cancel")
async def cb_send_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text(f"Transfer cancelled {STAR}", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# =====================================================================
#  BUY FLOW CALLBACKS
# =====================================================================

@router.callback_query(F.data == "buy_proceed")
async def cb_buy_proceed(callback: CallbackQuery):
    """Generate Korapay bank transfer account for payment."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "buy_confirm" or not data:
            await callback.answer("No pending purchase found")
            return

        try:
            await callback.message.edit_text("\U0001f504 Generating your payment details...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)
        total_ngn = float(data["total_ngn"])
        sidi_amount = float(data["sidi_amount"])
        reference = generate_tx_reference()

        # Create bank transfer charge via Korapay
        result = await create_bank_transfer_charge(
            reference=reference,
            amount=total_ngn,
            customer_name=user.get("full_name", "Sidicoin User"),
        )

        if not result.get("success"):
            error_msg = result.get("message", "Unknown error")
            logger.error(f"Korapay bank transfer failed: {error_msg}")
            await callback.message.edit_text(
                f"Could not generate payment details.\n\n"
                f"Error: {error_msg}\n\n"
                f"Please try again in a moment {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        # Store pending payment for webhook matching
        store_pending_payment(reference, {
            "telegram_id": str(callback.from_user.id),
            "sidi_amount": sidi_amount,
            "ngn_amount": total_ngn,
            "reference": reference,
            "type": "buy",
        })

        # Update pending action
        set_pending_action(callback.from_user.id, "buy_payment", {
            **data,
            "reference": reference,
            "bank_name": result.get("bank_name", ""),
            "account_number": result.get("account_number", ""),
        })

        bank_name = result.get("bank_name", "Wema Bank")
        acct_num = result.get("account_number", "")

        payment_text = (
            f"{STAR} <b>Make Your Payment</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f3e6 Bank:    <b>{bank_name}</b>\n"
            f"  \U0001f4b3 Account: <code>{acct_num}</code>\n"
            f"  \U0001f4b5 Amount:  <b>{fmt_naira(total_ngn)}</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \u23f0 Expires in 30 minutes\n\n"
            f"  Send <b>exactly</b> {fmt_naira(total_ngn)} to the\n"
            f"  account above. We will notify you\n"
            f"  once your payment is confirmed {STAR}"
        )
        await callback.message.edit_text(payment_text, reply_markup=buy_payment_keyboard())
        await callback.answer()

    except Exception as e:
        logger.error(f"buy_proceed error: {e}", exc_info=True)
        try:
            await callback.message.edit_text(
                f"Something went wrong. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()


@router.callback_query(F.data == "buy_paid")
async def cb_buy_paid(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            f"{STAR} <b>Waiting for confirmation</b>\n\n"
            f"We're checking for your payment.\n"
            f"This usually takes 1-5 minutes.\n\n"
            f"You'll be notified automatically\n"
            f"once your payment is confirmed.\n\n"
            f"If you haven't paid yet, please\n"
            f"complete the transfer now {STAR}",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "buy_cancel")
async def cb_buy_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text(f"Purchase cancelled {STAR}", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# =====================================================================
#  SELL FLOW CALLBACKS
# =====================================================================

@router.callback_query(F.data == "sell_confirm")
async def cb_sell_confirm(callback: CallbackQuery, bot: Bot):
    """Execute cashout."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "sell_confirm" or not data:
            await callback.answer("No pending cashout found")
            return

        try:
            await callback.message.edit_text("\U0001f4b8 Processing your cashout...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)

        # Check 24hr hold
        hold_until = int(user.get("cashout_hold_until", 0))
        if hold_until > int(time.time()):
            remaining_secs = hold_until - int(time.time())
            hours = remaining_secs // 3600
            mins = (remaining_secs % 3600) // 60
            await callback.message.edit_text(
                f"\u23f3 <b>24-Hour Hold Active</b>\n\n"
                f"Time remaining: <b>{hours}h {mins}m</b>\n\n"
                f"This is a security measure for new accounts.\n"
                f"Your SIDI is safe in your wallet {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        sidi_amount = float(data["sidi_amount"])
        net_ngn = float(data["net_ngn"])
        bank_code = data.get("bank_code", "")
        bank_account = data.get("bank_account", "")
        bank_name = data.get("bank_name", "")
        account_name = data.get("account_name", "")
        fee_sidi = float(data.get("fee_sidi", 0))

        # Deduct SIDI
        total_deduction = sidi_amount + fee_sidi
        success = update_balance(callback.from_user.id, -total_deduction)
        if not success:
            await callback.message.edit_text(
                f"Insufficient balance for cashout. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        if fee_sidi > 0:
            increment_stat("total_fees_sidi", fee_sidi)

        # Process payout via Korapay
        reference = generate_tx_reference()
        payout_result = await process_payout(
            reference=reference,
            amount=net_ngn,
            bank_code=bank_code,
            account_number=bank_account,
            account_name=account_name,
        )

        now = int(time.time())
        add_transaction(callback.from_user.id, {
            "type": "sell", "amount": sidi_amount,
            "description": f"{bank_name} \u2014 {account_name}",
            "timestamp": now, "reference": reference,
        })

        user = get_user(callback.from_user.id)
        user["total_sold_ngn"] = float(user.get("total_sold_ngn", 0)) + net_ngn
        save_user(callback.from_user.id, user)
        clear_pending_action(callback.from_user.id)

        if payout_result.get("success"):
            receipt_text = (
                f"{STAR} <b>Cashout Successful!</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \U0001f4b0 <b>{fmt_naira(net_ngn)}</b> sent to\n"
                f"  \U0001f3e6 {bank_name}\n"
                f"  \U0001f464 {_safe_escape(account_name)}\n"
                f"  \U0001f4cb Ref: <code>{reference}</code>\n"
                f"  \u26a1 Status: Processing\n\n"
                f"{DIVIDER}\n\n"
                f"  Usually arrives within minutes {STAR}"
            )
        else:
            receipt_text = (
                f"{STAR} <b>Cashout Submitted</b>\n\n"
                f"Your cashout of {fmt_naira(net_ngn)} to {bank_name} "
                f"has been submitted.\n"
                f"Ref: <code>{reference}</code>\n\n"
                f"We'll notify you once complete {STAR}"
            )

        await callback.message.edit_text(receipt_text, reply_markup=after_sell_keyboard())

        # First cashout milestone
        sell_txns = [t for t in user.get("transactions", []) if t.get("type") == "sell"]
        if len(sell_txns) <= 1:
            await callback.message.answer(
                f"\U0001f4b0 First cashout done! That's your Sidicoin working for you {STAR}"
            )

        await callback.answer("Cashout processed!")

    except Exception as e:
        logger.error(f"sell_confirm error: {e}", exc_info=True)
        try:
            await callback.message.edit_text(
                f"Something went wrong. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()


@router.callback_query(F.data == "sell_bank_yes")
async def cb_sell_bank_yes(callback: CallbackQuery):
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "sell_bank_check":
            await callback.answer("No pending action")
            return
        user = get_user(callback.from_user.id)
        sidi_amount = float(data["sidi_amount"])
        is_premium = check_premium_status(user)
        fee_sidi = calculate_fee(sidi_amount, is_premium, "sell")
        fee_ngn = sidi_to_naira(fee_sidi)
        gross_ngn = sidi_to_naira(sidi_amount)
        net_ngn = gross_ngn - fee_ngn
        fee_pct = "0.8%" if is_premium else "1.5%"

        set_pending_action(callback.from_user.id, "sell_confirm", {
            **data,
            "bank_code": user.get("bank_code", ""),
            "bank_account": user.get("bank_account", ""),
            "bank_name": user.get("bank_name", ""),
            "account_name": user.get("bank_account_name", ""),
            "fee_sidi": fee_sidi, "net_ngn": net_ngn,
        })

        text = (
            f"{STAR} <b>Cashout Summary</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  Selling    <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"  Gross      {fmt_naira(gross_ngn)}\n"
            f"  Fee ({fee_pct})  {fmt_naira(fee_ngn)}\n"
            f"  Net payout <b>{fmt_naira(net_ngn)}</b>\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  \U0001f3e6 {user.get('bank_name', '')}\n"
            f"  {user.get('bank_account', '')} \u2014 {user.get('bank_account_name', '')}\n\n"
            f"{DIVIDER}\n\n"
            f"Confirm cashout?"
        )
        await callback.message.edit_text(text, reply_markup=sell_confirm_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"sell_bank_yes error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "sell_change_bank")
async def cb_sell_change_bank(callback: CallbackQuery):
    try:
        action, data = get_pending_action(callback.from_user.id)
        set_pending_action(callback.from_user.id, "sell_bank_name", data)
        await callback.message.edit_text(
            f"{STAR} <b>Enter Bank Details</b>\n\n"
            f"What bank do you use?\n\n"
            f"Type the bank name:\n"
            f"e.g. GTBank, Access, Kuda, OPay, FirstBank",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "sell_cancel")
async def cb_sell_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text(f"Cashout cancelled {STAR}", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# =====================================================================
#  PREMIUM CALLBACKS
# =====================================================================

@router.callback_query(F.data == "premium_upgrade")
async def cb_premium_upgrade(callback: CallbackQuery):
    try:
        try:
            await callback.message.edit_text("\U0001f504 Generating your payment details...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)
        reference = generate_tx_reference()
        amount = 1500.0

        result = await create_bank_transfer_charge(
            reference=reference,
            amount=amount,
            customer_name=user.get("full_name", "Sidicoin User"),
            narration="Sidicoin Premium Subscription",
        )

        if not result.get("success"):
            await callback.message.edit_text(
                f"Could not generate payment details. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
            await callback.answer()
            return

        store_pending_payment(reference, {
            "telegram_id": str(callback.from_user.id),
            "type": "premium",
            "ngn_amount": amount,
            "reference": reference,
        })

        set_pending_action(callback.from_user.id, "premium_payment", {
            "reference": reference,
        })

        text = (
            f"{STAR} <b>Premium Payment</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f3e6 Bank:    <b>{result.get('bank_name', '')}</b>\n"
            f"  \U0001f4b3 Account: <code>{result.get('account_number', '')}</code>\n"
            f"  \U0001f4b5 Amount:  <b>{fmt_naira(amount)}</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \u23f0 Expires in 30 minutes\n"
            f"  Send exactly {fmt_naira(amount)} {STAR}"
        )
        await callback.message.edit_text(text, reply_markup=premium_payment_keyboard())
        await callback.answer()

    except Exception as e:
        logger.error(f"premium_upgrade error: {e}", exc_info=True)
        try:
            await callback.message.edit_text(
                f"Something went wrong. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
        except TelegramBadRequest:
            pass
        await callback.answer()


@router.callback_query(F.data == "premium_paid")
async def cb_premium_paid(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            f"{STAR} Checking for your payment...\n\n"
            f"You'll be notified once confirmed {STAR}",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# =====================================================================
#  MISC CALLBACKS
# =====================================================================

@router.callback_query(F.data.startswith("contact_send_"))
async def cb_contact_send(callback: CallbackQuery):
    try:
        recipient_id = callback.data.replace("contact_send_", "")
        recipient = get_user(recipient_id)
        if not recipient:
            await callback.answer("Contact not found")
            return
        set_pending_action(callback.from_user.id, "send_amount", {
            "recipient_id": recipient_id,
            "recipient_username": recipient.get("username", ""),
            "recipient_name": recipient.get("full_name", ""),
        })
        r_name = recipient.get("full_name", recipient.get("username", ""))
        await callback.message.edit_text(
            f"{STAR} <b>Send to {_safe_escape(r_name)}</b>\n\n"
            f"How much SIDI would you like to send?",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"contact_send error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "refer_copy")
async def cb_refer_copy(callback: CallbackQuery, bot: Bot):
    try:
        user = get_user(callback.from_user.id)
        bot_username = await _get_bot_username(bot)
        ref_link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}"
        await callback.answer(f"Link: {ref_link}", show_alert=True)
    except Exception:
        await callback.answer("Could not copy link")


@router.callback_query(F.data == "settings_bank")
async def cb_settings_bank(callback: CallbackQuery):
    try:
        set_pending_action(callback.from_user.id, "settings_bank_name")
        await callback.message.edit_text(
            f"{STAR} <b>Update Bank Details</b>\n\n"
            f"What bank do you use?\n\n"
            f"Type the bank name:\n"
            f"e.g. GTBank, Access, Kuda, OPay, FirstBank",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "settings_wallet")
async def cb_settings_wallet(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("No wallet found")
            return
        address = user.get("wallet_address", "N/A")
        await callback.answer(f"TON: {address}", show_alert=True)
    except Exception:
        await callback.answer("Could not get wallet")


@router.callback_query(F.data.startswith("leaderboard_"))
async def cb_leaderboard_type(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        await _show_leaderboard(callback, user, is_edit=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"leaderboard callback error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data == "cancel_action")
async def cb_cancel_action(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text(f"Action cancelled {STAR}", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# =====================================================================
#  TEXT MESSAGE HANDLER (multi-step flows + AI)
# =====================================================================

@router.message(F.text)
async def handle_text_message(message: Message, bot: Bot):
    """Handle all non-command text messages."""
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        sanitized = sanitize_input(text)

        action, data = get_pending_action(user_id)

        if action:
            await _handle_pending_action(message, bot, action, data, sanitized)
            return

        # No pending action -- use AI assistant
        loading = await message.answer(f"{STAR} Sidi is thinking...")

        intent = detect_intent(sanitized)
        if intent:
            ai_response = await get_ai_response(sanitized, message.from_user.first_name or "User")
            response_text = f"{ai_response}\n\n\U0001f4a1 Try: {intent}"
        else:
            ai_response = await get_ai_response(sanitized, message.from_user.first_name or "User")
            response_text = ai_response

        try:
            await loading.edit_text(response_text, reply_markup=home_button_keyboard())
        except TelegramBadRequest:
            await message.answer(response_text, reply_markup=home_button_keyboard())

    except Exception as e:
        logger.error(f"text_message error: {e}", exc_info=True)
        await message.answer(
            f"Something went wrong. Please try again {STAR}",
            reply_markup=home_button_keyboard(),
        )


async def _handle_pending_action(message: Message, bot: Bot, action: str, data: dict, text: str):
    """Route pending multi-step conversation flows."""
    user_id = message.from_user.id

    # -- Send flow --
    if action == "send_username":
        if not is_valid_username(text):
            await message.answer(
                "That doesn't look like a valid username.\n"
                "Enter a Telegram @username (e.g. @john):",
                reply_markup=cancel_keyboard(),
            )
            return

        clean = clean_username(text)
        recipient = find_user_by_username(clean)
        if not recipient:
            bot_username = await _get_bot_username(bot)
            invite_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
            await message.answer(
                f"@{clean} hasn't joined Sidicoin yet.\n\n"
                f"Invite them:\n<code>{invite_link}</code> {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(user_id)
            return

        if str(recipient["telegram_id"]) == str(user_id):
            await message.answer(f"You can't send SIDI to yourself {STAR}", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return

        set_pending_action(user_id, "send_amount", {
            "recipient_id": recipient["telegram_id"],
            "recipient_username": recipient.get("username", clean),
            "recipient_name": recipient.get("full_name", ""),
        })

        r_name = recipient.get("full_name", "")
        await message.answer(
            f"{STAR} Sending to @{recipient.get('username', clean)}"
            f"{f' ({_safe_escape(r_name)})' if r_name else ''}\n\n"
            f"How much SIDI would you like to send?",
            reply_markup=cancel_keyboard(),
        )

    elif action == "send_amount":
        valid, amount = is_valid_amount(text)
        if not valid or amount <= 0:
            await message.answer(
                "Please enter a valid amount (e.g. 500, 5k, N12500):",
                reply_markup=cancel_keyboard(),
            )
            return
        sender = get_user(user_id)
        await _process_send_flow(message, bot, sender, data.get("recipient_username", ""), amount)

    # -- Buy flow --
    elif action == "buy_amount":
        valid, sidi_amount = is_valid_amount(text)
        if not valid or sidi_amount <= 0:
            await message.answer(
                "Please enter a valid amount (e.g. 500, 5k, N12500):",
                reply_markup=cancel_keyboard(),
            )
            return

        user = get_user(user_id)
        is_premium = check_premium_status(user)
        naira_cost = sidi_to_naira(sidi_amount)
        fee_ngn = calculate_fee_naira(naira_cost, is_premium, "buy")
        total_ngn = naira_cost + fee_ngn
        fee_pct = "0.8%" if is_premium else "1.5%"

        set_pending_action(user_id, "buy_confirm", {
            "sidi_amount": sidi_amount,
            "naira_cost": naira_cost,
            "fee_ngn": fee_ngn,
            "total_ngn": total_ngn,
        })

        text = (
            f"{STAR} <b>Purchase Summary</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  You receive  <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"  Cost         {fmt_naira(naira_cost)}\n"
            f"  Fee ({fee_pct})    {fmt_naira(fee_ngn)}\n"
            f"  Total        <b>{fmt_naira(total_ngn)}</b>\n"
            f"  Method       Bank Transfer\n\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=buy_confirm_keyboard())

    # -- Sell flow --
    elif action == "sell_amount":
        valid, sidi_amount = is_valid_amount(text)
        if not valid or sidi_amount <= 0:
            await message.answer("Please enter a valid amount:", reply_markup=cancel_keyboard())
            return

        user = get_user(user_id)
        balance = float(user.get("sidi_balance", 0))
        if sidi_amount > balance:
            await message.answer(
                f"Insufficient balance. You have <b>{fmt_number(balance)} SIDI</b> {STAR}",
                reply_markup=cancel_keyboard(),
            )
            return

        if user.get("bank_account") and user.get("bank_name"):
            set_pending_action(user_id, "sell_bank_check", {"sidi_amount": sidi_amount})
            await message.answer(
                f"{STAR} <b>Cashout to:</b>\n\n"
                f"  \U0001f3e6 {user.get('bank_name', '')}\n"
                f"  {user.get('bank_account', '')} \u2014 {user.get('bank_account_name', '')}\n\n"
                f"Use this account?",
                reply_markup=sell_bank_confirm_keyboard(),
            )
        else:
            set_pending_action(user_id, "sell_bank_name", {"sidi_amount": sidi_amount})
            await message.answer(
                f"{STAR} <b>Enter Bank Details</b>\n\n"
                f"What bank do you use?\n"
                f"e.g. GTBank, Access, Kuda, OPay, FirstBank",
                reply_markup=cancel_keyboard(),
            )

    elif action == "sell_bank_name":
        bank_code = get_bank_code(text)
        if not bank_code:
            await message.answer(
                "Bank not recognized. Try again:\n"
                "e.g. GTBank, Access, Kuda, OPay, FirstBank, UBA, Zenith",
                reply_markup=cancel_keyboard(),
            )
            return
        set_pending_action(user_id, "sell_bank_account", {
            **data, "bank_name": text.strip().title(), "bank_code": bank_code,
        })
        await message.answer(
            f"{STAR} Bank: <b>{text.strip().title()}</b>\n\n"
            f"Enter your 10-digit account number:",
            reply_markup=cancel_keyboard(),
        )

    elif action == "sell_bank_account":
        if not is_valid_bank_account(text):
            await message.answer("Please enter a valid 10-digit account number:", reply_markup=cancel_keyboard())
            return

        loading = await message.answer("\U0001f3e6 Verifying account details...")
        bank_code = data.get("bank_code", "")
        account_number = text.strip()

        result = await verify_bank_account(bank_code, account_number)

        if not result.get("success"):
            try:
                await loading.edit_text(
                    f"Could not verify account: {result.get('message', 'Unknown error')}.\n"
                    f"Check and try again {STAR}",
                    reply_markup=cancel_keyboard(),
                )
            except TelegramBadRequest:
                pass
            return

        account_name = result.get("account_name", "")
        bank_name = data.get("bank_name", "")
        sidi_amount = float(data.get("sidi_amount", 0))

        update_bank_details(user_id, bank_name, bank_code, account_number, account_name)

        user = get_user(user_id)
        is_premium = check_premium_status(user)
        fee_sidi = calculate_fee(sidi_amount, is_premium, "sell")
        fee_ngn = sidi_to_naira(fee_sidi)
        gross_ngn = sidi_to_naira(sidi_amount)
        net_ngn = gross_ngn - fee_ngn
        fee_pct = "0.8%" if is_premium else "1.5%"

        set_pending_action(user_id, "sell_confirm", {
            **data, "bank_account": account_number, "account_name": account_name,
            "fee_sidi": fee_sidi, "net_ngn": net_ngn,
        })

        confirm_text = (
            f"{STAR} <b>Cashout Summary</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  Selling    <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"  Gross      {fmt_naira(gross_ngn)}\n"
            f"  Fee ({fee_pct})  {fmt_naira(fee_ngn)}\n"
            f"  Net payout <b>{fmt_naira(net_ngn)}</b>\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  \U0001f3e6 {bank_name}\n"
            f"  {account_number} \u2014 <b>{_safe_escape(account_name)}</b>\n\n"
            f"{DIVIDER}\n\nConfirm cashout?"
        )

        try:
            await loading.edit_text(confirm_text, reply_markup=sell_confirm_keyboard())
        except TelegramBadRequest:
            await message.answer(confirm_text, reply_markup=sell_confirm_keyboard())

    # -- Settings bank update --
    elif action == "settings_bank_name":
        bank_code = get_bank_code(text)
        if not bank_code:
            await message.answer("Bank not recognized. Try again:", reply_markup=cancel_keyboard())
            return
        set_pending_action(user_id, "settings_bank_account", {
            "bank_name": text.strip().title(), "bank_code": bank_code,
        })
        await message.answer(
            f"{STAR} Bank: <b>{text.strip().title()}</b>\n\nEnter your 10-digit account number:",
            reply_markup=cancel_keyboard(),
        )

    elif action == "settings_bank_account":
        if not is_valid_bank_account(text):
            await message.answer("Please enter a valid 10-digit account number:", reply_markup=cancel_keyboard())
            return

        loading = await message.answer("\U0001f3e6 Verifying account details...")
        bank_code = data.get("bank_code", "")
        account_number = text.strip()

        result = await verify_bank_account(bank_code, account_number)
        if not result.get("success"):
            try:
                await loading.edit_text(
                    f"Could not verify account. Check and try again {STAR}",
                    reply_markup=cancel_keyboard(),
                )
            except TelegramBadRequest:
                pass
            return

        account_name = result.get("account_name", "")
        bank_name = data.get("bank_name", "")
        update_bank_details(user_id, bank_name, bank_code, account_number, account_name)
        clear_pending_action(user_id)

        try:
            await loading.edit_text(
                f"\u2705 <b>Bank details updated!</b>\n\n"
                f"  \U0001f3e6 {bank_name}\n"
                f"  {account_number} \u2014 {_safe_escape(account_name)} {STAR}",
                reply_markup=settings_keyboard(),
            )
        except TelegramBadRequest:
            pass

    else:
        clear_pending_action(user_id)
        loading = await message.answer(f"{STAR} Sidi is thinking...")
        ai_response = await get_ai_response(text, message.from_user.first_name or "User")
        try:
            await loading.edit_text(ai_response, reply_markup=home_button_keyboard())
        except TelegramBadRequest:
            pass
