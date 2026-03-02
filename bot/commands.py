"""
All Sidicoin bot command handlers.
Every command shows a loading state first, then edits with the result.
All messages use HTML parse mode with branded formatting.
Beautiful, consistent, and professional throughout.
"""

import os
import time
import random
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
    credit_referrer, can_refer, activate_premium, check_premium_status,
    process_checkin, get_leaderboard, get_user_rank,
    get_all_user_ids, find_user_by_username,
    get_stat, get_all_stats, increment_stat,
    store_pending_payment, track_large_transfer, increment_rate_count,
    update_bank_details, update_user_country, get_user_country,
    generate_device_fingerprint, check_multi_account,
    flag_suspicious_account, is_account_flagged,
    check_withdrawal_locks, unlock_referral_earnings_on_tx,
    create_escrow, get_escrow, fund_escrow, mark_delivered,
    confirm_delivery, raise_dispute, cancel_escrow, get_user_escrows,
    ESCROW_STATUS_PENDING, ESCROW_STATUS_FUNDED, ESCROW_STATUS_DELIVERED,
    MAX_REFERRALS, WELCOME_BONUS_SIDI, WELCOME_BONUS_HOLD_DAYS,
    DAILY_CHECKIN_FREE, DAILY_CHECKIN_PREMIUM,
    MONTHLY_CHECKIN_LIMIT, CHECKIN_REWARDS, CHECKIN_DAY10_BONUS,
)
from services.ton import create_wallet, format_wallet_address
from services.korapay import (
    create_bank_transfer_charge, verify_bank_account,
    process_payout, get_bank_code, COMMON_BANKS,
)
from services.flutterwave import (
    create_payment_link, get_country_config, detect_country_from_language,
    convert_to_ngn, convert_from_ngn, COUNTRY_CONFIG,
)
from services.otp import (
    send_otp_message, verify_otp, needs_otp, is_account_otp_flagged,
    get_otp_failure_count, LARGE_SEND_THRESHOLD,
)
from services.groq import get_ai_response, detect_intent
from services.notifications import notify_user, notify_admin
from utils.formatting import (
    fmt_number, sidi_to_naira, naira_to_sidi, fmt_sidi, fmt_naira,
    fmt_timestamp, fmt_date, fmt_relative_time, time_greeting,
    generate_receipt, generate_mini_receipt, generate_tx_reference,
    generate_downloadable_receipt,
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
    game_menu_keyboard, coinflip_bet_keyboard, coinflip_choice_keyboard,
    dice_bet_keyboard, dice_choice_keyboard, lucky_number_keyboard,
    after_game_keyboard,
    escrow_create_keyboard, escrow_detail_keyboard, escrow_list_keyboard,
    support_keyboard, fund_method_keyboard,
    merchant_keyboard, merchant_apply_keyboard, merchant_pay_confirm_keyboard,
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

        # Check for merchant payment link: pay_MERCHANTID_AMOUNT_REF
        if command.args and command.args.startswith("pay_"):
            existing = get_user(user_id)
            if not existing:
                await message.answer(f"Type /start to create your wallet first, then click the link again {STAR}")
                return
            parts = command.args.split("_", 3)
            if len(parts) >= 3:
                merchant_id = parts[1]
                try:
                    pay_amount = float(parts[2])
                except (ValueError, IndexError):
                    await message.answer("Invalid payment link.", reply_markup=home_keyboard())
                    return
                pay_ref = parts[3] if len(parts) > 3 else f"PAY-{int(time.time())}"

                merchant = get_user(merchant_id)
                if not merchant or not merchant.get("is_merchant") or not merchant.get("merchant_approved"):
                    await message.answer("This merchant is not verified.", reply_markup=home_keyboard())
                    return
                if str(merchant_id) == str(user_id):
                    await message.answer("You can't pay yourself.", reply_markup=home_keyboard())
                    return

                merchant_name = merchant.get("merchant_name", merchant.get("username", "Merchant"))
                fee_rate = float(merchant.get("merchant_fee_rate", 0.02))
                fee = pay_amount * fee_rate
                naira = sidi_to_naira(pay_amount)

                text = (
                    f"\U0001f6d2 <b>Merchant Payment</b>\n\n"
                    f"{DIVIDER}\n\n"
                    f"  Pay to:     <b>{_safe_escape(merchant_name)}</b>\n"
                    f"  Amount:     <b>{fmt_number(pay_amount)} SIDI</b> ({fmt_naira(naira)})\n"
                    f"  Reference:  <code>{_safe_escape(pay_ref)}</code>\n\n"
                    f"{DIVIDER}\n\n"
                    f"This payment goes directly to the merchant.\n"
                    f"Press confirm to pay {STAR}"
                )
                await message.answer(
                    text,
                    reply_markup=merchant_pay_confirm_keyboard(merchant_id, pay_amount, pay_ref),
                )
                return

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

        # Anti-fraud: generate fingerprint and check for multi-accounts
        fingerprint = generate_device_fingerprint({
            "first_name": from_user.first_name or "",
            "last_name": from_user.last_name or "",
            "language_code": from_user.language_code or "",
        })
        multi_check = check_multi_account(user_id, fingerprint)

        # Detect country from Telegram language
        lang_code = from_user.language_code or "en"
        detected_country = detect_country_from_language(lang_code)
        country_config = get_country_config(detected_country)

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

        # Store country, language, and fingerprint
        user["country_code"] = detected_country
        user["currency"] = country_config["currency"]
        user["language_code"] = lang_code
        user["device_fingerprint"] = fingerprint
        if multi_check["is_suspicious"]:
            user["flagged_multi_account"] = True
            user["linked_accounts"] = multi_check["linked_accounts"]
            save_user(user_id, user)
            # Notify admin
            await notify_admin(
                bot,
                f"\u26a0\ufe0f <b>MULTI-ACCOUNT DETECTED</b>\n\n"
                f"New user: @{username} (ID: {user_id})\n"
                f"Linked to: {', '.join(multi_check['linked_accounts'])}\n"
                f"Reason: {multi_check['reason']}\n"
                f"Action: Welcome bonus locked, withdrawals restricted"
            )
        else:
            save_user(user_id, user)

        # Credit referrer if applicable (with 5-referral cap)
        referrer_name_display = ""
        if referred_by:
            try:
                referrer_id = int(referred_by)
                if user_exists(referrer_id) and can_refer(referrer_id):
                    # Earnings are LOCKED until this new user makes a transaction
                    credit_referrer(referrer_id, 10.0, "signup")
                    referrer = get_user(referrer_id)
                    remaining_refs = MAX_REFERRALS - int(referrer.get("referral_count", 0))
                    if referrer:
                        referrer_name_display = referrer.get("full_name", "")
                        await notify_user(
                            bot, referrer_id,
                            f"{STAR} <b>Referral Bonus!</b>\n\n"
                            f"<b>{_safe_escape(first_name)}</b> just joined Sidicoin "
                            f"through your referral link.\n\n"
                            f"+<b>10 SIDI</b> ({fmt_naira(sidi_to_naira(10))}) "
                            f"will be added to your wallet once they "
                            f"make their first transaction.\n\n"
                            f"Referral slots remaining: <b>{remaining_refs}/{MAX_REFERRALS}</b> {STAR}"
                        )
            except (ValueError, Exception) as e:
                logger.error(f"Referral credit error: {e}")

        # Build beautiful welcome message
        referral_line = ""
        if referred_by and referrer_name_display:
            referral_line = (
                f"\n\U0001f91d You joined through <b>{_safe_escape(referrer_name_display)}</b>'s "
                f"referral!\n"
            )
        elif referred_by:
            referral_line = (
                f"\n\U0001f91d You joined through a referral link!\n"
            )

        welcome_naira = sidi_to_naira(WELCOME_BONUS_SIDI)
        country_flag = country_config.get("flag", "\U0001f30d")
        country_name = country_config.get("name", "your country")

        welcome_text = (
            f"{STAR} <b>Welcome to Sidicoin, {_safe_escape(first_name)}</b>\n\n"
            f"Your wallet is ready. {country_flag} {country_name} detected.\n"
            f"Your money moves instantly worldwide.\n"
            f"{referral_line}\n"
            f"{DIVIDER}\n"
            f"  <b>Your Welcome Gift</b>\n\n"
            f"  \U0001f48e  <b>{fmt_number(WELCOME_BONUS_SIDI)} SIDI</b>\n"
            f"  \U0001f4b5  {fmt_naira(welcome_naira)}\n"
            f"  \U0001f512  Withdrawable after {WELCOME_BONUS_HOLD_DAYS} days\n"
            f"{DIVIDER}\n\n"
            f"Sidicoin lets you send money to anyone worldwide using "
            f"just their Telegram @username \u2014 instantly, with zero fees.\n\n"
            f"Let's get you started {STAR}"
        )

        try:
            await loading_msg.edit_text(welcome_text, reply_markup=welcome_keyboard())
        except TelegramBadRequest:
            await message.answer(welcome_text, reply_markup=welcome_keyboard())

        # Send enhanced onboarding step 1
        onboard_text = (
            f"\U0001f44b <b>Welcome aboard!</b>\n\n"
            f"Here's what makes Sidicoin special:\n\n"
            f"  \u26a1 <b>Instant transfers</b>\n"
            f"     Send money in under 2 seconds\n\n"
            f"  \U0001f310 <b>Works across Africa</b>\n"
            f"     Nigeria, Ghana, Kenya & more\n\n"
            f"  \U0001f4b0 <b>Zero fees on transfers</b>\n"
            f"     Send to any Telegram user for free\n\n"
            f"  \U0001f512 <b>Bank-grade security</b>\n"
            f"     Your money is protected 24/7\n\n"
            f"Ready to explore?"
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

        await message.answer(
            f"{STAR} <b>Buy SIDI</b>\n\n"
            f"How much would you like to buy?\n\n"
            f"Enter amount in SIDI or Naira:\n\n"
            f"  <code>500</code>        \u2192 500 SIDI\n"
            f"  <code>2000 SIDI</code>  \u2192 2,000 SIDI\n"
            f"  <code>5000 NGN</code>   \u2192 {fmt_naira(5000)} worth\n"
            f"  <code>5k</code>         \u2192 5,000 SIDI\n\n"
            f"Fee: <b>Free</b> \u2705",
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

        await message.answer(
            f"{STAR} <b>Cash Out SIDI</b>\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?\n"
            f"Fee: <b>Free</b> \u2705",
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
        "game": "\U0001f3ae",
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
        elif tx_type == "game":
            desc = tx.get("description", "Game")
            lines.append(f"{icon} {desc}")
            lines.append(f"     {fmt_naira(sidi_to_naira(amount))} \u2022 {time_str}")
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
        locked = float(user.get("referral_earnings_locked", 0))
        unlocked = float(user.get("referral_earnings_unlocked", 0))
        remaining_slots = max(0, MAX_REFERRALS - count)
        slots_bar = progress_bar(count, MAX_REFERRALS)

        # Check if user has reached the cap
        cap_notice = ""
        if count >= MAX_REFERRALS:
            cap_notice = (
                f"\n  \u26a0\ufe0f You've used all {MAX_REFERRALS} referral slots.\n"
            )

        locked_notice = ""
        if locked > 0:
            locked_notice = (
                f"\n  \U0001f512 Locked: <b>{fmt_number(locked)} SIDI</b>\n"
                f"     <i>Unlocks when your referrals transact</i>\n"
            )

        text = (
            f"{STAR} <b>Refer & Earn</b>\n\n"
            f"Your link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>How It Works</b>\n\n"
            f"  1. Share your link with friends\n"
            f"  2. They sign up (you earn 10 SIDI)\n"
            f"  3. When they make a transaction,\n"
            f"     your earnings unlock for withdrawal\n\n"
            f"  \U0001f91d Per signup    +<b>10 SIDI</b> ({fmt_naira(sidi_to_naira(10))})\n"
            f"  \U0001f512 Locked until they transact\n"
            f"  \U0001f465 Max {MAX_REFERRALS} referrals\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  <b>Your Stats</b>\n\n"
            f"  \U0001f465 Referrals    <b>{count}/{MAX_REFERRALS}</b> {slots_bar}\n"
            f"  \U0001f48e Total earned  <b>{fmt_number(earned)} SIDI</b>\n"
            f"  \u2705 Unlocked     <b>{fmt_number(unlocked)} SIDI</b>\n"
            f"{locked_notice}"
            f"{cap_notice}\n"
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
    """Monthly check-in reward (10 per month, progressive)."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        success, bonus_msg, amount, checkin_num = process_checkin(message.from_user.id)

        if not success:
            # Show schedule with remaining info
            monthly_count = int(user.get("monthly_checkin_count", 0))
            remaining = MONTHLY_CHECKIN_LIMIT - monthly_count
            schedule_lines = []
            for i, reward in enumerate(CHECKIN_REWARDS):
                day = i + 1
                marker = "\u2705" if i < monthly_count else "\u2b1c"
                bonus_label = f" +{int(CHECKIN_DAY10_BONUS)} bonus!" if day == 10 else ""
                schedule_lines.append(f"  {marker} #{day}  {reward} SIDI{bonus_label}")

            text = (
                f"{STAR} <b>Monthly Check-In</b>\n\n"
                f"{bonus_msg}\n\n"
                f"{DIVIDER}\n\n"
                + "\n".join(schedule_lines) + "\n\n"
                f"{DIVIDER}\n\n"
                f"  {remaining} check-ins remaining this month"
            )
            await message.answer(text, reply_markup=home_button_keyboard())
            return

        user = get_user(message.from_user.id)
        balance = float(user.get("sidi_balance", 0))
        remaining = MONTHLY_CHECKIN_LIMIT - checkin_num
        fires = streak_fire(int(user.get("checkin_streak", 0)))

        # Show reward schedule
        schedule_lines = []
        for i, reward in enumerate(CHECKIN_REWARDS):
            day = i + 1
            marker = "\u2705" if i < checkin_num else "\u2b1c"
            bonus_label = f" +{int(CHECKIN_DAY10_BONUS)} bonus!" if day == 10 else ""
            schedule_lines.append(f"  {marker} #{day}  {reward} SIDI{bonus_label}")

        text = (
            f"{STAR} <b>Check-In #{checkin_num} Claimed!</b>\n\n"
            f"+<b>{fmt_number(amount)} SIDI</b> added to your wallet\n"
            f"{bonus_msg}\n\n"
            f"  {fires}  Streak: <b>{int(user.get('checkin_streak', 0))} days</b>\n"
            f"  \U0001f48e  Balance: <b>{fmt_number(balance)} SIDI</b>\n"
            f"  \U0001f4c5  {remaining} check-ins left this month\n\n"
            f"{DIVIDER}\n\n"
            + "\n".join(schedule_lines) + "\n\n"
            f"{DIVIDER}"
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
            f"  All Fees          Free     <b>Free</b>\n"
            f"  Badge             \u2014        <b>{STAR}</b>\n"
            f"  Priority Support  \u2014        <b>\u2705</b>\n"
            f"  Escrow Priority   \u2014        <b>\u2705</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>{fmt_naira(1500)} per month</b>\n"
            f"  10x higher limits + priority support"
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
        f"  /send \u2014 Send SIDI to anyone worldwide\n"
        f"  /send @user 500 \u2014 Quick send\n"
        f"  /contacts \u2014 Saved contacts\n\n"
        f"  <b>\U0001f4b0 Money</b>\n"
        f"  /buy \u2014 Buy SIDI (zero fees)\n"
        f"  /sell \u2014 Cash out to bank (zero fees)\n"
        f"  /history \u2014 Transaction history\n\n"
        f"  <b>\U0001f6e1 Escrow</b>\n"
        f"  /escrow \u2014 Safe P2P trades & transfers\n\n"
        f"  <b>\U0001f381 Earn</b>\n"
        f"  /checkin \u2014 Monthly check-in (10x, up to 44 SIDI)\n"
        f"  /refer \u2014 Earn 10 SIDI per referral (max {MAX_REFERRALS})\n"
        f"  /premium \u2014 Higher limits & priority\n\n"
        f"  <b>\U0001f3ae Games</b>\n"
        f"  /game \u2014 Play games to win SIDI\n\n"
        f"  <b>\U0001f4ca Market</b>\n"
        f"  /price \u2014 SIDI price & market data\n"
        f"  /stats \u2014 Platform statistics\n"
        f"  /leaderboard \u2014 Top holders\n\n"
        f"  <b>\U0001f3e2 Business</b>\n"
        f"  /merchant \u2014 Accept SIDI payments\n\n"
        f"  <b>\u2764\ufe0f Support</b>\n"
        f"  /support \u2014 Help keep Sidicoin free\n\n"
        f"  <b>\u2139\ufe0f Info</b>\n"
        f"  /about \u2014 About Sidicoin\n"
        f"  /help \u2014 This menu\n\n"
        f"{DIVIDER}\n"
        f"  {BRAND} {STAR}"
    )
    await message.answer(text, reply_markup=help_keyboard(), disable_web_page_preview=True)


# =====================================================================
#  /convert  --  Quick SIDI calculator
# =====================================================================

@router.message(Command("convert", "calc"))
async def cmd_convert(message: Message):
    """Quick SIDI/NGN converter."""
    try:
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            await message.answer(
                f"{STAR} <b>SIDI Calculator</b>\n\n"
                f"Quick convert between SIDI and Naira.\n\n"
                f"  <code>/convert 500</code>       \u2192  500 SIDI in Naira\n"
                f"  <code>/convert 5000 NGN</code>  \u2192  {fmt_naira(5000)} in SIDI\n"
                f"  <code>/convert 10k</code>       \u2192  10,000 SIDI in Naira",
                reply_markup=home_button_keyboard(),
            )
            return

        amount_text = " ".join(parts[1:])
        valid, sidi_amount = is_valid_amount(amount_text)

        if not valid:
            await message.answer(
                f"Could not parse that amount. Try: <code>/convert 500</code> {STAR}",
                reply_markup=home_button_keyboard(),
            )
            return

        naira = sidi_to_naira(sidi_amount)
        from utils.formatting import sidi_to_usd, fmt_usd
        usd = sidi_to_usd(sidi_amount)

        await message.answer(
            f"{STAR} <b>Conversion Result</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f48e <b>{fmt_number(sidi_amount)} SIDI</b>\n\n"
            f"  \U0001f4b5 = {fmt_naira(naira)}\n"
            f"  \U0001f4b2 = {fmt_usd(usd)}\n\n"
            f"  Rate: 1 SIDI = {fmt_naira(SIDI_PRICE_NGN)}\n\n"
            f"{DIVIDER}",
            reply_markup=home_button_keyboard(),
        )
    except Exception as e:
        logger.error(f"/convert error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


# =====================================================================
#  /about
# =====================================================================

@router.message(Command("about"))
async def cmd_about(message: Message):
    """About Sidicoin."""
    text = (
        f"{STAR} <b>About Sidicoin</b>\n\n"
        f"Sidicoin (SIDI) is a digital currency for instant "
        f"money transfers \u2014 with one mission: make sending "
        f"money worldwide instant, free, and accessible to everyone.\n\n"
        f"{DIVIDER}\n\n"
        f"  <b>Why Sidicoin?</b>\n\n"
        f"  \u2022 Zero fees on everything\n"
        f"  \u2022 No bank account required\n"
        f"  \u2022 Works in 13+ countries\n"
        f"  \u2022 Escrow for safe P2P trades\n"
        f"  \u2022 Telegram OTP security\n"
        f"  \u2022 Just Telegram and a @username\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"  <b>SIDI Facts</b>\n\n"
        f"  Value        {fmt_naira(25)} per SIDI (stable)\n"
        f"  Fees         Zero on all transactions\n"
        f"  Ticker       SIDI\n"
        f"  Security     Telegram OTP + Escrow\n\n"
        f"  SIDI is a digital balance \u2014 like airtime\n"
        f"  credit or mobile money. It is not a\n"
        f"  speculative investment. 1 SIDI always\n"
        f"  equals {fmt_naira(25)}.\n\n"
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


@router.message(Command("admin_merchant_approve"))
async def cmd_admin_merchant_approve(message: Message, bot: Bot):
    """Approve a merchant application."""
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /admin_merchant_approve <user_id>")
        return
    target_id = parts[1].strip()
    user = get_user(target_id)
    if not user or not user.get("is_merchant"):
        await message.answer("User not found or hasn't applied.")
        return
    user["merchant_approved"] = True
    save_user(target_id, user)
    merchant_name = user.get("merchant_name", "")
    await message.answer(
        f"\u2705 Merchant approved: {merchant_name} (@{user.get('username', target_id)})"
    )
    # Notify merchant
    await notify_user(
        bot, target_id,
        f"\U0001f389 <b>Merchant Approved!</b>\n\n"
        f"Your business <b>{_safe_escape(merchant_name)}</b> is now verified.\n\n"
        f"Type /merchant to generate payment links {STAR}",
    )


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
        await callback.message.edit_text(
            f"{STAR} <b>Buy SIDI</b>\n\n"
            f"How much would you like to buy?\n\n"
            f"  <code>500</code>        \u2192 500 SIDI\n"
            f"  <code>2000 SIDI</code>  \u2192 2,000 SIDI\n"
            f"  <code>5000 NGN</code>   \u2192 {fmt_naira(5000)} worth\n"
            f"  <code>5k</code>         \u2192 5,000 SIDI\n\n"
            f"Fee: <b>Free</b> \u2705",
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
        await callback.message.edit_text(
            f"{STAR} <b>Cash Out SIDI</b>\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b> ({fmt_naira(sidi_to_naira(balance))})\n\n"
            f"How much SIDI would you like to cash out?\n"
            f"Fee: <b>Free</b> \u2705",
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
        locked = float(user.get("referral_earnings_locked", 0))
        unlocked = float(user.get("referral_earnings_unlocked", 0))
        remaining_slots = max(0, MAX_REFERRALS - count)

        cap_line = ""
        if count >= MAX_REFERRALS:
            cap_line = f"\n  \u26a0\ufe0f All {MAX_REFERRALS} slots used\n"

        locked_line = ""
        if locked > 0:
            locked_line = f"\n  \U0001f512 Locked: {fmt_number(locked)} SIDI (awaiting referral tx)\n"

        text = (
            f"{STAR} <b>Refer & Earn</b>\n\n"
            f"Your link:\n<code>{ref_link}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f91d Per signup    +<b>10 SIDI</b> (locked)\n"
            f"  \U0001f513 Unlocks when they transact\n"
            f"  \U0001f465 Max {MAX_REFERRALS} referrals\n\n"
            f"  \U0001f465 Referrals: <b>{count}/{MAX_REFERRALS}</b>\n"
            f"  \U0001f48e Earned: <b>{fmt_number(earned)} SIDI</b>\n"
            f"  \u2705 Unlocked: <b>{fmt_number(unlocked)} SIDI</b>\n"
            f"{locked_line}{cap_line}\n"
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
            f"  /merchant \u2014 Business payments\n"
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
    """Monthly check-in from inline button."""
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        success, bonus_msg, amount, checkin_num = process_checkin(callback.from_user.id)
        if not success:
            await callback.answer(bonus_msg, show_alert=True)
            return
        user = get_user(callback.from_user.id)
        balance = float(user.get("sidi_balance", 0))
        remaining = MONTHLY_CHECKIN_LIMIT - checkin_num
        fires = streak_fire(int(user.get("checkin_streak", 0)))
        text = (
            f"{STAR} <b>Check-In #{checkin_num} Claimed!</b>\n\n"
            f"+<b>{fmt_number(amount)} SIDI</b>\n"
            f"{bonus_msg}\n\n"
            f"  {fires}  Streak: <b>{int(user.get('checkin_streak', 0))} days</b>\n"
            f"  \U0001f48e  Balance: <b>{fmt_number(balance)} SIDI</b>\n"
            f"  \U0001f4c5  {remaining} check-ins left this month"
        )
        await callback.message.edit_text(text, reply_markup=home_keyboard())
        await callback.answer(f"+{fmt_number(amount)} SIDI! #{checkin_num}/10")
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
            f"  Daily Check-in    {fmt_number(DAILY_CHECKIN_FREE)}       <b>{fmt_number(DAILY_CHECKIN_PREMIUM)} SIDI</b>\n"
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
            f"\U0001f4a1 <b>How It Works</b>\n\n"
            f"Sending money is as easy as texting:\n\n"
            f"  <b>Step 1:</b> Type <code>/send @friend 100</code>\n"
            f"  <b>Step 2:</b> Confirm the transfer\n"
            f"  <b>Step 3:</b> Done! They receive instantly\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  \U0001f4b3 <b>Buy SIDI</b> with Naira via bank transfer\n"
            f"  \U0001f4b0 <b>Cash out</b> to any Nigerian bank\n"
            f"  \U0001f381 <b>Earn free</b> SIDI every day\n"
            f"  \U0001f3ae <b>Play games</b> to win more SIDI\n\n"
            f"No bank details needed. No stress {STAR}"
        )
        await callback.message.edit_text(text, reply_markup=onboarding_step2_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "onboard_3")
async def cb_onboard_3(callback: CallbackQuery):
    try:
        welcome_naira = sidi_to_naira(WELCOME_BONUS_SIDI)
        text = (
            f"\U0001f680 <b>You're All Set!</b>\n\n"
            f"You have <b>{fmt_number(WELCOME_BONUS_SIDI)} SIDI</b> ({fmt_naira(welcome_naira)}) ready to go.\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>Quick Actions:</b>\n\n"
            f"  \U0001f4b3 <b>Buy SIDI</b> \u2014 top up with Naira\n"
            f"  \U0001f381 <b>Refer friends</b> \u2014 earn 10 SIDI each (max {MAX_REFERRALS})\n"
            f"  \u2705 <b>Daily check-in</b> \u2014 earn {fmt_number(DAILY_CHECKIN_FREE)} SIDI/day\n"
            f"  \U0001f3ae <b>Play games</b> \u2014 win SIDI by playing\n\n"
            f"{DIVIDER}\n\n"
            f"What's your first move? {STAR}"
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
    """Execute confirmed transfer -- OTP for large amounts."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "send_confirm" or not data:
            await callback.answer("No pending transfer found")
            return

        amount = float(data.get("amount", 0))

        # OTP check for large sends
        if needs_otp(callback.from_user.id, "send_confirm", amount):
            if is_account_otp_flagged(callback.from_user.id):
                await callback.message.edit_text(
                    f"\u26d4 <b>Account Locked</b>\n\n"
                    f"Too many failed verifications. Contact support {STAR}",
                    reply_markup=home_button_keyboard(),
                )
                clear_pending_action(callback.from_user.id)
                await callback.answer()
                return

            otp_result = await send_otp_message(bot, callback.from_user.id, "send_confirm", data)
            if otp_result.get("cooldown"):
                await callback.answer(otp_result["message"], show_alert=True)
                return
            if otp_result.get("success"):
                set_pending_action(callback.from_user.id, "otp_verify", {
                    "original_action": "send_execute",
                    "original_data": data,
                })
                try:
                    await callback.message.edit_text(
                        f"\U0001f510 <b>Verification Required</b>\n\n"
                        f"Large transfer of <b>{fmt_number(amount)} SIDI</b> detected.\n"
                        f"A 6-digit code has been sent to you.\n"
                        f"Enter the code to confirm.\n\n"
                        f"Code expires in 5 minutes.",
                        reply_markup=cancel_keyboard(),
                    )
                except TelegramBadRequest:
                    pass
                await callback.answer()
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

        # Unlock referral earnings when user transacts
        unlock_referral_earnings_on_tx(callback.from_user.id)

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
#  DOWNLOADABLE RECEIPT
# =====================================================================

@router.callback_query(F.data == "receipt_download")
async def cb_receipt_download(callback: CallbackQuery):
    """Generate and send a downloadable .txt receipt file for the last transaction."""
    try:
        import io
        from aiogram.types import BufferedInputFile

        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("No wallet found")
            return

        txns = user.get("transactions", [])
        if not txns or not isinstance(txns, list):
            await callback.answer("No transactions found")
            return

        # Get the most recent transaction
        last_tx = txns[-1] if txns else None
        if not last_tx:
            await callback.answer("No recent transaction")
            return

        tx_type = last_tx.get("type", "Unknown")
        amount = float(last_tx.get("amount", 0))
        ref = last_tx.get("reference", "N/A")
        description = last_tx.get("description", "")
        other_user = last_tx.get("other_username", "")

        # Determine sender/recipient based on tx type
        username = user.get("username", "")
        if tx_type == "send":
            sender = username
            recipient = other_user or description.replace("Sent to @", "")
        elif tx_type == "receive":
            sender = other_user or description.replace("Received from @", "")
            recipient = username
        elif tx_type == "buy":
            sender = "Korapay"
            recipient = username
        elif tx_type == "sell":
            sender = username
            recipient = description or "Bank Account"
        else:
            sender = username
            recipient = other_user or "N/A"

        fee = float(last_tx.get("fee", 0))
        bank_info = ""
        if tx_type in ("sell", "cashout"):
            bank_info = description

        # Generate the downloadable receipt text
        receipt_text = generate_downloadable_receipt(
            tx_type=tx_type.title(),
            sender=sender,
            recipient=recipient,
            sidi_amount=amount,
            fee=fee,
            reference=ref,
            bank_info=bank_info,
        )

        # Create file buffer
        file_bytes = receipt_text.encode("utf-8")
        filename = f"sidicoin_receipt_{ref}.txt"
        doc = BufferedInputFile(file=file_bytes, filename=filename)

        await callback.message.answer_document(
            document=doc,
            caption=f"{STAR} Your Sidicoin receipt \u2014 Ref: <code>{ref}</code>",
            parse_mode="HTML",
        )
        await callback.answer("Receipt ready!")

    except Exception as e:
        logger.error(f"receipt_download error: {e}", exc_info=True)
        await callback.answer("Could not generate receipt. Try again.")


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
    """Execute cashout -- requires OTP verification."""
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "sell_confirm" or not data:
            await callback.answer("No pending cashout found")
            return

        # OTP check
        if needs_otp(callback.from_user.id, "sell_confirm"):
            if is_account_otp_flagged(callback.from_user.id):
                await callback.message.edit_text(
                    f"\u26d4 <b>Account Locked</b>\n\n"
                    f"Too many failed verifications. Contact support {STAR}",
                    reply_markup=home_button_keyboard(),
                )
                from services.notifications import notify_admin as _admin_notify
                await _admin_notify(bot,
                    f"\u26a0\ufe0f OTP FLAG: User {callback.from_user.id} locked "
                    f"({get_otp_failure_count(callback.from_user.id)} failures)")
                clear_pending_action(callback.from_user.id)
                await callback.answer()
                return

            otp_result = await send_otp_message(bot, callback.from_user.id, "sell_confirm", data)
            if otp_result.get("cooldown"):
                await callback.answer(otp_result["message"], show_alert=True)
                return
            if otp_result.get("success"):
                set_pending_action(callback.from_user.id, "otp_verify", {
                    "original_action": "sell_execute",
                    "original_data": data,
                })
                try:
                    await callback.message.edit_text(
                        f"\U0001f510 <b>Verification Required</b>\n\n"
                        f"A 6-digit code has been sent to you.\n"
                        f"Enter the code to confirm your cashout.\n\n"
                        f"Code expires in 5 minutes.",
                        reply_markup=cancel_keyboard(),
                    )
                except TelegramBadRequest:
                    pass
                await callback.answer()
                return
            else:
                await callback.answer(otp_result.get("message", "Could not send code"), show_alert=True)
                return

        try:
            await callback.message.edit_text("\U0001f4b8 Processing your cashout...")
        except TelegramBadRequest:
            pass

        user = get_user(callback.from_user.id)

        # Check all withdrawal locks (welcome bonus hold, multi-account, banned)
        lock_check = check_withdrawal_locks(callback.from_user.id)
        if not lock_check["can_withdraw"]:
            remaining_secs = lock_check["remaining_secs"]
            reason = lock_check["reason"]
            if reason == "welcome_hold":
                days = remaining_secs // 86400
                hours = (remaining_secs % 86400) // 3600
                mins = (remaining_secs % 3600) // 60
                await callback.message.edit_text(
                    f"\U0001f512 <b>Welcome Bonus Protection</b>\n\n"
                    f"Your welcome bonus is locked for\n"
                    f"<b>{WELCOME_BONUS_HOLD_DAYS} days</b> as a security measure.\n\n"
                    f"Time remaining: <b>{days}d {hours}h {mins}m</b>\n\n"
                    f"This protects against fraud.\n"
                    f"Your SIDI is safe in your wallet {STAR}",
                    reply_markup=home_button_keyboard(),
                )
            elif reason == "cashout_hold":
                hours = remaining_secs // 3600
                mins = (remaining_secs % 3600) // 60
                await callback.message.edit_text(
                    f"\u23f3 <b>Cashout Hold Active</b>\n\n"
                    f"Time remaining: <b>{hours}h {mins}m</b>\n\n"
                    f"This is a security measure.\n"
                    f"Your SIDI is safe in your wallet {STAR}",
                    reply_markup=home_button_keyboard(),
                )
            else:
                await callback.message.edit_text(
                    f"\u26d4 <b>Withdrawal Restricted</b>\n\n"
                    f"{reason}\n\n"
                    f"Please contact support for help {STAR}",
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
async def cb_settings_bank(callback: CallbackQuery, bot: Bot):
    try:
        # OTP check for bank details change
        if needs_otp(callback.from_user.id, "bank_change"):
            if is_account_otp_flagged(callback.from_user.id):
                await callback.answer("Account locked due to failed verifications", show_alert=True)
                return

            otp_result = await send_otp_message(bot, callback.from_user.id, "bank_change", {})
            if otp_result.get("cooldown"):
                await callback.answer(otp_result["message"], show_alert=True)
                return
            if otp_result.get("success"):
                set_pending_action(callback.from_user.id, "otp_verify", {
                    "original_action": "bank_change_start",
                    "original_data": {},
                })
                try:
                    await callback.message.edit_text(
                        f"\U0001f510 <b>Verification Required</b>\n\n"
                        f"Changing bank details requires verification.\n"
                        f"A 6-digit code has been sent to you.\n"
                        f"Enter the code to proceed.\n\n"
                        f"Code expires in 5 minutes.",
                        reply_markup=cancel_keyboard(),
                    )
                except TelegramBadRequest:
                    pass
                await callback.answer()
                return

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
#  ESCROW
# =====================================================================

@router.message(Command("escrow"))
async def cmd_escrow(message: Message):
    """Show escrow menu."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        active = get_user_escrows(str(message.from_user.id))
        active_count = len(active)
        completed = int(user.get("escrow_completed", 0))
        rating = float(user.get("escrow_rating", 5.0))

        text = (
            f"\U0001f6e1 <b>Sidicoin Escrow</b>\n\n"
            f"Trade safely on Telegram. Your money is\n"
            f"held securely until both parties confirm.\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>How It Works</b>\n\n"
            f"  1. Create an escrow (seller or buyer)\n"
            f"  2. Buyer funds the escrow (SIDI locked)\n"
            f"  3. Seller delivers the item/service\n"
            f"  4. Buyer confirms delivery\n"
            f"  5. SIDI released to seller instantly\n\n"
            f"  \U0001f512 Funds are 100% protected\n"
            f"  \u26a0\ufe0f Disputes handled by our team\n"
            f"  \U0001f4b0 Zero fees on escrow\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  Active escrows: <b>{active_count}</b>\n"
            f"  Completed: <b>{completed}</b>\n"
            f"  Trust score: <b>{rating:.1f}/5.0</b>\n\n"
            f"{DIVIDER}"
        )
        await message.answer(text, reply_markup=escrow_create_keyboard())

    except Exception as e:
        logger.error(f"/escrow error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


@router.callback_query(F.data == "cmd_escrow")
async def cb_escrow(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        active = get_user_escrows(str(callback.from_user.id))
        text = (
            f"\U0001f6e1 <b>Sidicoin Escrow</b>\n\n"
            f"Trade safely. Create or manage escrows.\n\n"
            f"  Active: <b>{len(active)}</b>\n"
            f"  Completed: <b>{user.get('escrow_completed', 0)}</b>"
        )
        await callback.message.edit_text(text, reply_markup=escrow_create_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_escrow error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.in_({"escrow_new_p2p", "escrow_new_xborder"}))
async def cb_escrow_new(callback: CallbackQuery):
    try:
        escrow_type = "p2p_trade" if callback.data == "escrow_new_p2p" else "cross_border"
        type_label = "P2P Trade" if escrow_type == "p2p_trade" else "Cross-Border Transfer"

        set_pending_action(callback.from_user.id, "escrow_role_select", {"escrow_type": escrow_type})
        text = (
            f"\U0001f6e1 <b>New {type_label} Escrow</b>\n\n"
            f"Are you the buyer or seller?\n\n"
            f"  \U0001f6d2 <b>Seller</b> \u2014 You are selling an item/service\n"
            f"  \U0001f4b3 <b>Buyer</b> \u2014 You are buying and will fund escrow"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="\U0001f6d2 I'm the Seller", callback_data="escrow_role_seller"),
                InlineKeyboardButton(text="\U0001f4b3 I'm the Buyer", callback_data="escrow_role_buyer"),
            ],
            [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
        ]))
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.in_({"escrow_role_seller", "escrow_role_buyer"}))
async def cb_escrow_role(callback: CallbackQuery):
    try:
        action, data = get_pending_action(callback.from_user.id)
        role = "seller" if callback.data == "escrow_role_seller" else "buyer"
        set_pending_action(callback.from_user.id, "escrow_description", {
            **data, "my_role": role,
        })
        await callback.message.edit_text(
            f"\U0001f6e1 <b>Escrow Description</b>\n\n"
            f"Briefly describe what's being traded:\n"
            f"e.g. \"iPhone 15 Pro Max\", \"Logo design\", \"100 USD transfer\"",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "escrow_list")
async def cb_escrow_list(callback: CallbackQuery):
    try:
        escrows = get_user_escrows(str(callback.from_user.id))
        if not escrows:
            await callback.message.edit_text(
                f"\U0001f6e1 <b>My Escrows</b>\n\nNo active escrows. Create one to get started {STAR}",
                reply_markup=escrow_create_keyboard(),
            )
            await callback.answer()
            return

        await callback.message.edit_text(
            f"\U0001f6e1 <b>My Escrows</b> ({len(escrows)} active)\n\n"
            f"Tap an escrow to view details:",
            reply_markup=escrow_list_keyboard(escrows),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_list error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.startswith("escrow_view_"))
async def cb_escrow_view(callback: CallbackQuery):
    try:
        escrow_id = callback.data.replace("escrow_view_", "")
        escrow = get_escrow(escrow_id)
        if not escrow:
            await callback.answer("Escrow not found")
            return

        uid = str(callback.from_user.id)
        role = "seller" if escrow["seller_id"] == uid else "buyer"
        status = escrow.get("status", "pending")
        amount = float(escrow.get("amount_sidi", 0))
        naira = sidi_to_naira(amount)

        seller = get_user(escrow["seller_id"])
        buyer = get_user(escrow["buyer_id"])
        s_name = seller.get("username", "") if seller else escrow["seller_id"]
        b_name = buyer.get("username", "") if buyer else escrow["buyer_id"]

        status_display = {
            "pending": "\u23f3 Pending (awaiting funding)",
            "funded": "\U0001f4b3 Funded (awaiting delivery)",
            "delivered": "\U0001f4e6 Delivered (awaiting confirmation)",
            "disputed": "\u26a0\ufe0f Disputed (under review)",
            "released": "\u2705 Completed",
            "cancelled": "\u274c Cancelled",
        }.get(status, status)

        text = (
            f"\U0001f6e1 <b>Escrow Details</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  ID:          <code>{escrow_id}</code>\n"
            f"  Amount:      <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n"
            f"  Seller:      @{s_name}\n"
            f"  Buyer:       @{b_name}\n"
            f"  Your role:   {role.title()}\n"
            f"  Description: {_safe_escape(escrow.get('description', ''))}\n"
            f"  Status:      {status_display}\n"
            f"  Created:     {fmt_relative_time(escrow.get('created_at', 0))}\n\n"
            f"{DIVIDER}"
        )
        from bot.keyboards import escrow_detail_keyboard
        await callback.message.edit_text(text, reply_markup=escrow_detail_keyboard(escrow_id, role, status))
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_view error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.startswith("escrow_fund_"))
async def cb_escrow_fund(callback: CallbackQuery, bot: Bot):
    try:
        escrow_id = callback.data.replace("escrow_fund_", "")

        # OTP check for escrow funding
        if needs_otp(callback.from_user.id, "escrow_fund"):
            if is_account_otp_flagged(callback.from_user.id):
                await callback.answer("Account locked due to failed verifications", show_alert=True)
                return

            otp_data = {"escrow_id": escrow_id}
            otp_result = await send_otp_message(bot, callback.from_user.id, "escrow_fund", otp_data)
            if otp_result.get("cooldown"):
                await callback.answer(otp_result["message"], show_alert=True)
                return
            if otp_result.get("success"):
                set_pending_action(callback.from_user.id, "otp_verify", {
                    "original_action": "escrow_fund_execute",
                    "original_data": otp_data,
                })
                escrow = get_escrow(escrow_id)
                amount = float(escrow.get("amount_sidi", 0)) if escrow else 0
                try:
                    await callback.message.edit_text(
                        f"\U0001f510 <b>Verification Required</b>\n\n"
                        f"Funding escrow of <b>{fmt_number(amount)} SIDI</b>.\n"
                        f"A 6-digit code has been sent to you.\n"
                        f"Enter the code to confirm.\n\n"
                        f"Code expires in 5 minutes.",
                        reply_markup=cancel_keyboard(),
                    )
                except TelegramBadRequest:
                    pass
                await callback.answer()
                return

        result = fund_escrow(escrow_id, str(callback.from_user.id))
        if result.get("success"):
            escrow = get_escrow(escrow_id)
            amount = float(escrow.get("amount_sidi", 0))
            await callback.message.edit_text(
                f"\u2705 <b>Escrow Funded!</b>\n\n"
                f"<b>{fmt_number(amount)} SIDI</b> locked in escrow.\n\n"
                f"The seller can now deliver. Once you confirm\n"
                f"delivery, the funds will be released {STAR}",
                reply_markup=home_button_keyboard(),
            )
            # Notify seller
            from services.notifications import notify_user as _notify
            await _notify(
                bot, escrow["seller_id"],
                f"\U0001f4b3 <b>Escrow Funded!</b>\n\n"
                f"Buyer funded escrow <code>{escrow_id}</code>.\n"
                f"Amount: <b>{fmt_number(amount)} SIDI</b>\n\n"
                f"Please deliver now. Type /escrow to manage {STAR}",
            )
        else:
            await callback.answer(result.get("message", "Could not fund"), show_alert=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_fund error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.startswith("escrow_deliver_"))
async def cb_escrow_deliver(callback: CallbackQuery, bot: Bot):
    try:
        escrow_id = callback.data.replace("escrow_deliver_", "")
        result = mark_delivered(escrow_id, str(callback.from_user.id))
        if result.get("success"):
            escrow = get_escrow(escrow_id)
            await callback.message.edit_text(
                f"\U0001f4e6 <b>Marked as Delivered!</b>\n\n"
                f"Waiting for buyer to confirm delivery.\n"
                f"Funds will be released once confirmed {STAR}",
                reply_markup=home_button_keyboard(),
            )
            from services.notifications import notify_user as _notify
            await _notify(
                bot, escrow["buyer_id"],
                f"\U0001f4e6 <b>Delivery Notification</b>\n\n"
                f"Seller marked escrow <code>{escrow_id}</code> as delivered.\n\n"
                f"Please confirm if you received everything.\n"
                f"Type /escrow to confirm or dispute {STAR}",
            )
        else:
            await callback.answer(result.get("message", "Error"), show_alert=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_deliver error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.startswith("escrow_confirm_"))
async def cb_escrow_confirm(callback: CallbackQuery, bot: Bot):
    try:
        escrow_id = callback.data.replace("escrow_confirm_", "")
        escrow = get_escrow(escrow_id)
        if not escrow:
            await callback.answer("Escrow not found")
            return

        result = confirm_delivery(escrow_id, str(callback.from_user.id))
        if result.get("success"):
            amount = float(result.get("amount", 0))
            await callback.message.edit_text(
                f"\u2705 <b>Escrow Complete!</b>\n\n"
                f"<b>{fmt_number(amount)} SIDI</b> has been released to the seller.\n\n"
                f"Trade completed successfully. Thank you for\n"
                f"using Sidicoin Escrow {STAR}",
                reply_markup=home_keyboard(),
            )
            from services.notifications import notify_user as _notify
            await _notify(
                bot, escrow["seller_id"],
                f"\u2705 <b>Funds Released!</b>\n\n"
                f"Buyer confirmed delivery on <code>{escrow_id}</code>.\n"
                f"+<b>{fmt_number(amount)} SIDI</b> added to your wallet {STAR}",
            )
        else:
            await callback.answer(result.get("message", "Error"), show_alert=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_confirm error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.startswith("escrow_dispute_"))
async def cb_escrow_dispute(callback: CallbackQuery):
    try:
        escrow_id = callback.data.replace("escrow_dispute_", "")
        set_pending_action(callback.from_user.id, "escrow_dispute_reason", {"escrow_id": escrow_id})
        await callback.message.edit_text(
            f"\u26a0\ufe0f <b>File a Dispute</b>\n\n"
            f"Escrow: <code>{escrow_id}</code>\n\n"
            f"Please describe the issue. Our team will\n"
            f"review and resolve this fairly.\n\n"
            f"Type your reason below:",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("escrow_cancel_"))
async def cb_escrow_cancel(callback: CallbackQuery):
    try:
        escrow_id = callback.data.replace("escrow_cancel_", "")
        result = cancel_escrow(escrow_id, str(callback.from_user.id))
        if result.get("success"):
            await callback.message.edit_text(
                f"\u274c Escrow <code>{escrow_id}</code> cancelled {STAR}",
                reply_markup=home_keyboard(),
            )
        else:
            await callback.answer(result.get("message", "Error"), show_alert=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"escrow_cancel error: {e}")
        await callback.answer("Something went wrong")


# =====================================================================
#  SUPPORT / DONATE
# =====================================================================

@router.message(Command("support", "donate"))
async def cmd_support(message: Message):
    """Support Sidicoin with a voluntary donation."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        total_donated = get_stat("total_donations")
        text = (
            f"{STAR} <b>Support Sidicoin</b>\n\n"
            f"Sidicoin is committed to keeping all transfers\n"
            f"and transactions <b>100% free</b> for everyone.\n\n"
            f"Your voluntary support helps us:\n\n"
            f"  \u2022 Keep zero fees forever\n"
            f"  \u2022 Expand to more countries\n"
            f"  \u2022 Improve security & features\n"
            f"  \u2022 Run servers & infrastructure\n\n"
            f"{DIVIDER}\n\n"
            f"  Total community support: <b>{fmt_number(total_donated)} SIDI</b>\n"
            f"  ({fmt_naira(sidi_to_naira(total_donated))})\n\n"
            f"{DIVIDER}\n\n"
            f"Every SIDI counts. Thank you {STAR}"
        )
        await message.answer(text, reply_markup=support_keyboard())

    except Exception as e:
        logger.error(f"/support error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


@router.callback_query(F.data == "cmd_support")
async def cb_support(callback: CallbackQuery):
    try:
        total_donated = get_stat("total_donations")
        text = (
            f"{STAR} <b>Support Sidicoin</b>\n\n"
            f"Help us keep everything free.\n\n"
            f"  Total support: <b>{fmt_number(total_donated)} SIDI</b>"
        )
        await callback.message.edit_text(text, reply_markup=support_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "support_sidi")
async def cb_support_sidi(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        set_pending_action(callback.from_user.id, "support_amount")
        await callback.message.edit_text(
            f"{STAR} <b>Support with SIDI</b>\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b>\n\n"
            f"How much would you like to donate?",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


# =====================================================================
#  MERCHANT
# =====================================================================

@router.message(Command("merchant"))
async def cmd_merchant(message: Message):
    """Merchant tools -- generate payment links."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        if user.get("is_merchant") and user.get("merchant_approved"):
            merchant_name = user.get("merchant_name", user.get("username", ""))
            total_received = float(user.get("merchant_total_received", 0))
            total_fees = float(user.get("merchant_total_fees", 0))
            fee_rate = float(user.get("merchant_fee_rate", 0.02))

            text = (
                f"\U0001f3e2 <b>Merchant Dashboard</b>\n\n"
                f"  Business: <b>{_safe_escape(merchant_name)}</b>\n"
                f"  Fee rate: <b>{fee_rate * 100:.1f}%</b> per transaction\n\n"
                f"{DIVIDER}\n\n"
                f"  Total received: <b>{fmt_number(total_received)} SIDI</b>\n"
                f"  Fees paid:      <b>{fmt_number(total_fees)} SIDI</b>\n"
                f"  Net earned:     <b>{fmt_number(total_received - total_fees)} SIDI</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  Generate a payment link to collect SIDI\n"
                f"  from your customers. Share the link anywhere.\n\n"
                f"  Users pay you free. You pay 2% service fee {STAR}"
            )
            await message.answer(text, reply_markup=merchant_keyboard())

        elif user.get("is_merchant") and not user.get("merchant_approved"):
            await message.answer(
                f"\u23f3 <b>Application Pending</b>\n\n"
                f"Your merchant application is being reviewed.\n"
                f"We'll notify you once approved {STAR}",
                reply_markup=home_button_keyboard(),
            )
        else:
            text = (
                f"\U0001f3e2 <b>Sidicoin for Business</b>\n\n"
                f"Accept SIDI payments from customers.\n\n"
                f"{DIVIDER}\n\n"
                f"  <b>How it works:</b>\n\n"
                f"  1. Apply to become a merchant\n"
                f"  2. Generate payment links\n"
                f"  3. Share links with customers\n"
                f"  4. Receive SIDI instantly\n\n"
                f"  <b>Pricing:</b>\n\n"
                f"  \u2022 Customers pay: <b>Free</b>\n"
                f"  \u2022 Merchant fee:  <b>2%</b> per transaction\n"
                f"  \u2022 Cash out:      <b>Free</b>\n\n"
                f"{DIVIDER}"
            )
            await message.answer(text, reply_markup=merchant_apply_keyboard())

    except Exception as e:
        logger.error(f"/merchant error: {e}", exc_info=True)
        await message.answer(f"Something went wrong {STAR}")


@router.callback_query(F.data == "merchant_apply")
async def cb_merchant_apply(callback: CallbackQuery, bot: Bot):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return

        set_pending_action(callback.from_user.id, "merchant_apply_name")
        await callback.message.edit_text(
            f"\U0001f3e2 <b>Merchant Application</b>\n\n"
            f"Enter your business name:",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "merchant_create_link")
async def cb_merchant_create_link(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user or not user.get("merchant_approved"):
            await callback.answer("Not a verified merchant")
            return

        set_pending_action(callback.from_user.id, "merchant_link_amount")
        await callback.message.edit_text(
            f"\U0001f517 <b>Generate Payment Link</b>\n\n"
            f"Enter the amount in SIDI:",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data == "merchant_stats")
async def cb_merchant_stats(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        total_received = float(user.get("merchant_total_received", 0))
        total_fees = float(user.get("merchant_total_fees", 0))
        await callback.answer(
            f"Received: {fmt_number(total_received)} SIDI | Fees: {fmt_number(total_fees)} SIDI",
            show_alert=True,
        )
    except Exception:
        await callback.answer("Error loading stats")


@router.callback_query(F.data.startswith("merchant_pay_"))
async def cb_merchant_pay(callback: CallbackQuery, bot: Bot):
    """Process merchant payment from deep link."""
    try:
        # Format: merchant_pay_MERCHANTID_AMOUNT_REF
        parts = callback.data.split("_", 4)
        if len(parts) < 5:
            await callback.answer("Invalid payment")
            return

        merchant_id = parts[2]
        try:
            amount = float(parts[3])
        except ValueError:
            await callback.answer("Invalid amount")
            return
        ref = parts[4]

        payer = get_user(callback.from_user.id)
        if not payer:
            await callback.answer("Please /start first")
            return

        merchant = get_user(merchant_id)
        if not merchant or not merchant.get("merchant_approved"):
            await callback.answer("Merchant not found")
            return

        # Check payer balance
        payer_balance = float(payer.get("sidi_balance", 0))
        if payer_balance < amount:
            await callback.answer("Insufficient balance", show_alert=True)
            return

        # Calculate merchant fee (2%)
        fee_rate = float(merchant.get("merchant_fee_rate", 0.02))
        fee = amount * fee_rate
        net_to_merchant = amount - fee

        # Deduct from payer
        update_balance(callback.from_user.id, -amount)
        # Credit merchant (minus fee)
        update_balance(merchant_id, net_to_merchant)

        # Track merchant stats
        merchant["merchant_total_received"] = float(merchant.get("merchant_total_received", 0)) + amount
        merchant["merchant_total_fees"] = float(merchant.get("merchant_total_fees", 0)) + fee
        save_user(merchant_id, merchant)

        # Track platform revenue
        increment_stat("merchant_fees_total", fee)
        increment_stat("merchant_tx_count", 1)

        # Record transactions
        now = int(time.time())
        tx_ref = generate_tx_reference()
        merchant_name = merchant.get("merchant_name", merchant.get("username", ""))
        payer_username = payer.get("username", "")

        add_transaction(callback.from_user.id, {
            "type": "merchant_pay", "amount": amount,
            "description": f"Payment to {merchant_name} (ref: {ref})",
            "timestamp": now, "reference": tx_ref,
        })
        add_transaction(merchant_id, {
            "type": "merchant_receive", "amount": net_to_merchant,
            "fee": fee,
            "description": f"Payment from @{payer_username} (ref: {ref})",
            "timestamp": now, "reference": tx_ref,
        })

        clear_pending_action(callback.from_user.id)
        naira = sidi_to_naira(amount)

        payer = get_user(callback.from_user.id)
        new_balance = float(payer.get("sidi_balance", 0))

        await callback.message.edit_text(
            f"\u2705 <b>Payment Successful!</b>\n\n"
            f"  Paid to:    <b>{_safe_escape(merchant_name)}</b>\n"
            f"  Amount:     <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n"
            f"  Reference:  <code>{_safe_escape(ref)}</code>\n\n"
            f"  \U0001f48e Balance: <b>{fmt_number(new_balance)} SIDI</b> {STAR}",
            reply_markup=home_keyboard(),
        )
        await callback.answer(f"Paid {fmt_number(amount)} SIDI!")

        # Notify merchant
        await notify_user(
            bot, merchant_id,
            f"\U0001f4b0 <b>Payment Received!</b>\n\n"
            f"  From:      @{payer_username}\n"
            f"  Amount:    <b>{fmt_number(amount)} SIDI</b>\n"
            f"  Fee (2%):  -{fmt_number(fee)} SIDI\n"
            f"  Net:       <b>{fmt_number(net_to_merchant)} SIDI</b>\n"
            f"  Reference: {ref}\n\n"
            f"  Type /merchant to view your dashboard {STAR}",
        )

    except Exception as e:
        logger.error(f"merchant_pay error: {e}", exc_info=True)
        await callback.answer("Payment failed")


# =====================================================================
#  OTP POST-VERIFICATION EXECUTORS
# =====================================================================

async def _execute_sell(message: Message, bot: Bot, user_id: int, data: dict):
    """Execute cashout after OTP verification."""
    try:
        user = get_user(user_id)
        lock_check = check_withdrawal_locks(user_id)
        if not lock_check["can_withdraw"]:
            await message.answer(
                f"\u26d4 <b>Withdrawal Restricted</b>\n\n{lock_check['reason']} {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(user_id)
            return

        sidi_amount = float(data["sidi_amount"])
        net_ngn = float(data["net_ngn"])
        bank_code = data.get("bank_code", "")
        bank_account = data.get("bank_account", "")
        bank_name = data.get("bank_name", "")
        account_name = data.get("account_name", "")
        fee_sidi = float(data.get("fee_sidi", 0))

        total_deduction = sidi_amount + fee_sidi
        success = update_balance(user_id, -total_deduction)
        if not success:
            await message.answer(
                f"Insufficient balance for cashout. Please try again {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(user_id)
            return

        reference = generate_tx_reference()
        payout_result = process_payout(
            bank_code=bank_code,
            account_number=bank_account,
            amount_ngn=net_ngn,
            reference=reference,
            narration=f"Sidicoin cashout - {account_name}",
        )

        now = int(time.time())
        add_transaction(user_id, {
            "type": "sell", "amount": sidi_amount,
            "ngn_amount": net_ngn, "fee_sidi": fee_sidi,
            "bank_name": bank_name, "bank_account": bank_account,
            "description": f"Cashout to {bank_name} {bank_account}",
            "timestamp": now, "reference": reference,
            "status": "processing",
        })

        unlock_referral_earnings_on_tx(user_id)
        user = get_user(user_id)
        new_balance = float(user.get("sidi_balance", 0))

        receipt = generate_receipt("Cashout", user.get("username", ""), bank_name, sidi_amount, fee_sidi, reference)
        await message.answer(
            f"\u2705 <b>Cashout Processing!</b>\n\n"
            f"{receipt}\n\n"
            f"  \U0001f3e6 {bank_name} - {bank_account}\n"
            f"  \U0001f464 {_safe_escape(account_name)}\n"
            f"  \U0001f48e Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
            f"You'll receive {fmt_naira(net_ngn)} shortly {STAR}",
            reply_markup=home_keyboard(),
        )
        clear_pending_action(user_id)

    except Exception as e:
        logger.error(f"_execute_sell error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}", reply_markup=home_keyboard())
        clear_pending_action(user_id)


async def _execute_send(message: Message, bot: Bot, user_id: int, data: dict):
    """Execute send after OTP verification."""
    try:
        sender = get_user(user_id)
        recipient_id = data["recipient_id"]
        amount = float(data["amount"])
        recipient_username = data.get("recipient_username", "")
        recipient_name = data.get("recipient_name", "")

        reference = generate_tx_reference()
        success = transfer_sidi(user_id, recipient_id, amount)

        if not success:
            await message.answer(
                f"Transfer failed. Insufficient balance or error {STAR}",
                reply_markup=home_button_keyboard(),
            )
            clear_pending_action(user_id)
            return

        increment_rate_count(user_id)
        unlock_referral_earnings_on_tx(user_id)

        now = int(time.time())
        sender_username = sender.get("username", "")
        add_transaction(user_id, {
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

        clear_pending_action(user_id)
        naira = sidi_to_naira(amount)
        receipt = generate_receipt("Transfer", sender_username, recipient_username, amount, 0, reference)

        sender = get_user(user_id)
        new_balance = float(sender.get("sidi_balance", 0))

        text = (
            f"\u2705 <b>Transfer Complete!</b>\n\n"
            f"{receipt}\n\n"
            f"  \U0001f48e Balance: <b>{fmt_number(new_balance)} SIDI</b> {STAR}"
        )
        await message.answer(text, reply_markup=after_send_keyboard())

        # Notify recipient
        await notify_user(
            bot, recipient_id,
            f"\U0001f4b8 <b>You received money!</b>\n\n"
            f"  From:   @{sender_username}\n"
            f"  Amount: <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n\n"
            f"  Your balance has been updated {STAR}",
        )

    except Exception as e:
        logger.error(f"_execute_send error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}", reply_markup=home_keyboard())
        clear_pending_action(user_id)


# =====================================================================
#  GAMES
# =====================================================================

@router.message(Command("game", "games", "play"))
async def cmd_game(message: Message):
    """Show game menu."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer(f"Type /start to create your wallet first {STAR}")
            return

        balance = float(user.get("sidi_balance", 0))
        text = (
            f"\U0001f3ae <b>Sidicoin Games</b>\n\n"
            f"Play to win SIDI! Choose a game:\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001fa99 <b>Coin Flip</b>\n"
            f"     Heads or tails? 2x your bet!\n\n"
            f"  \U0001f3b2 <b>Dice Roll</b>\n"
            f"     Guess the number. 5x payout!\n\n"
            f"  \U0001f3b0 <b>Lucky Number</b>\n"
            f"     Pick 1-10. Match for 8x!\n\n"
            f"{DIVIDER}\n\n"
            f"  Your balance: <b>{fmt_number(balance)} SIDI</b>\n"
            f"  Min bet: 1 SIDI | Max bet: 50 SIDI"
        )
        await message.answer(text, reply_markup=game_menu_keyboard())

    except Exception as e:
        logger.error(f"/game error: {e}", exc_info=True)
        await message.answer(f"Something went wrong. Please try again {STAR}")


@router.callback_query(F.data == "cmd_game")
async def cb_game(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        text = (
            f"\U0001f3ae <b>Sidicoin Games</b>\n\n"
            f"Play to win SIDI! Choose a game:\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001fa99 <b>Coin Flip</b> \u2014 2x payout\n"
            f"  \U0001f3b2 <b>Dice Roll</b> \u2014 5x payout\n"
            f"  \U0001f3b0 <b>Lucky Number</b> \u2014 8x payout\n\n"
            f"{DIVIDER}\n\n"
            f"  Balance: <b>{fmt_number(balance)} SIDI</b>"
        )
        await callback.message.edit_text(text, reply_markup=game_menu_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"cb_game error: {e}")
        await callback.answer("Something went wrong")


# -- Coin Flip --

@router.callback_query(F.data == "game_coinflip")
async def cb_coinflip(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        text = (
            f"\U0001fa99 <b>Coin Flip</b>\n\n"
            f"Win <b>2x</b> your bet!\n"
            f"50% chance to win.\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b>\n\n"
            f"Choose your bet amount:"
        )
        await callback.message.edit_text(text, reply_markup=coinflip_bet_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("flip_bet_"))
async def cb_flip_bet(callback: CallbackQuery):
    try:
        bet_str = callback.data.replace("flip_bet_", "")
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return

        if bet_str == "custom":
            set_pending_action(callback.from_user.id, "game_coinflip_custom_bet")
            await callback.message.edit_text(
                f"\U0001fa99 <b>Coin Flip</b>\n\n"
                f"Enter your bet amount (1-50 SIDI):",
                reply_markup=cancel_keyboard(),
            )
            await callback.answer()
            return

        bet = float(bet_str)
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await callback.answer(f"Not enough SIDI. You have {fmt_number(balance)}", show_alert=True)
            return

        set_pending_action(callback.from_user.id, "game_coinflip_choose", {"bet": bet})
        text = (
            f"\U0001fa99 <b>Coin Flip</b>\n\n"
            f"Bet: <b>{fmt_number(bet)} SIDI</b>\n"
            f"Win: <b>{fmt_number(bet * 2)} SIDI</b>\n\n"
            f"Choose your side:"
        )
        await callback.message.edit_text(text, reply_markup=coinflip_choice_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"flip_bet error: {e}")
        await callback.answer("Something went wrong")


@router.callback_query(F.data.in_({"flip_heads", "flip_tails"}))
async def cb_flip_play(callback: CallbackQuery):
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "game_coinflip_choose" or not data:
            await callback.answer("No active game")
            return

        user = get_user(callback.from_user.id)
        bet = float(data["bet"])
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await callback.answer("Not enough SIDI!", show_alert=True)
            clear_pending_action(callback.from_user.id)
            return

        player_choice = "heads" if callback.data == "flip_heads" else "tails"
        result = random.choice(["heads", "tails"])
        won = player_choice == result

        result_icon = "\U0001f7e1" if result == "heads" else "\U0001f535"
        choice_icon = "\U0001f7e1" if player_choice == "heads" else "\U0001f535"

        if won:
            winnings = bet  # Net gain
            update_balance(callback.from_user.id, winnings)
            increment_stat("game_payouts", winnings)
            user = get_user(callback.from_user.id)
            new_balance = float(user.get("sidi_balance", 0))

            text = (
                f"\U0001fa99 <b>COIN FLIP</b>\n\n"
                f"  You chose: {choice_icon} <b>{player_choice.title()}</b>\n"
                f"  Result:    {result_icon} <b>{result.title()}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \U0001f389 <b>YOU WON!</b>\n\n"
                f"  +<b>{fmt_number(bet * 2)} SIDI</b> ({fmt_naira(sidi_to_naira(bet * 2))})\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}"
            )
        else:
            update_balance(callback.from_user.id, -bet)
            increment_stat("game_revenue", bet)
            user = get_user(callback.from_user.id)
            new_balance = float(user.get("sidi_balance", 0))

            text = (
                f"\U0001fa99 <b>COIN FLIP</b>\n\n"
                f"  You chose: {choice_icon} <b>{player_choice.title()}</b>\n"
                f"  Result:    {result_icon} <b>{result.title()}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \u274c <b>You lost</b>\n\n"
                f"  -{fmt_number(bet)} SIDI\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  Better luck next time {STAR}"
            )

        add_transaction(callback.from_user.id, {
            "type": "game",
            "amount": bet * 2 if won else bet,
            "description": f"Coin Flip {'Won' if won else 'Lost'}: {player_choice}",
            "timestamp": int(time.time()),
            "reference": f"GAME-FLIP-{int(time.time())}",
        })
        clear_pending_action(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=after_game_keyboard())
        await callback.answer("You won!" if won else "Better luck next time!")
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"flip_play error: {e}", exc_info=True)
        await callback.answer("Something went wrong")


# -- Dice Roll --

@router.callback_query(F.data == "game_dice")
async def cb_dice(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        text = (
            f"\U0001f3b2 <b>Dice Roll</b>\n\n"
            f"Guess the number (1-6).\n"
            f"Win <b>5x</b> your bet!\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b>\n\n"
            f"Choose your bet:"
        )
        await callback.message.edit_text(text, reply_markup=dice_bet_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("dice_bet_"))
async def cb_dice_bet(callback: CallbackQuery):
    try:
        bet = float(callback.data.replace("dice_bet_", ""))
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await callback.answer(f"Not enough SIDI. You have {fmt_number(balance)}", show_alert=True)
            return

        set_pending_action(callback.from_user.id, "game_dice_choose", {"bet": bet})
        text = (
            f"\U0001f3b2 <b>Dice Roll</b>\n\n"
            f"Bet: <b>{fmt_number(bet)} SIDI</b>\n"
            f"Win: <b>{fmt_number(bet * 5)} SIDI</b>\n\n"
            f"Pick a number (1-6):"
        )
        await callback.message.edit_text(text, reply_markup=dice_choice_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("dice_pick_"))
async def cb_dice_play(callback: CallbackQuery):
    try:
        action, data = get_pending_action(callback.from_user.id)
        if action != "game_dice_choose" or not data:
            await callback.answer("No active game")
            return

        user = get_user(callback.from_user.id)
        bet = float(data["bet"])
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await callback.answer("Not enough SIDI!", show_alert=True)
            clear_pending_action(callback.from_user.id)
            return

        player_pick = int(callback.data.replace("dice_pick_", ""))
        result = random.randint(1, 6)
        won = player_pick == result

        dice_faces = ["\u2680", "\u2681", "\u2682", "\u2683", "\u2684", "\u2685"]

        if won:
            winnings = bet * 4  # Net gain (they keep bet + win 4x)
            update_balance(callback.from_user.id, winnings)
            increment_stat("game_payouts", winnings)
            user = get_user(callback.from_user.id)
            new_balance = float(user.get("sidi_balance", 0))

            text = (
                f"\U0001f3b2 <b>DICE ROLL</b>\n\n"
                f"  You picked: <b>{player_pick}</b>\n"
                f"  Result:     {dice_faces[result - 1]} <b>{result}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \U0001f389 <b>JACKPOT!</b>\n\n"
                f"  +<b>{fmt_number(bet * 5)} SIDI</b> ({fmt_naira(sidi_to_naira(bet * 5))})\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}"
            )
        else:
            update_balance(callback.from_user.id, -bet)
            increment_stat("game_revenue", bet)
            user = get_user(callback.from_user.id)
            new_balance = float(user.get("sidi_balance", 0))

            text = (
                f"\U0001f3b2 <b>DICE ROLL</b>\n\n"
                f"  You picked: <b>{player_pick}</b>\n"
                f"  Result:     {dice_faces[result - 1]} <b>{result}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \u274c <b>Not this time</b>\n\n"
                f"  -{fmt_number(bet)} SIDI\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  Try again? The dice are waiting {STAR}"
            )

        add_transaction(callback.from_user.id, {
            "type": "game",
            "amount": bet * 5 if won else bet,
            "description": f"Dice Roll {'Won' if won else 'Lost'}: picked {player_pick}, rolled {result}",
            "timestamp": int(time.time()),
            "reference": f"GAME-DICE-{int(time.time())}",
        })
        clear_pending_action(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=after_game_keyboard())
        await callback.answer("JACKPOT!" if won else f"Rolled {result}. Try again!")
    except TelegramBadRequest:
        await callback.answer()
    except Exception as e:
        logger.error(f"dice_play error: {e}", exc_info=True)
        await callback.answer("Something went wrong")


# -- Lucky Number --

@router.callback_query(F.data == "game_lucky")
async def cb_lucky(callback: CallbackQuery):
    try:
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        text = (
            f"\U0001f3b0 <b>Lucky Number</b>\n\n"
            f"A number from 1-10 will be drawn.\n"
            f"Match it to win <b>8x</b> your bet!\n\n"
            f"Balance: <b>{fmt_number(balance)} SIDI</b>\n\n"
            f"Choose your bet:"
        )
        await callback.message.edit_text(text, reply_markup=lucky_number_keyboard())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("lucky_bet_"))
async def cb_lucky_bet(callback: CallbackQuery):
    try:
        bet = float(callback.data.replace("lucky_bet_", ""))
        user = get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please /start first")
            return
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await callback.answer(f"Not enough SIDI. You have {fmt_number(balance)}", show_alert=True)
            return

        set_pending_action(callback.from_user.id, "game_lucky_pick", {"bet": bet})
        await callback.message.edit_text(
            f"\U0001f3b0 <b>Lucky Number</b>\n\n"
            f"Bet: <b>{fmt_number(bet)} SIDI</b>\n"
            f"Win: <b>{fmt_number(bet * 8)} SIDI</b>\n\n"
            f"Type a number from <b>1 to 10</b>:",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()


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
            error_msg = result.get("message", "Unknown error")
            try:
                await loading.edit_text(
                    f"\u274c <b>Account Verification Failed</b>\n\n"
                    f"{error_msg}\n\n"
                    f"Please check:\n"
                    f"\u2022 Your bank name is correct\n"
                    f"\u2022 Your account number is 10 digits\n"
                    f"\u2022 The account is active\n\n"
                    f"Enter your account number again or /cancel {STAR}",
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
            error_msg = result.get("message", "Unknown error")
            try:
                await loading.edit_text(
                    f"\u274c <b>Verification Failed</b>\n\n"
                    f"{error_msg}\n\n"
                    f"Check your bank and account number, "
                    f"then try again {STAR}",
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

    # -- Game flows --
    elif action == "game_coinflip_custom_bet":
        valid, bet_amount = is_valid_amount(text)
        if not valid or bet_amount <= 0 or bet_amount > 50:
            await message.answer(
                "Enter a valid bet (1-50 SIDI):",
                reply_markup=cancel_keyboard(),
            )
            return
        user = get_user(user_id)
        balance = float(user.get("sidi_balance", 0))
        if balance < bet_amount:
            await message.answer(
                f"Not enough SIDI. You have <b>{fmt_number(balance)}</b> {STAR}",
                reply_markup=cancel_keyboard(),
            )
            return
        set_pending_action(user_id, "game_coinflip_choose", {"bet": bet_amount})
        await message.answer(
            f"\U0001fa99 <b>Coin Flip</b>\n\n"
            f"Bet: <b>{fmt_number(bet_amount)} SIDI</b>\n"
            f"Win: <b>{fmt_number(bet_amount * 2)} SIDI</b>\n\n"
            f"Choose your side:",
            reply_markup=coinflip_choice_keyboard(),
        )

    elif action == "game_lucky_pick":
        try:
            pick = int(text.strip())
        except ValueError:
            await message.answer("Please enter a number from 1 to 10:", reply_markup=cancel_keyboard())
            return

        if pick < 1 or pick > 10:
            await message.answer("Number must be between 1 and 10:", reply_markup=cancel_keyboard())
            return

        bet = float(data.get("bet", 0))
        user = get_user(user_id)
        balance = float(user.get("sidi_balance", 0))
        if balance < bet:
            await message.answer(f"Not enough SIDI! Balance: {fmt_number(balance)} {STAR}", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return

        result = random.randint(1, 10)
        won = pick == result

        if won:
            winnings = bet * 7  # Net gain
            update_balance(user_id, winnings)
            increment_stat("game_payouts", winnings)
            user = get_user(user_id)
            new_balance = float(user.get("sidi_balance", 0))
            text_msg = (
                f"\U0001f3b0 <b>LUCKY NUMBER</b>\n\n"
                f"  Your pick:  <b>{pick}</b>\n"
                f"  Lucky num:  <b>{result}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \U0001f389\U0001f389\U0001f389 <b>MEGA WIN!</b>\n\n"
                f"  +<b>{fmt_number(bet * 8)} SIDI</b> ({fmt_naira(sidi_to_naira(bet * 8))})\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}"
            )
        else:
            update_balance(user_id, -bet)
            increment_stat("game_revenue", bet)
            user = get_user(user_id)
            new_balance = float(user.get("sidi_balance", 0))
            text_msg = (
                f"\U0001f3b0 <b>LUCKY NUMBER</b>\n\n"
                f"  Your pick:  <b>{pick}</b>\n"
                f"  Lucky num:  <b>{result}</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  \u274c <b>Not your lucky number</b>\n\n"
                f"  -{fmt_number(bet)} SIDI\n"
                f"  Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  Will you be luckier next time? {STAR}"
            )

        add_transaction(user_id, {
            "type": "game",
            "amount": bet * 8 if won else bet,
            "description": f"Lucky Number {'Won' if won else 'Lost'}: picked {pick}, drew {result}",
            "timestamp": int(time.time()),
            "reference": f"GAME-LUCKY-{int(time.time())}",
        })
        clear_pending_action(user_id)
        await message.answer(text_msg, reply_markup=after_game_keyboard())

    # -- Merchant flows --
    elif action == "merchant_apply_name":
        merchant_name = text.strip()[:50]
        if not merchant_name:
            await message.answer("Enter a valid business name:", reply_markup=cancel_keyboard())
            return

        user = get_user(user_id)
        user["is_merchant"] = True
        user["merchant_approved"] = False
        user["merchant_name"] = merchant_name
        save_user(user_id, user)
        clear_pending_action(user_id)

        await message.answer(
            f"\u2705 <b>Application Submitted!</b>\n\n"
            f"  Business: <b>{_safe_escape(merchant_name)}</b>\n\n"
            f"  We'll review and notify you once approved.\n"
            f"  This usually takes 24-48 hours {STAR}",
            reply_markup=home_keyboard(),
        )

        # Notify admin
        from services.notifications import notify_admin as _admin_notify
        await _admin_notify(
            bot,
            f"\U0001f3e2 New merchant application:\n"
            f"  User: @{user.get('username', user_id)}\n"
            f"  ID: {user_id}\n"
            f"  Business: {merchant_name}\n\n"
            f"Approve: /admin_merchant_approve {user_id}",
        )
        return

    elif action == "merchant_link_amount":
        try:
            link_amount = float(text.strip())
        except ValueError:
            await message.answer("Enter a valid number in SIDI:", reply_markup=cancel_keyboard())
            return
        if link_amount <= 0 or link_amount > 100000:
            await message.answer("Amount must be between 1 and 100,000 SIDI:", reply_markup=cancel_keyboard())
            return

        ref = f"M{int(time.time())}"
        merchant_link = f"https://t.me/SidicoinBot?start=pay_{user_id}_{link_amount}_{ref}"
        naira = sidi_to_naira(link_amount)

        clear_pending_action(user_id)
        await message.answer(
            f"\U0001f517 <b>Payment Link Generated!</b>\n\n"
            f"  Amount: <b>{fmt_number(link_amount)} SIDI</b> ({fmt_naira(naira)})\n"
            f"  Reference: <code>{ref}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  Share this link with your customer:\n\n"
            f"  <code>{merchant_link}</code>\n\n"
            f"{DIVIDER}\n\n"
            f"  When they click, they'll see your business name\n"
            f"  and can confirm the payment. 2% fee applies {STAR}",
            reply_markup=merchant_keyboard(),
        )
        return

    # -- OTP verification flow --
    elif action == "otp_verify":
        code = text.strip()
        if not code.isdigit() or len(code) != 6:
            await message.answer(
                "Enter the 6-digit code sent to you:",
                reply_markup=cancel_keyboard(),
            )
            return

        otp_result = verify_otp(user_id, code)

        if otp_result.get("success"):
            original_action = data.get("original_action", "")
            original_data = data.get("original_data", {})
            clear_pending_action(user_id)

            # Route to the original action
            if original_action == "sell_execute":
                # Re-set pending and simulate the sell flow
                set_pending_action(user_id, "sell_confirm", original_data)
                # Create a fake callback-like flow by processing inline
                from bot.commands import _execute_sell
                await _execute_sell(message, bot, user_id, original_data)

            elif original_action == "send_execute":
                set_pending_action(user_id, "send_confirm", original_data)
                from bot.commands import _execute_send
                await _execute_send(message, bot, user_id, original_data)

            elif original_action == "escrow_fund_execute":
                escrow_id = original_data.get("escrow_id", "")
                result = fund_escrow(escrow_id, str(user_id))
                if result.get("success"):
                    escrow = get_escrow(escrow_id)
                    amount = float(escrow.get("amount_sidi", 0)) if escrow else 0
                    await message.answer(
                        f"\u2705 <b>Escrow Funded!</b>\n\n"
                        f"<b>{fmt_number(amount)} SIDI</b> locked in escrow.\n\n"
                        f"The seller can now deliver. Once you confirm\n"
                        f"delivery, the funds will be released {STAR}",
                        reply_markup=home_button_keyboard(),
                    )
                    if escrow:
                        from services.notifications import notify_user as _notify
                        await _notify(bot, escrow["seller_id"],
                            f"\U0001f4b3 <b>Escrow Funded!</b>\n\n"
                            f"Buyer funded escrow <code>{escrow_id}</code>.\n"
                            f"Amount: <b>{fmt_number(amount)} SIDI</b>\n\n"
                            f"Please deliver now. Type /escrow to manage {STAR}")
                else:
                    await message.answer(
                        f"Could not fund escrow: {result.get('message', 'Error')} {STAR}",
                        reply_markup=home_button_keyboard(),
                    )

            elif original_action == "bank_change_start":
                set_pending_action(user_id, "settings_bank_name")
                await message.answer(
                    f"\u2705 <b>Verified!</b>\n\n"
                    f"What bank do you use?\n\n"
                    f"Type the bank name:\n"
                    f"e.g. GTBank, Access, Kuda, OPay, FirstBank",
                    reply_markup=cancel_keyboard(),
                )

            else:
                await message.answer(f"Verified! {STAR}", reply_markup=home_keyboard())

        else:
            msg = otp_result.get("message", "Wrong code")
            if otp_result.get("locked"):
                # Check if flagged
                failures = get_otp_failure_count(user_id)
                if failures >= 5:
                    from services.notifications import notify_admin as _admin_notify
                    await _admin_notify(bot,
                        f"\u26a0\ufe0f OTP ALERT: User {user_id} has {failures} "
                        f"cumulative OTP failures. Account may be compromised.")
                clear_pending_action(user_id)
                await message.answer(
                    f"\u26d4 <b>Code Expired</b>\n\n{msg}\n\n"
                    f"Please try the action again {STAR}",
                    reply_markup=home_keyboard(),
                )
            else:
                await message.answer(f"\u274c {msg}", reply_markup=cancel_keyboard())
            return

    # -- Escrow flows --
    elif action == "escrow_description":
        if len(text) < 3:
            await message.answer("Please provide a short description (3+ chars):", reply_markup=cancel_keyboard())
            return
        set_pending_action(user_id, "escrow_amount", {**data, "description": text[:200]})
        await message.answer(
            f"{STAR} <b>Escrow Amount</b>\n\n"
            f"How much SIDI to escrow?\n"
            f"This amount will be held until both parties confirm.",
            reply_markup=cancel_keyboard(),
        )

    elif action == "escrow_amount":
        valid, amount = is_valid_amount(text)
        if not valid or amount <= 0:
            await message.answer("Enter a valid amount:", reply_markup=cancel_keyboard())
            return
        set_pending_action(user_id, "escrow_counterparty", {**data, "amount": amount})
        role = data.get("my_role", "seller")
        other_role = "buyer" if role == "seller" else "seller"
        await message.answer(
            f"{STAR} <b>Escrow Counterparty</b>\n\n"
            f"Enter the @username of the {other_role}:",
            reply_markup=cancel_keyboard(),
        )

    elif action == "escrow_counterparty":
        if not is_valid_username(text):
            await message.answer("Enter a valid @username:", reply_markup=cancel_keyboard())
            return
        clean = clean_username(text)
        other_user = find_user_by_username(clean)
        if not other_user:
            await message.answer(f"@{clean} hasn't joined Sidicoin. Invite them first.", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return
        if str(other_user["telegram_id"]) == str(user_id):
            await message.answer("You can't escrow with yourself.", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return

        description = data.get("description", "")
        amount = float(data.get("amount", 0))
        escrow_type = data.get("escrow_type", "p2p_trade")
        my_role = data.get("my_role", "seller")

        if my_role == "seller":
            seller_id = str(user_id)
            buyer_id = other_user["telegram_id"]
        else:
            buyer_id = str(user_id)
            seller_id = other_user["telegram_id"]

        import uuid
        escrow_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
        result = create_escrow(
            escrow_id=escrow_id,
            seller_id=seller_id,
            buyer_id=buyer_id,
            amount_sidi=amount,
            escrow_type=escrow_type,
            description=description,
        )

        clear_pending_action(user_id)

        if result.get("success"):
            from bot.keyboards import escrow_detail_keyboard
            naira = sidi_to_naira(amount)
            seller_user = get_user(seller_id)
            buyer_user = get_user(buyer_id)
            s_name = seller_user.get("username", "") if seller_user else ""
            b_name = buyer_user.get("username", "") if buyer_user else ""

            text_msg = (
                f"\U0001f6e1 <b>Escrow Created!</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  ID:          <code>{escrow_id}</code>\n"
                f"  Amount:      <b>{fmt_number(amount)} SIDI</b> ({fmt_naira(naira)})\n"
                f"  Seller:      @{s_name}\n"
                f"  Buyer:       @{b_name}\n"
                f"  Type:        {escrow_type.replace('_', ' ').title()}\n"
                f"  Description: {_safe_escape(description)}\n"
                f"  Status:      Pending\n\n"
                f"{DIVIDER}\n\n"
                f"  The buyer needs to fund this escrow.\n"
                f"  Once funded, the seller delivers.\n"
                f"  Buyer confirms, funds release {STAR}"
            )
            await message.answer(text_msg, reply_markup=escrow_detail_keyboard(escrow_id, my_role, "pending"))

            # Notify the other party
            from services.notifications import notify_user as _notify
            other_id = buyer_id if my_role == "seller" else seller_id
            other_role = "buyer" if my_role == "seller" else "seller"
            my_user = get_user(user_id)
            my_name = my_user.get("username", "") if my_user else ""
            await _notify(
                bot, other_id,
                f"\U0001f6e1 <b>New Escrow Request</b>\n\n"
                f"@{my_name} created an escrow with you.\n\n"
                f"  Amount: <b>{fmt_number(amount)} SIDI</b>\n"
                f"  Your role: {other_role.title()}\n"
                f"  Description: {_safe_escape(description)}\n"
                f"  ID: <code>{escrow_id}</code>\n\n"
                f"Type /escrow to view and manage {STAR}",
            )
        else:
            await message.answer(f"Could not create escrow: {result.get('message', 'Error')} {STAR}", reply_markup=home_button_keyboard())

    # -- Support/donate flow --
    elif action == "support_amount":
        valid, amount = is_valid_amount(text)
        if not valid or amount <= 0:
            await message.answer("Enter a valid amount:", reply_markup=cancel_keyboard())
            return
        user = get_user(user_id)
        balance = float(user.get("sidi_balance", 0))
        if balance < amount:
            await message.answer(f"Insufficient balance. You have {fmt_number(balance)} SIDI.", reply_markup=home_button_keyboard())
            clear_pending_action(user_id)
            return

        # Deduct and record
        update_balance(user_id, -amount)
        increment_stat("total_donations", amount)
        add_transaction(user_id, {
            "type": "donation",
            "amount": amount,
            "description": "Support donation to Sidicoin",
            "timestamp": int(time.time()),
            "reference": generate_tx_reference(),
        })
        clear_pending_action(user_id)

        user = get_user(user_id)
        new_balance = float(user.get("sidi_balance", 0))
        donor_name = user.get("full_name", user.get("username", "Anonymous"))
        naira_val = sidi_to_naira(amount)

        await message.answer(
            f"{STAR} <b>Thank You, {_safe_escape(donor_name)}!</b>\n\n"
            f"Your generous donation of <b>{fmt_number(amount)} SIDI</b> "
            f"({fmt_naira(naira_val)}) helps keep Sidicoin\n"
            f"running with zero fees for everyone.\n\n"
            f"{DIVIDER}\n\n"
            f"  Because of supporters like you:\n\n"
            f"  \u2022 All transfers stay free\n"
            f"  \u2022 Escrow trades cost nothing\n"
            f"  \u2022 Buy/sell with zero fees\n"
            f"  \u2022 Cross-border payments stay free\n\n"
            f"{DIVIDER}\n\n"
            f"  \U0001f48e Balance: <b>{fmt_number(new_balance)} SIDI</b>\n\n"
            f"You are part of what makes Sidicoin possible.\n"
            f"We truly appreciate your support {STAR}",
            reply_markup=home_keyboard(),
        )

        # Notify admin about the donation
        from services.notifications import notify_admin as _admin_notify
        await _admin_notify(
            bot,
            f"\U0001f4b0 <b>DONATION RECEIVED</b>\n\n"
            f"From: {_safe_escape(donor_name)} ({user_id})\n"
            f"Amount: {fmt_number(amount)} SIDI ({fmt_naira(naira_val)})\n"
            f"Total donated: {fmt_number(get_stat('total_donations'))} SIDI",
        )

    # -- Escrow dispute reason --
    elif action == "escrow_dispute_reason":
        escrow_id = data.get("escrow_id", "")
        if len(text) < 5:
            await message.answer("Please describe the issue (5+ characters):", reply_markup=cancel_keyboard())
            return
        result = raise_dispute(escrow_id, str(user_id), text)
        clear_pending_action(user_id)

        if result.get("success"):
            from services.notifications import notify_admin as _admin_notify
            escrow = get_escrow(escrow_id)
            await message.answer(
                f"\u26a0\ufe0f <b>Dispute Filed</b>\n\n"
                f"Escrow <code>{escrow_id}</code> is now under review.\n"
                f"Our team will investigate and resolve this.\n\n"
                f"Reason: {_safe_escape(text[:200])}\n\n"
                f"Funds are held safely until resolved {STAR}",
                reply_markup=home_button_keyboard(),
            )
            if escrow:
                await _admin_notify(
                    bot,
                    f"\u26a0\ufe0f <b>ESCROW DISPUTE</b>\n\n"
                    f"ID: {escrow_id}\n"
                    f"By: {user_id}\n"
                    f"Amount: {escrow.get('amount_sidi')} SIDI\n"
                    f"Reason: {text[:300]}",
                )
        else:
            await message.answer(f"Could not file dispute: {result.get('message', 'Error')}", reply_markup=home_button_keyboard())

    else:
        clear_pending_action(user_id)
        loading = await message.answer(f"{STAR} Sidi is thinking...")
        ai_response = await get_ai_response(text, message.from_user.first_name or "User")
        try:
            await loading.edit_text(ai_response, reply_markup=home_button_keyboard())
        except TelegramBadRequest:
            pass
