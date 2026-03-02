"""
All Sidicoin bot command handlers.
Every command shows a loading state first, then edits with the result.
All messages use HTML parse mode with branded formatting.
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
    create_virtual_account, verify_bank_account,
    process_payout, get_bank_code, COMMON_BANKS,
)
from services.groq import get_ai_response, detect_intent
from services.notifications import notify_user, notify_admin
from utils.formatting import (
    fmt_number, sidi_to_naira, naira_to_sidi, fmt_sidi, fmt_naira,
    fmt_timestamp, fmt_date, time_greeting, generate_receipt,
    generate_tx_reference, DIVIDER, SIDI_PRICE_NGN,
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


# ── Utility helpers ────────────────────────────────────────────

async def _get_bot_username(bot: Bot) -> str:
    """Get bot username for referral links."""
    me = await bot.get_me()
    return me.username or ""


def _account_badge(user: dict) -> str:
    """Return account type display."""
    if check_premium_status(user):
        return "Premium ✦"
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


# ═══════════════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    """Handle /start — new user onboarding or returning user welcome."""
    try:
        user_id = message.from_user.id
        from_user = message.from_user
        username = from_user.username or f"user_{user_id}"
        full_name = f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
        photo_url = ""

        # Check for referral code
        referred_by = ""
        if command.args and command.args.startswith("ref_"):
            referred_by = command.args.replace("ref_", "")

        existing_user = get_user(user_id)

        if existing_user:
            # Returning user — show balance summary
            balance = float(existing_user.get("sidi_balance", 0))
            naira = sidi_to_naira(balance)
            greeting = time_greeting(full_name or username)

            text = (
                f"✦ {greeting}\n\n"
                f"Welcome back to Sidicoin!\n\n"
                f"{DIVIDER}\n"
                f"💎 Balance: <b>{fmt_number(balance)} SIDI</b>\n"
                f"💵 Value: {fmt_naira(naira)}\n"
                f"🏆 Account: {_account_badge(existing_user)}\n"
                f"{DIVIDER}\n\n"
                f"What would you like to do? ✦"
            )
            await message.answer(text, reply_markup=home_keyboard())
            return

        # New user — show loading
        loading_msg = await message.answer("⚡ Setting up your Sidicoin wallet...")

        # Create TON wallet
        wallet_address, encrypted_key = create_wallet()

        # Create user record
        user = create_user(
            telegram_id=user_id,
            username=username,
            full_name=full_name,
            photo_url=photo_url,
            wallet_address=wallet_address,
            encrypted_private_key=encrypted_key,
            referred_by=referred_by,
        )

        # Credit referrer if applicable
        if referred_by:
            try:
                referrer_id = int(referred_by)
                if user_exists(referrer_id):
                    credit_referrer(referrer_id, 50.0, "signup")
                    # Notify referrer
                    referrer = get_user(referrer_id)
                    if referrer:
                        referrer_name = referrer.get("full_name", "there")
                        await notify_user(
                            bot, referrer_id,
                            f"🎉 {referrer_name}, someone joined via your referral link!\n"
                            f"+<b>50 SIDI</b> ({fmt_naira(sidi_to_naira(50))}) added to your wallet ✦"
                        )
            except (ValueError, Exception) as e:
                logger.error(f"Referral credit error: {e}")

        # Edit loading message with welcome
        welcome_text = (
            f"✦ Welcome to Sidicoin, {full_name or username}\n\n"
            f"Your wallet is ready. Your money moves instantly across Africa.\n\n"
            f"{DIVIDER}\n"
            f"💎 Balance: <b>80 SIDI</b>\n"
            f"💵 Value: {fmt_naira(2000)} (Welcome Bonus)\n"
            f"{DIVIDER}\n\n"
            f"Sidicoin lets you send money to anyone in Africa "
            f"using just their Telegram username — instantly, for free.\n\n"
            f"Type /help to see everything you can do ✦"
        )

        try:
            await loading_msg.edit_text(welcome_text, reply_markup=welcome_keyboard())
        except TelegramBadRequest:
            await message.answer(welcome_text, reply_markup=welcome_keyboard())

        # Send onboarding step 1
        onboard_text = (
            f"✦ <b>Let's get you started</b>\n\n"
            f"Sidicoin is the easiest way to move money across Africa.\n"
            f"No bank transfers. No long account numbers.\n"
            f"Just a Telegram username."
        )
        await message.answer(onboard_text, reply_markup=onboarding_step1_keyboard())

    except Exception as e:
        logger.error(f"/start error: {e}", exc_info=True)
        await message.answer(
            "Something went wrong on our end. Please try again in a moment ✦",
            reply_markup=home_button_keyboard(),
        )


# ═══════════════════════════════════════════════════════════════
# /balance
# ═══════════════════════════════════════════════════════════════

@router.message(Command("balance", "wallet"))
async def cmd_balance(message: Message):
    """Show detailed wallet balance."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        loading = await message.answer("📊 Fetching your wallet...")
        await _show_balance(loading, user)
    except Exception as e:
        logger.error(f"/balance error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


async def _show_balance(msg: Message, user: dict):
    """Edit message with balance details."""
    balance = float(user.get("sidi_balance", 0))
    naira = sidi_to_naira(balance)
    username = user.get("username", "")
    total_sent = float(user.get("total_sent", 0))
    total_received = float(user.get("total_received", 0))
    remaining = _get_daily_remaining(user)
    badge = _account_badge(user)

    text = (
        f"✦ Your Sidicoin Wallet\n\n"
        f"👤 @{username}\n"
        f"{DIVIDER}\n"
        f"💎 SIDI: <b>{fmt_number(balance)} SIDI</b>\n"
        f"💵 Value: {fmt_naira(naira)}\n"
        f"{DIVIDER}\n"
        f"📤 Total Sent: {fmt_number(total_sent)} SIDI\n"
        f"📥 Total Received: {fmt_number(total_received)} SIDI\n"
        f"🏆 Account: {badge}\n"
        f"📊 Daily Limit: {fmt_number(remaining)} SIDI left\n"
        f"{DIVIDER}"
    )
    try:
        await msg.edit_text(text, reply_markup=balance_keyboard())
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════════════════
# /send
# ═══════════════════════════════════════════════════════════════

@router.message(Command("send"))
async def cmd_send(message: Message, bot: Bot):
    """Handle /send — direct or guided flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        text = message.text.strip()
        parts = text.split()

        # METHOD 1: Direct — /send @username 500
        if len(parts) >= 3:
            recipient_username = parts[1]
            amount_text = " ".join(parts[2:])
            valid, amount = is_valid_amount(amount_text)
            if valid and is_valid_username(recipient_username):
                await _process_send_flow(message, bot, user, recipient_username, amount)
                return

        # METHOD 2: Guided flow — ask for recipient
        await message.answer(
            "✦ <b>Send SIDI</b>\n\n"
            "Who would you like to send to?\n"
            "Enter their Telegram @username:",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "send_username")

    except Exception as e:
        logger.error(f"/send error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


async def _process_send_flow(message: Message, bot: Bot, sender: dict, recipient_username: str, amount: float):
    """Process the send confirmation and execution."""
    sender_id = sender["telegram_id"]
    clean_user = clean_username(recipient_username)

    # Check recipient exists
    recipient = find_user_by_username(clean_user)
    if not recipient:
        # Check for similar usernames
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
            suggest_text = "\n\nDid you mean: " + ", ".join(f"@{s}" for s in similar)

        invite_link = f"https://t.me/{bot_username}?start=ref_{sender_id}"
        await message.answer(
            f"@{clean_user} hasn't joined Sidicoin yet.{suggest_text}\n\n"
            f"Invite them to join:\n{invite_link} ✦",
            reply_markup=home_button_keyboard(),
        )
        return

    if str(recipient["telegram_id"]) == str(sender_id):
        await message.answer("You can't send SIDI to yourself ✦", reply_markup=home_button_keyboard())
        return

    # Check balance
    balance = float(sender.get("sidi_balance", 0))
    if balance < amount:
        await message.answer(
            f"Insufficient balance. You have <b>{fmt_number(balance)} SIDI</b> "
            f"but tried to send <b>{fmt_number(amount)} SIDI</b>.\n\n"
            f"Type /buy to top up ✦",
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
            f"Daily transfer limit reached.\n"
            f"Limit: {fmt_number(limit)} SIDI | Remaining: {fmt_number(remaining)} SIDI\n\n"
            f"{'Upgrade to Premium for 500K/day limit: /premium' if not is_premium else 'Try again tomorrow'} ✦",
            reply_markup=home_button_keyboard(),
        )
        return

    naira = sidi_to_naira(amount)
    recipient_name = recipient.get("full_name", recipient.get("username", ""))

    # Store pending send data
    set_pending_action(int(sender_id), "send_confirm", {
        "recipient_id": recipient["telegram_id"],
        "recipient_username": recipient.get("username", clean_user),
        "recipient_name": recipient_name,
        "amount": amount,
    })

    # Large transfer warning
    keyboard = send_confirm_keyboard()
    warning = ""
    if is_large_transfer(amount):
        warning = "\n⚠️ <b>Large transfer warning</b> — please double-check the details.\n"
        keyboard = send_large_confirm_keyboard()

    confirm_text = (
        f"✦ <b>Transfer Summary</b>\n\n"
        f"To: @{recipient.get('username', clean_user)} — {recipient_name}\n"
        f"Amount: <b>{fmt_number(amount)} SIDI</b>\n"
        f"Value: {fmt_naira(naira)}\n"
        f"Fee: Free ✅\n"
        f"Speed: Instant ⚡\n"
        f"{warning}\n"
        f"Confirm transfer?"
    )
    await message.answer(confirm_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════════════════
# /buy
# ═══════════════════════════════════════════════════════════════

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    """Start buy SIDI flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        await message.answer(
            "✦ <b>Buy SIDI</b>\n\n"
            "How much would you like to buy?\n\n"
            "Enter amount in SIDI or Naira:\n"
            "• <code>500</code> (500 SIDI)\n"
            "• <code>₦12500</code> (₦12,500 worth)\n"
            "• <code>1000 SIDI</code>\n"
            "• <code>5000 NGN</code>",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "buy_amount")

    except Exception as e:
        logger.error(f"/buy error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /sell
# ═══════════════════════════════════════════════════════════════

@router.message(Command("sell", "cashout"))
async def cmd_sell(message: Message):
    """Start sell/cashout flow."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        balance = float(user.get("sidi_balance", 0))
        if balance <= 0:
            await message.answer(
                f"You don't have any SIDI to cash out.\n"
                f"Type /buy to purchase some ✦",
                reply_markup=home_button_keyboard(),
            )
            return

        await message.answer(
            f"✦ <b>Cash Out SIDI</b>\n\n"
            f"Your balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?",
            reply_markup=cancel_keyboard(),
        )
        set_pending_action(message.from_user.id, "sell_amount")

    except Exception as e:
        logger.error(f"/sell error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /history
# ═══════════════════════════════════════════════════════════════

@router.message(Command("history"))
async def cmd_history(message: Message):
    """Show transaction history."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        await _show_history(message, user, "all")

    except Exception as e:
        logger.error(f"/history error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


async def _show_history(target, user: dict, tx_filter: str):
    """Display transaction history with filter."""
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
        text = "✦ <b>Transaction History</b>\n\nNo transactions yet. Start with /send or /buy ✦"
        if isinstance(target, Message):
            await target.answer(text, reply_markup=history_filter_keyboard())
        elif isinstance(target, CallbackQuery):
            try:
                await target.message.edit_text(text, reply_markup=history_filter_keyboard())
            except TelegramBadRequest:
                pass
        return

    lines = ["✦ <b>Transaction History</b>\n", DIVIDER]
    for tx in txns[:20]:
        tx_type = tx.get("type", "")
        amount = float(tx.get("amount", 0))
        ts = tx.get("timestamp", 0)
        time_str = fmt_timestamp(ts) if ts else ""
        desc = tx.get("description", "")
        other = tx.get("other_username", "")

        if tx_type == "send":
            lines.append(f"📤 Sent <b>{fmt_number(amount)} SIDI</b> to @{other}")
            lines.append(f"   {fmt_naira(sidi_to_naira(amount))} · Instant · {time_str}")
        elif tx_type == "receive":
            lines.append(f"📥 Received <b>{fmt_number(amount)} SIDI</b> from @{other}")
            lines.append(f"   {fmt_naira(sidi_to_naira(amount))} · Instant · {time_str}")
        elif tx_type == "buy":
            lines.append(f"💳 Bought <b>{fmt_number(amount)} SIDI</b> — Paid {fmt_naira(sidi_to_naira(amount))}")
            lines.append(f"   {time_str}")
        elif tx_type == "sell":
            lines.append(f"💰 Cashed out {fmt_naira(sidi_to_naira(amount))}")
            lines.append(f"   {desc} · {time_str}")
        elif tx_type == "bonus":
            lines.append(f"🎁 {desc}: +<b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"   {time_str}")
        elif tx_type == "checkin":
            lines.append(f"✅ {desc}: +<b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"   {time_str}")
        elif tx_type == "referral_bonus":
            lines.append(f"🎁 {desc}: +<b>{fmt_number(amount)} SIDI</b>")
            lines.append(f"   {time_str}")
        else:
            lines.append(f"• {desc}: {fmt_number(amount)} SIDI · {time_str}")

    lines.append(DIVIDER)
    text = "\n".join(lines)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=history_filter_keyboard())
    elif isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=history_filter_keyboard())
        except TelegramBadRequest:
            pass


# ═══════════════════════════════════════════════════════════════
# /contacts
# ═══════════════════════════════════════════════════════════════

@router.message(Command("contacts"))
async def cmd_contacts(message: Message):
    """Show saved contacts."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        contacts = user.get("saved_contacts", [])
        if not contacts:
            await message.answer(
                "✦ <b>Saved Contacts</b>\n\n"
                "No saved contacts yet. Send SIDI to someone and they'll appear here ✦",
                reply_markup=home_button_keyboard(),
            )
            return

        lines = ["✦ <b>Saved Contacts</b>\n", DIVIDER]
        for c in contacts[:10]:
            name = c.get("full_name", "")
            uname = c.get("username", "")
            last = c.get("last_transfer", 0)
            lines.append(f"👤 {name} (@{uname})")
            if last:
                lines.append(f"   Last transfer: {fmt_timestamp(last)}")

        lines.append(DIVIDER)
        text = "\n".join(lines)
        await message.answer(text, reply_markup=contacts_keyboard(contacts))

    except Exception as e:
        logger.error(f"/contacts error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /refer
# ═══════════════════════════════════════════════════════════════

@router.message(Command("refer", "referral"))
async def cmd_refer(message: Message, bot: Bot):
    """Show referral info and link."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        bot_username = await _get_bot_username(bot)
        ref_link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}"
        count = int(user.get("referral_count", 0))
        earned = float(user.get("referral_earnings", 0))

        text = (
            f"✦ <b>Refer and Earn</b>\n\n"
            f"Your referral link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n"
            f"🎁 Per signup: +50 SIDI ({fmt_naira(sidi_to_naira(50))})\n"
            f"💰 Per purchase: +10 SIDI ({fmt_naira(sidi_to_naira(10))})\n"
            f"{DIVIDER}\n"
            f"👥 Referrals: <b>{count}</b>\n"
            f"💎 Earned: <b>{fmt_number(earned)} SIDI</b> ({fmt_naira(sidi_to_naira(earned))})\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=refer_keyboard(ref_link))

    except Exception as e:
        logger.error(f"/refer error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /checkin
# ═══════════════════════════════════════════════════════════════

@router.message(Command("checkin"))
async def cmd_checkin(message: Message):
    """Daily check-in reward."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        success, bonus_msg, amount, streak = process_checkin(message.from_user.id)

        if not success:
            await message.answer(bonus_msg, reply_markup=home_button_keyboard())
            return

        # Refresh user data
        user = get_user(message.from_user.id)
        balance = float(user.get("sidi_balance", 0))

        text = (
            f"✦ <b>Daily Reward Claimed!</b>\n\n"
            f"+<b>{fmt_number(amount)} SIDI</b> added to your wallet\n"
            f"🔥 Streak: {streak} days\n"
            f"New Balance: <b>{fmt_number(balance)} SIDI</b>"
            f"{bonus_msg}"
        )
        await message.answer(text, reply_markup=home_keyboard())

    except Exception as e:
        logger.error(f"/checkin error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /premium
# ═══════════════════════════════════════════════════════════════

@router.message(Command("premium"))
async def cmd_premium(message: Message):
    """Show premium comparison and upgrade option."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        if check_premium_status(user):
            expiry = int(user.get("premium_expiry", 0))
            await message.answer(
                f"✦ You are already a <b>Premium ✦</b> member!\n\n"
                f"Expires: {fmt_timestamp(expiry)}\n\n"
                f"Enjoy your benefits ✦",
                reply_markup=home_keyboard(),
            )
            return

        text = (
            f"✦ <b>Sidicoin Premium</b>\n\n"
            f"<b>FREE</b>          <b>PREMIUM ✦</b>\n"
            f"{DIVIDER}\n"
            f"50K/day       500K/day limit\n"
            f"1.5% fees     0.8% fees\n"
            f"10 SIDI/day   25 SIDI/day check-in\n"
            f"No badge      ✦ badge\n"
            f"No priority   Priority support\n\n"
            f"<b>₦1,500 per month</b>"
        )
        await message.answer(text, reply_markup=premium_keyboard())

    except Exception as e:
        logger.error(f"/premium error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /leaderboard
# ═══════════════════════════════════════════════════════════════

@router.message(Command("leaderboard", "top"))
async def cmd_leaderboard(message: Message):
    """Show top holders leaderboard."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        leaders = get_leaderboard(5)
        rank = get_user_rank(message.from_user.id)
        balance = float(user.get("sidi_balance", 0))

        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        lines = ["✦ <b>Top Sidicoin Holders</b>\n"]

        for i, (uid, score) in enumerate(leaders):
            leader_user = get_user(uid)
            uname = leader_user.get("username", uid) if leader_user else uid
            medal = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"{medal} @{uname} — <b>{fmt_number(score)} SIDI</b>")

        lines.append(f"\nYour Rank: <b>#{rank}</b>")
        lines.append(f"Your Balance: <b>{fmt_number(balance)} SIDI</b> ✦")

        text = "\n".join(lines)
        await message.answer(text, reply_markup=leaderboard_keyboard())

    except Exception as e:
        logger.error(f"/leaderboard error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /price
# ═══════════════════════════════════════════════════════════════

@router.message(Command("price"))
async def cmd_price(message: Message):
    """Show current SIDI price and market data."""
    try:
        loading = await message.answer("📈 Fetching live data...")

        stats = get_all_stats()
        holders = int(stats.get("total_holders", 0))
        volume = float(stats.get("daily_volume_ngn", 0))
        tx_count = int(stats.get("daily_tx_count", 0))
        cap = SIDI_PRICE_NGN * 10_000_000_000
        usd_rate = 1600  # approximate NGN/USD
        usd_equiv = SIDI_PRICE_NGN / usd_rate

        text = (
            f"✦ <b>Sidicoin Price</b>\n\n"
            f"1 SIDI = <b>₦{fmt_number(SIDI_PRICE_NGN)}</b>\n"
            f"1 SIDI = <b>${usd_equiv:.6f}</b>\n\n"
            f"{DIVIDER}\n"
            f"Holders: {fmt_number(holders)}\n"
            f"Market Cap: {fmt_naira(cap)}\n"
            f"Volume Today: {fmt_naira(volume)}\n"
            f"Transactions Today: {fmt_number(tx_count)}\n"
            f"{DIVIDER}\n"
            f"Blockchain: TON ✦"
        )

        try:
            await loading.edit_text(text, reply_markup=home_button_keyboard())
        except TelegramBadRequest:
            await message.answer(text, reply_markup=home_button_keyboard())

    except Exception as e:
        logger.error(f"/price error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /stats
# ═══════════════════════════════════════════════════════════════

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

        text = (
            f"✦ <b>Sidicoin Statistics</b>\n\n"
            f"Total Supply: <b>10,000,000,000 SIDI</b>\n"
            f"Circulating: {fmt_number(circulating)} SIDI\n"
            f"Holders: {fmt_number(holders)}\n"
            f"Transactions Today: {fmt_number(tx_count)}\n"
            f"Volume Today: {fmt_naira(volume)}\n"
            f"Total Fees Collected: {fmt_naira(sidi_to_naira(fees))}\n\n"
            f"Blockchain: TON | Ticker: SIDI | Price: ₦{fmt_number(SIDI_PRICE_NGN)} per SIDI ✦"
        )
        await message.answer(text, reply_markup=home_button_keyboard())

    except Exception as e:
        logger.error(f"/stats error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /settings
# ═══════════════════════════════════════════════════════════════

@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Show account settings."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("You don't have a wallet yet. Type /start to create one ✦")
            return

        joined = fmt_date(user.get("joined_date", 0))
        bank = user.get("bank_name", "Not set")
        account = user.get("bank_account", "")
        account_name = user.get("bank_account_name", "")
        bank_display = f"{bank} — {account} — {account_name}" if bank != "Not set" and account else "Not set"

        text = (
            f"✦ <b>Account Settings</b>\n\n"
            f"👤 {user.get('full_name', '')} (@{user.get('username', '')})\n"
            f"🏆 {_account_badge(user)} Account\n"
            f"📅 Member since {joined}\n"
            f"🏦 Saved Bank: {bank_display}"
        )
        await message.answer(text, reply_markup=settings_keyboard())

    except Exception as e:
        logger.error(f"/settings error: {e}", exc_info=True)
        await message.answer("Something went wrong on our end. Please try again in a moment ✦")


# ═══════════════════════════════════════════════════════════════
# /help
# ═══════════════════════════════════════════════════════════════

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Show all commands organized by category."""
    text = (
        f"✦ <b>Sidicoin Commands</b>\n\n"
        f"<b>💎 Wallet</b>\n"
        f"/balance — Check your SIDI balance\n"
        f"/settings — Account settings\n\n"
        f"<b>📤 Transfers</b>\n"
        f"/send — Send SIDI to anyone\n"
        f"/contacts — Quick send to saved contacts\n\n"
        f"<b>💰 Money</b>\n"
        f"/buy — Buy SIDI with Naira\n"
        f"/sell — Cash out SIDI to bank\n"
        f"/history — Transaction history\n\n"
        f"<b>🎁 Earn</b>\n"
        f"/checkin — Daily reward\n"
        f"/refer — Earn 50 SIDI per referral\n"
        f"/premium — Upgrade for lower fees\n\n"
        f"<b>📊 Market</b>\n"
        f"/price — SIDI price and market data\n"
        f"/stats — Platform statistics\n"
        f"/leaderboard — Top holders\n\n"
        f"<b>ℹ️ Info</b>\n"
        f"/about — About Sidicoin\n"
        f"/help — This menu\n\n"
        f'🌐 <a href="https://coin.sidihost.sbs">coin.sidihost.sbs</a> ✦'
    )
    await message.answer(text, reply_markup=help_keyboard(), disable_web_page_preview=True)


# ═══════════════════════════════════════════════════════════════
# /about
# ═══════════════════════════════════════════════════════════════

@router.message(Command("about"))
async def cmd_about(message: Message):
    """About Sidicoin."""
    text = (
        f"✦ <b>About Sidicoin</b>\n\n"
        f"Sidicoin (SIDI) is a cryptocurrency built on TON blockchain "
        f"with one mission — make financial transfers across Africa "
        f"instant, free and accessible to everyone.\n\n"
        f"No bank account required.\n"
        f"No crypto knowledge needed.\n"
        f"Just Telegram and a username.\n\n"
        f"Supply: <b>10,000,000,000 SIDI</b>\n"
        f"Price: <b>₦25 per SIDI</b>\n"
        f"Blockchain: TON\n\n"
        f"Built for Africa. Going global ✦\n\n"
        f'🌐 <a href="https://coin.sidihost.sbs">coin.sidihost.sbs</a>'
    )
    await message.answer(text, reply_markup=home_button_keyboard(), disable_web_page_preview=True)


# ═══════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ═══════════════════════════════════════════════════════════════

def _is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_TELEGRAM_ID


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message):
    """Admin: platform dashboard."""
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
        f"🛡️ <b>Admin Dashboard</b>\n\n"
        f"Total Users: {fmt_number(user_count)}\n"
        f"Active Holders: {fmt_number(holders)}\n"
        f"Circulating Supply: {fmt_number(circulating)} SIDI\n"
        f"Daily Volume: {fmt_naira(volume)}\n"
        f"Daily Transactions: {fmt_number(tx_count)}\n"
        f"Total Fees: {fmt_number(fees)} SIDI ({fmt_naira(sidi_to_naira(fees))})\n"
        f"Fee Wallet: {SIDI_FEE_WALLET or 'Not set'}"
    )
    await message.answer(text)


@router.message(Command("admin_user"))
async def cmd_admin_user(message: Message):
    """Admin: view full user profile."""
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

    text = f"🛡️ <b>User Profile: @{username}</b>\n\n<code>{json.dumps(safe_user, indent=2, default=str)[:3800]}</code>"
    await message.answer(text)


@router.message(Command("admin_credit"))
async def cmd_admin_credit(message: Message, bot: Bot):
    """Admin: credit SIDI to user."""
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
        "type": "bonus",
        "amount": amount,
        "description": "Admin credit",
        "timestamp": int(time.time()),
        "reference": generate_tx_reference(),
    })
    increment_stat("circulating_supply", amount)

    await message.answer(f"✅ Credited {fmt_number(amount)} SIDI to @{username}")
    await notify_user(
        bot, user["telegram_id"],
        f"💎 +<b>{fmt_number(amount)} SIDI</b> has been added to your wallet ✦"
    )


@router.message(Command("admin_debit"))
async def cmd_admin_debit(message: Message, bot: Bot):
    """Admin: debit SIDI from user."""
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
        "type": "debit",
        "amount": -amount,
        "description": "Admin debit",
        "timestamp": int(time.time()),
        "reference": generate_tx_reference(),
    })

    await message.answer(f"✅ Debited {fmt_number(amount)} SIDI from @{username}")


@router.message(Command("admin_ban"))
async def cmd_admin_ban(message: Message):
    """Admin: ban user."""
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
    await message.answer(f"🚫 @{username} has been banned.")


@router.message(Command("admin_unban"))
async def cmd_admin_unban(message: Message):
    """Admin: unban user."""
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
    await message.answer(f"✅ @{username} has been unbanned.")


@router.message(Command("admin_broadcast"))
async def cmd_admin_broadcast(message: Message, bot: Bot):
    """Admin: broadcast message to all users."""
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

    status_msg = await message.answer(f"📡 Broadcasting to {len(user_ids)} users...")

    for uid in user_ids:
        try:
            success = await notify_user(bot, uid, broadcast_text)
            if success:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    try:
        await status_msg.edit_text(f"✅ Broadcast complete\nSent: {sent} | Failed: {failed}")
    except TelegramBadRequest:
        pass


@router.message(Command("admin_fees"))
async def cmd_admin_fees(message: Message):
    """Admin: total fees collected."""
    if not _is_admin(message.from_user.id):
        return

    fees = get_stat("total_fees_sidi")
    await message.answer(
        f"💰 <b>Total Fees Collected</b>\n\n"
        f"{fmt_number(fees)} SIDI ({fmt_naira(sidi_to_naira(fees))})\n"
        f"Fee Wallet: <code>{SIDI_FEE_WALLET or 'Not set'}</code>"
    )


@router.message(Command("admin_pending"))
async def cmd_admin_pending(message: Message):
    """Admin: list users with pending actions."""
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

    text = "🕐 <b>Pending Actions</b>\n\n" + "\n".join(pending[:50])
    await message.answer(text)


# ═══════════════════════════════════════════════════════════════
# CALLBACK QUERY HANDLERS
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "cmd_home")
async def cb_home(callback: CallbackQuery):
    """Show home menu."""
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return

        balance = float(user.get("sidi_balance", 0))
        naira = sidi_to_naira(balance)
        name = user.get("full_name", "there")

        text = (
            f"✦ {name}'s Wallet\n"
            f"💎 <b>{fmt_number(balance)} SIDI</b>\n"
            f"💵 {fmt_naira(naira)}"
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
            "✦ <b>Send SIDI</b>\n\n"
            "Who would you like to send to?\n"
            "Enter their Telegram @username:",
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

        await callback.message.edit_text(
            "✦ <b>Buy SIDI</b>\n\n"
            "How much would you like to buy?\n\n"
            "Enter amount in SIDI or Naira:\n"
            "• <code>500</code> (500 SIDI)\n"
            "• <code>₦12500</code> (₦12,500 worth)\n"
            "• <code>1000 SIDI</code>\n"
            "• <code>5000 NGN</code>",
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
                "You don't have any SIDI to cash out.\nType /buy to purchase some ✦",
                reply_markup=home_button_keyboard(),
            )
            await callback.answer()
            return

        await callback.message.edit_text(
            f"✦ <b>Cash Out SIDI</b>\n\n"
            f"Your balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?",
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
            f"✦ <b>Refer and Earn</b>\n\n"
            f"Your referral link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n"
            f"🎁 Per signup: +50 SIDI ({fmt_naira(sidi_to_naira(50))})\n"
            f"💰 Per purchase: +10 SIDI ({fmt_naira(sidi_to_naira(10))})\n"
            f"{DIVIDER}\n"
            f"👥 Referrals: <b>{count}</b>\n"
            f"💎 Earned: <b>{fmt_number(earned)} SIDI</b> ({fmt_naira(sidi_to_naira(earned))})\n"
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
            f"✦ <b>Sidicoin Commands</b>\n\n"
            f"<b>💎 Wallet</b>\n"
            f"/balance — Check your SIDI balance\n"
            f"/settings — Account settings\n\n"
            f"<b>📤 Transfers</b>\n"
            f"/send — Send SIDI to anyone\n"
            f"/contacts — Quick send to saved contacts\n\n"
            f"<b>💰 Money</b>\n"
            f"/buy — Buy SIDI with Naira\n"
            f"/sell — Cash out SIDI to bank\n"
            f"/history — Transaction history\n\n"
            f"<b>🎁 Earn</b>\n"
            f"/checkin — Daily reward\n"
            f"/refer — Earn 50 SIDI per referral\n"
            f"/premium — Upgrade for lower fees\n\n"
            f"<b>📊 Market</b>\n"
            f"/price — SIDI price and market data\n"
            f"/stats — Platform statistics\n"
            f"/leaderboard — Top holders\n\n"
            f'🌐 <a href="https://coin.sidihost.sbs">coin.sidihost.sbs</a> ✦'
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
        bank = user.get("bank_name", "Not set")
        account = user.get("bank_account", "")
        account_name = user.get("bank_account_name", "")
        bank_display = f"{bank} — {account} — {account_name}" if bank != "Not set" and account else "Not set"

        text = (
            f"✦ <b>Account Settings</b>\n\n"
            f"👤 {user.get('full_name', '')} (@{user.get('username', '')})\n"
            f"🏆 {_account_badge(user)} Account\n"
            f"📅 Member since {joined}\n"
            f"🏦 Saved Bank: {bank_display}"
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


# ── History filter callbacks ───────────────────────────────────

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


# ── Onboarding callbacks ──────────────────────────────────────

@router.callback_query(F.data == "onboard_2")
async def cb_onboard_2(callback: CallbackQuery):
    try:
        text = (
            "✦ <b>How Sidicoin Works</b>\n\n"
            "Send money to anyone in Africa using just their Telegram username.\n\n"
            "Example: /send @john 5000\n\n"
            "No bank transfer stress. No long account numbers. Just a username ✦"
        )
        await callback.message.edit_text(text, reply_markup=onboarding_step2_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "onboard_3")
async def cb_onboard_3(callback: CallbackQuery):
    try:
        text = (
            "✦ <b>Your First Step</b>\n\n"
            "Buy some SIDI to get started. "
            "Or send your referral link to earn free SIDI first!"
        )
        await callback.message.edit_text(text, reply_markup=onboarding_step3_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# ── Send flow callbacks ───────────────────────────────────────

@router.callback_query(F.data == "send_confirm")
async def cb_send_confirm(callback: CallbackQuery, bot: Bot):
    """Execute confirmed transfer."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "send_confirm" or not data:
            await callback.answer("No pending transfer found")
            return

        loading_text = "📡 Processing your transfer..."
        try:
            await callback.message.edit_text(loading_text)
        except TelegramBadRequest:
            pass

        sender = get_user(callback.from_user.id)
        recipient_id = data["recipient_id"]
        amount = float(data["amount"])
        recipient_username = data.get("recipient_username", "")
        recipient_name = data.get("recipient_name", "")

        # Check for large transfer suspicious activity
        if is_large_transfer(amount):
            count = track_large_transfer(callback.from_user.id)
            if count > 3:
                await notify_admin(
                    bot,
                    f"⚠️ SUSPICIOUS: @{sender.get('username', '')} made {count} large transfers in 1 hour\n"
                    f"Latest: {fmt_number(amount)} SIDI to @{recipient_username}"
                )

        # Execute transfer
        reference = generate_tx_reference()
        success = transfer_sidi(callback.from_user.id, recipient_id, amount)

        if not success:
            await callback.message.edit_text(
                "Transfer failed — insufficient balance or an error occurred. "
                "Please try again ✦",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        increment_rate_count(callback.from_user.id)

        # Add transactions for both parties
        now = int(time.time())
        sender_username = sender.get("username", "")

        add_transaction(callback.from_user.id, {
            "type": "send",
            "amount": amount,
            "other_username": recipient_username,
            "description": f"Sent to @{recipient_username}",
            "timestamp": now,
            "reference": reference,
        })

        add_transaction(recipient_id, {
            "type": "receive",
            "amount": amount,
            "other_username": sender_username,
            "description": f"Received from @{sender_username}",
            "timestamp": now,
            "reference": reference,
        })

        clear_pending_action(callback.from_user.id)

        # Show receipt to sender
        naira = sidi_to_naira(amount)
        receipt = generate_receipt(
            "Transfer", sender_username, recipient_username, amount, 0, reference
        )

        # Refresh sender data
        sender = get_user(callback.from_user.id)
        new_balance = float(sender.get("sidi_balance", 0))

        sender_text = (
            f"✦ <b>Transfer Successful!</b>\n\n"
            f"Sent <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)}) to @{recipient_username}\n"
            f"New Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
            f"{receipt}"
        )

        try:
            await callback.message.edit_text(sender_text, reply_markup=after_send_keyboard())
        except TelegramBadRequest:
            pass

        # Notify recipient
        recipient = get_user(recipient_id)
        recipient_balance = float(recipient.get("sidi_balance", 0)) if recipient else 0

        recipient_text = (
            f"✦ <b>You received money!</b>\n\n"
            f"💰 +<b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n"
            f"From: @{sender_username}\n"
            f"Speed: Instant ⚡\n"
            f"Balance: <b>{fmt_number(recipient_balance)} SIDI</b>"
        )
        await notify_user(bot, recipient_id, recipient_text, reply_markup=received_money_keyboard())

        # Smart suggestions
        if new_balance < 50:
            await callback.message.answer(
                f"💡 Your balance is getting low. Top up with /buy ✦",
                reply_markup=home_button_keyboard(),
            )

        # Milestone check
        tx_count = _transfer_count(sender)
        if tx_count == 1:
            await callback.message.answer(
                f"🎉 You just made your first Sidicoin transfer, "
                f"{sender.get('full_name', 'there')}! "
                f"Welcome to the future of African finance ✦"
            )
        elif tx_count == 10:
            await callback.message.answer(
                f"🔥 10 transfers done! You are a true Sidicoin power user, "
                f"{sender.get('full_name', 'there')} ✦"
            )

        await callback.answer("Transfer successful!")

    except Exception as e:
        logger.error(f"send_confirm error: {e}", exc_info=True)
        await callback.message.edit_text(
            "Something went wrong on our end. Please try again in a moment ✦",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()


@router.callback_query(F.data == "send_cancel")
async def cb_send_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "Transfer cancelled ✦", reply_markup=home_keyboard()
        )
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# ── Buy flow callbacks ────────────────────────────────────────

@router.callback_query(F.data == "buy_proceed")
async def cb_buy_proceed(callback: CallbackQuery):
    """Generate Korapay virtual account for payment."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "buy_confirm" or not data:
            await callback.answer("No pending purchase found")
            return

        try:
            await callback.message.edit_text("🔄 Generating your payment details...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)
        total_ngn = float(data["total_ngn"])
        sidi_amount = float(data["sidi_amount"])
        reference = generate_tx_reference()

        # Create virtual account
        result = await create_virtual_account(
            reference=reference,
            amount=total_ngn,
            customer_name=user.get("full_name", "Sidicoin User"),
        )

        if not result.get("success"):
            await callback.message.edit_text(
                f"Could not generate payment details: {result.get('message', 'Unknown error')}.\n"
                "Please try again ✦",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        # Store pending payment for webhook
        from services.redis import store_pending_payment
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

        payment_text = (
            f"✦ <b>Make Your Payment</b>\n\n"
            f"Bank: <b>{result.get('bank_name', '')}</b>\n"
            f"Account: <code>{result.get('account_number', '')}</code>\n"
            f"Amount: <b>{fmt_naira(total_ngn)}</b>\n\n"
            f"⏰ Expires in 30 minutes\n\n"
            f"Send EXACTLY {fmt_naira(total_ngn)} to avoid delays.\n"
            f"We will notify you once confirmed ✦"
        )
        await callback.message.edit_text(payment_text, reply_markup=buy_payment_keyboard())
        await callback.answer()

    except Exception as e:
        logger.error(f"buy_proceed error: {e}", exc_info=True)
        await callback.message.edit_text(
            "Something went wrong on our end. Please try again in a moment ✦",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()


@router.callback_query(F.data == "buy_paid")
async def cb_buy_paid(callback: CallbackQuery):
    """User says they've paid — advise to wait for confirmation."""
    try:
        await callback.message.edit_text(
            "✦ <b>Waiting for confirmation</b>\n\n"
            "We're checking for your payment. This usually takes 1-5 minutes.\n"
            "You'll be notified automatically once your payment is confirmed.\n\n"
            "If you haven't paid yet, please complete the transfer now ✦",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "buy_cancel")
async def cb_buy_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text("Purchase cancelled ✦", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# ── Sell flow callbacks ───────────────────────────────────────

@router.callback_query(F.data == "sell_confirm")
async def cb_sell_confirm(callback: CallbackQuery, bot: Bot):
    """Execute cashout."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "sell_confirm" or not data:
            await callback.answer("No pending cashout found")
            return

        try:
            await callback.message.edit_text("💸 Processing your cashout...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)

        # Check 24hr hold
        hold_until = int(user.get("cashout_hold_until", 0))
        if hold_until > int(time.time()):
            remaining = hold_until - int(time.time())
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            await callback.message.edit_text(
                f"⏳ Your account has a 24-hour hold on cashouts.\n"
                f"Time remaining: <b>{hours}h {mins}m</b>\n\n"
                f"This is a security measure for new accounts. "
                f"Your SIDI is safe in your wallet ✦",
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
                "Insufficient balance for cashout. Please try again ✦",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(callback.from_user.id)
            await callback.answer()
            return

        # Track fees
        if fee_sidi > 0:
            increment_stat("total_fees_sidi", fee_sidi)

        # Process payout
        reference = generate_tx_reference()
        payout_result = await process_payout(
            reference=reference,
            amount=net_ngn,
            bank_code=bank_code,
            account_number=bank_account,
            account_name=account_name,
        )

        # Record transaction
        now = int(time.time())
        add_transaction(callback.from_user.id, {
            "type": "sell",
            "amount": sidi_amount,
            "description": f"{bank_name} — {account_name}",
            "timestamp": now,
            "reference": reference,
        })

        # Update sold total
        user = get_user(callback.from_user.id)
        user["total_sold_ngn"] = float(user.get("total_sold_ngn", 0)) + net_ngn
        save_user(callback.from_user.id, user)

        clear_pending_action(callback.from_user.id)

        if payout_result.get("success"):
            receipt_text = (
                f"✦ <b>Cashout Successful!</b>\n\n"
                f"{fmt_naira(net_ngn)} sent to {bank_name}\n"
                f"Account: {account_name}\n"
                f"Reference: <code>{reference}</code>\n"
                f"Status: Processing ⚡\n\n"
                f"Usually arrives within minutes ✦"
            )
        else:
            receipt_text = (
                f"✦ <b>Cashout Submitted</b>\n\n"
                f"Your cashout of {fmt_naira(net_ngn)} to {bank_name} "
                f"has been submitted for processing.\n"
                f"Reference: <code>{reference}</code>\n\n"
                f"We'll notify you once it's complete ✦"
            )

        await callback.message.edit_text(receipt_text, reply_markup=after_sell_keyboard())

        # First cashout milestone
        sell_txns = [t for t in user.get("transactions", []) if t.get("type") == "sell"]
        if len(sell_txns) <= 1:
            await callback.message.answer(
                f"💰 First cashout done! That's your Sidicoin working for you ✦"
            )

        await callback.answer("Cashout processed!")

    except Exception as e:
        logger.error(f"sell_confirm error: {e}", exc_info=True)
        await callback.message.edit_text(
            "Something went wrong on our end. Please try again in a moment ✦",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()


@router.callback_query(F.data == "sell_bank_yes")
async def cb_sell_bank_yes(callback: CallbackQuery):
    """User confirmed saved bank for cashout."""
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

        # Update pending with bank details and move to confirm
        set_pending_action(callback.from_user.id, "sell_confirm", {
            **data,
            "bank_code": user.get("bank_code", ""),
            "bank_account": user.get("bank_account", ""),
            "bank_name": user.get("bank_name", ""),
            "account_name": user.get("bank_account_name", ""),
            "fee_sidi": fee_sidi,
            "net_ngn": net_ngn,
        })

        text = (
            f"✦ <b>Cashout Summary</b>\n\n"
            f"Selling: <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"You receive: {fmt_naira(gross_ngn)}\n"
            f"Fee ({fee_pct}): {fmt_naira(fee_ngn)}\n"
            f"Net payout: <b>{fmt_naira(net_ngn)}</b>\n\n"
            f"🏦 {user.get('bank_name', '')} — {user.get('bank_account', '')} — {user.get('bank_account_name', '')}\n\n"
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
    """Prompt user to enter new bank details."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        set_pending_action(callback.from_user.id, "sell_bank_name", data)

        await callback.message.edit_text(
            "✦ <b>Enter Bank Details</b>\n\n"
            "What bank do you use?\n"
            "Type the bank name (e.g. GTBank, Access Bank, Kuda, OPay):",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "sell_cancel")
async def cb_sell_cancel(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text("Cashout cancelled ✦", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# ── Premium callbacks ─────────────────────────────────────────

@router.callback_query(F.data == "premium_upgrade")
async def cb_premium_upgrade(callback: CallbackQuery):
    """Start premium payment flow via Korapay."""
    try:
        try:
            await callback.message.edit_text("🔄 Generating your payment details...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)
        reference = generate_tx_reference()
        amount = 1500.0

        result = await create_virtual_account(
            reference=reference,
            amount=amount,
            customer_name=user.get("full_name", "Sidicoin User"),
            narration="Sidicoin Premium Subscription",
        )

        if not result.get("success"):
            await callback.message.edit_text(
                "Could not generate payment details. Please try again ✦",
                reply_markup=home_button_keyboard(),
            )
            await callback.answer()
            return

        from services.redis import store_pending_payment
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
            f"✦ <b>Premium Payment</b>\n\n"
            f"Bank: <b>{result.get('bank_name', '')}</b>\n"
            f"Account: <code>{result.get('account_number', '')}</code>\n"
            f"Amount: <b>{fmt_naira(amount)}</b>\n\n"
            f"⏰ Expires in 30 minutes\n"
            f"Send EXACTLY {fmt_naira(amount)} ✦"
        )
        await callback.message.edit_text(text, reply_markup=premium_payment_keyboard())
        await callback.answer()

    except Exception as e:
        logger.error(f"premium_upgrade error: {e}", exc_info=True)
        await callback.message.edit_text(
            "Something went wrong. Please try again ✦", reply_markup=home_button_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "premium_paid")
async def cb_premium_paid(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "✦ Checking for your payment...\n\n"
            "You'll be notified automatically once confirmed ✦",
            reply_markup=home_button_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# ── Contact quick-send callback ────────────────────────────────

@router.callback_query(F.data.startswith("contact_send_"))
async def cb_contact_send(callback: CallbackQuery):
    """Quick send to a saved contact."""
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

        await callback.message.edit_text(
            f"✦ <b>Send to @{recipient.get('username', '')}</b>\n\n"
            f"How much SIDI would you like to send?",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()

    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"contact_send error: {e}")
        await callback.answer("Something went wrong")


# ── Referral copy callback ─────────────────────────────────────

@router.callback_query(F.data == "refer_copy")
async def cb_refer_copy(callback: CallbackQuery, bot: Bot):
    try:
        user = get_user(callback.from_user.id)
        bot_username = await _get_bot_username(bot)
        ref_link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}"
        await callback.answer(f"Link: {ref_link}", show_alert=True)
    except Exception:
        await callback.answer("Could not copy link")


# ── Settings callbacks ─────────────────────────────────────────

@router.callback_query(F.data == "settings_bank")
async def cb_settings_bank(callback: CallbackQuery):
    try:
        set_pending_action(callback.from_user.id, "settings_bank_name")
        await callback.message.edit_text(
            "✦ <b>Update Bank Details</b>\n\n"
            "What bank do you use?\n"
            "Type the bank name (e.g. GTBank, Access Bank, Kuda, OPay):",
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
        address = user.get("wallet_address", "")
        await callback.answer(f"TON Wallet: {address}", show_alert=True)
    except Exception:
        await callback.answer("Could not get wallet address")


@router.callback_query(F.data == "settings_notif")
async def cb_settings_notif(callback: CallbackQuery):
    try:
        await callback.answer("Notifications are always on for important updates ✦", show_alert=True)
    except Exception:
        pass


# ── Leaderboard callbacks ─────────────────────────────────────

@router.callback_query(F.data.startswith("leaderboard_"))
async def cb_leaderboard_type(callback: CallbackQuery):
    try:
        # For now all views show the same data
        user = get_user(callback.from_user.id)
        leaders = get_leaderboard(5)
        rank = get_user_rank(callback.from_user.id)
        balance = float(user.get("sidi_balance", 0)) if user else 0

        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        lines = ["✦ <b>Top Sidicoin Holders</b>\n"]

        for i, (uid, score) in enumerate(leaders):
            leader_user = get_user(uid)
            uname = leader_user.get("username", uid) if leader_user else uid
            medal = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"{medal} @{uname} — <b>{fmt_number(score)} SIDI</b>")

        lines.append(f"\nYour Rank: <b>#{rank}</b>")
        lines.append(f"Your Balance: <b>{fmt_number(balance)} SIDI</b> ✦")

        await callback.message.edit_text("\n".join(lines), reply_markup=leaderboard_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"leaderboard callback error: {e}")
        await callback.answer("Something went wrong")


# ── Cancel action callback ─────────────────────────────────────

@router.callback_query(F.data == "cancel_action")
async def cb_cancel_action(callback: CallbackQuery):
    clear_pending_action(callback.from_user.id)
    try:
        await callback.message.edit_text("Action cancelled ✦", reply_markup=home_keyboard())
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled")


# ═══════════════════════════════════════════════════════════════
# TEXT MESSAGE HANDLER (multi-step flows + AI)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text)
async def handle_text_message(message: Message, bot: Bot):
    """
    Handle all non-command text messages.
    Routes to pending action flows or AI assistant.
    """
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        sanitized = sanitize_input(text)

        # Check for pending multi-step actions
        action, data = get_pending_action(user_id)

        if action:
            await _handle_pending_action(message, bot, action, data, sanitized)
            return

        # No pending action — use AI assistant
        loading = await message.answer("✦ Sidi is thinking...")

        # Check for intent to guide user
        intent = detect_intent(sanitized)
        if intent:
            ai_response = await get_ai_response(sanitized, message.from_user.first_name or "User")
            response_text = f"{ai_response}\n\n💡 Try: {intent}"
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
            "Something went wrong on our end. Please try again in a moment ✦",
            reply_markup=home_button_keyboard(),
        )


async def _handle_pending_action(message: Message, bot: Bot, action: str, data: dict, text: str):
    """Route pending multi-step conversation flows."""
    user_id = message.from_user.id

    # ── Send flow ──────────────────────────────────────────
    if action == "send_username":
        # User is entering recipient username
        if not is_valid_username(text):
            await message.answer(
                "That doesn't look like a valid username. "
                "Please enter a Telegram @username (e.g. @john):",
                reply_markup=cancel_keyboard(),
            )
            return

        clean = clean_username(text)
        recipient = find_user_by_username(clean)
        if not recipient:
            bot_username = await _get_bot_username(bot)
            sender = get_user(user_id)
            invite_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
            await message.answer(
                f"@{clean} hasn't joined Sidicoin yet.\n\n"
                f"Invite them: {invite_link} ✦",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(user_id)
            return

        if str(recipient["telegram_id"]) == str(user_id):
            await message.answer("You can't send SIDI to yourself ✦", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return

        set_pending_action(user_id, "send_amount", {
            "recipient_id": recipient["telegram_id"],
            "recipient_username": recipient.get("username", clean),
            "recipient_name": recipient.get("full_name", ""),
        })

        await message.answer(
            f"✦ Sending to @{recipient.get('username', clean)} "
            f"({recipient.get('full_name', '')})\n\n"
            f"How much SIDI would you like to send?",
            reply_markup=cancel_keyboard(),
        )

    elif action == "send_amount":
        valid, amount = is_valid_amount(text)
        if not valid or amount <= 0:
            await message.answer(
                "Please enter a valid amount (e.g. 500 or ₦12500):",
                reply_markup=cancel_keyboard(),
            )
            return

        sender = get_user(user_id)
        await _process_send_flow(
            message, bot, sender,
            data.get("recipient_username", ""),
            amount,
        )

    # ── Buy flow ──────────────────────────────────────────
    elif action == "buy_amount":
        valid, sidi_amount = is_valid_amount(text)
        if not valid or sidi_amount <= 0:
            await message.answer(
                "Please enter a valid amount (e.g. 500, ₦12500, 1000 SIDI):",
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
            f"✦ <b>Purchase Summary</b>\n\n"
            f"You will receive: <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"Cost: {fmt_naira(naira_cost)}\n"
            f"Fee ({fee_pct}): {fmt_naira(fee_ngn)}\n"
            f"Total to pay: <b>{fmt_naira(total_ngn)}</b>\n"
            f"Payment method: Bank Transfer"
        )
        await message.answer(text, reply_markup=buy_confirm_keyboard())

    # ── Sell flow ──────────────────────────────────────────
    elif action == "sell_amount":
        valid, sidi_amount = is_valid_amount(text)
        if not valid or sidi_amount <= 0:
            await message.answer(
                "Please enter a valid amount:",
                reply_markup=cancel_keyboard(),
            )
            return

        user = get_user(user_id)
        balance = float(user.get("sidi_balance", 0))
        if sidi_amount > balance:
            await message.answer(
                f"Insufficient balance. You have <b>{fmt_number(balance)} SIDI</b> ✦",
                reply_markup=cancel_keyboard(),
            )
            return

        # Check if user has saved bank
        if user.get("bank_account") and user.get("bank_name"):
            set_pending_action(user_id, "sell_bank_check", {"sidi_amount": sidi_amount})

            await message.answer(
                f"✦ <b>Cashout to:</b>\n\n"
                f"🏦 {user.get('bank_name', '')}\n"
                f"Account: {user.get('bank_account', '')}\n"
                f"Name: {user.get('bank_account_name', '')}\n\n"
                f"Use this account?",
                reply_markup=sell_bank_confirm_keyboard(),
            )
        else:
            set_pending_action(user_id, "sell_bank_name", {"sidi_amount": sidi_amount})
            await message.answer(
                "✦ <b>Enter Bank Details</b>\n\n"
                "What bank do you use?\n"
                "Type the bank name (e.g. GTBank, Access Bank, Kuda, OPay):",
                reply_markup=cancel_keyboard(),
            )

    elif action == "sell_bank_name":
        bank_code = get_bank_code(text)
        if not bank_code:
            await message.answer(
                "Bank not recognized. Please try again with a common name "
                "(e.g. GTBank, Access Bank, Kuda, OPay, FirstBank, UBA, Zenith):",
                reply_markup=cancel_keyboard(),
            )
            return

        set_pending_action(user_id, "sell_bank_account", {
            **data,
            "bank_name": text.strip().title(),
            "bank_code": bank_code,
        })

        await message.answer(
            f"✦ Bank: <b>{text.strip().title()}</b>\n\n"
            f"Enter your 10-digit account number:",
            reply_markup=cancel_keyboard(),
        )

    elif action == "sell_bank_account":
        if not is_valid_bank_account(text):
            await message.answer(
                "Please enter a valid 10-digit account number:",
                reply_markup=cancel_keyboard(),
            )
            return

        loading = await message.answer("🏦 Verifying account details...")

        bank_code = data.get("bank_code", "")
        account_number = text.strip()

        # Verify bank account via Korapay
        result = await verify_bank_account(bank_code, account_number)

        if not result.get("success"):
            try:
                await loading.edit_text(
                    f"Could not verify account: {result.get('message', 'Unknown error')}.\n"
                    "Please check and try again ✦",
                    reply_markup=cancel_keyboard(),
                )
            except TelegramBadRequest:
                pass
            return

        account_name = result.get("account_name", "")
        bank_name = data.get("bank_name", "")
        sidi_amount = float(data.get("sidi_amount", 0))

        # Save bank details
        update_bank_details(user_id, bank_name, bank_code, account_number, account_name)

        user = get_user(user_id)
        is_premium = check_premium_status(user)
        fee_sidi = calculate_fee(sidi_amount, is_premium, "sell")
        fee_ngn = sidi_to_naira(fee_sidi)
        gross_ngn = sidi_to_naira(sidi_amount)
        net_ngn = gross_ngn - fee_ngn
        fee_pct = "0.8%" if is_premium else "1.5%"

        set_pending_action(user_id, "sell_confirm", {
            **data,
            "bank_account": account_number,
            "account_name": account_name,
            "fee_sidi": fee_sidi,
            "net_ngn": net_ngn,
        })

        confirm_text = (
            f"✦ <b>Cashout Summary</b>\n\n"
            f"Selling: <b>{fmt_number(sidi_amount)} SIDI</b>\n"
            f"You receive: {fmt_naira(gross_ngn)}\n"
            f"Fee ({fee_pct}): {fmt_naira(fee_ngn)}\n"
            f"Net payout: <b>{fmt_naira(net_ngn)}</b>\n\n"
            f"🏦 {bank_name} — {account_number} — <b>{account_name}</b>\n\n"
            f"Confirm cashout?"
        )

        try:
            await loading.edit_text(confirm_text, reply_markup=sell_confirm_keyboard())
        except TelegramBadRequest:
            await message.answer(confirm_text, reply_markup=sell_confirm_keyboard())

    # ── Settings bank update flow ──────────────────────────
    elif action == "settings_bank_name":
        bank_code = get_bank_code(text)
        if not bank_code:
            await message.answer(
                "Bank not recognized. Please try again:",
                reply_markup=cancel_keyboard(),
            )
            return

        set_pending_action(user_id, "settings_bank_account", {
            "bank_name": text.strip().title(),
            "bank_code": bank_code,
        })

        await message.answer(
            f"✦ Bank: <b>{text.strip().title()}</b>\n\n"
            "Enter your 10-digit account number:",
            reply_markup=cancel_keyboard(),
        )

    elif action == "settings_bank_account":
        if not is_valid_bank_account(text):
            await message.answer(
                "Please enter a valid 10-digit account number:",
                reply_markup=cancel_keyboard(),
            )
            return

        loading = await message.answer("🏦 Verifying account details...")

        bank_code = data.get("bank_code", "")
        account_number = text.strip()

        result = await verify_bank_account(bank_code, account_number)

        if not result.get("success"):
            try:
                await loading.edit_text(
                    f"Could not verify account. Please check and try again ✦",
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
                f"✅ <b>Bank details updated!</b>\n\n"
                f"🏦 {bank_name}\n"
                f"Account: {account_number}\n"
                f"Name: {account_name} ✦",
                reply_markup=settings_keyboard(),
            )
        except TelegramBadRequest:
            pass

    else:
        # Unknown pending action — clear and use AI
        clear_pending_action(user_id)
        loading = await message.answer("✦ Sidi is thinking...")
        ai_response = await get_ai_response(text, message.from_user.first_name or "User")
        try:
            await loading.edit_text(ai_response, reply_markup=home_button_keyboard())
        except TelegramBadRequest:
            pass
