"""
Group & channel commands for Sidicoin bot.
Handles all group-specific features: tipping, giveaways, rain,
verification, user lookup, random picks, and group AI mentions.
"""

import os
import re
import random
import time
import logging
import asyncio
import html

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest

from services.redis import (
    get_user, save_user, find_user_by_username,
    update_balance, add_transaction,
    track_group_member_activity, get_active_group_members,
    create_giveaway, get_giveaway, update_giveaway,
    join_giveaway, get_giveaway_participants, end_giveaway,
    set_verification_status, get_verification_status,
    get_all_user_ids, increment_stat,
)
from utils.formatting import (
    fmt_number, fmt_naira, sidi_to_naira,
    generate_tx_reference,
    DIVIDER, THIN_DIVIDER, STAR,
)
from utils.validation import clean_username, is_valid_amount, sanitize_input
from bot.keyboards import (
    giveaway_join_keyboard, giveaway_end_keyboard,
    verify_start_keyboard, whois_tip_keyboard,
)

logger = logging.getLogger("sidicoin.group")

group_router = Router()

# Only handle group and supergroup messages
GROUP_FILTER = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})

BOT_USERNAME = os.getenv("BOT_USERNAME", "SidicoinBot").lower()

# Verification questions bank
VERIFY_QUESTIONS = [
    {"q": "What is 7 + 15?", "a": "22"},
    {"q": "What is 12 x 3?", "a": "36"},
    {"q": "What is 100 - 37?", "a": "63"},
    {"q": "What is 9 x 9?", "a": "81"},
    {"q": "What is 56 / 8?", "a": "7"},
    {"q": "What is the currency of Sidicoin?", "a": "sidi"},
    {"q": "What command sends money in Sidicoin?", "a": "/send"},
    {"q": "Are Sidicoin transfers free? (yes/no)", "a": "yes"},
    {"q": "What command checks your balance?", "a": "/balance"},
    {"q": "What is 2 + 2?", "a": "4"},
]


def _esc(text) -> str:
    """Escape HTML entities."""
    return html.escape(str(text)) if text else ""


def _mention(user_id: str, name: str) -> str:
    """Create a tg user mention link."""
    return f'<a href="tg://user?id={user_id}">{_esc(name)}</a>'


# =====================================================================
#  ACTIVITY TRACKING (runs on every group message)
# =====================================================================

@group_router.message(GROUP_FILTER)
async def track_activity(message: Message):
    """Track member activity in groups for /rain and other features.
    This handler is registered last so it doesn't block other handlers.
    """
    if message.from_user:
        group_id = str(message.chat.id)
        user_id = str(message.from_user.id)
        track_group_member_activity(group_id, user_id)


# =====================================================================
#  /tip @user amount -- Group tipping
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/tip(@\w+)?\s"))
async def cmd_tip(message: Message, bot: Bot):
    """Tip a user SIDI directly in a group chat."""
    text = message.text or ""
    parts = text.split()

    # Parse: /tip @username amount  OR  /tip amount (reply)
    target_username = None
    amount_str = None

    if message.reply_to_message and message.reply_to_message.from_user:
        # /tip 50 (replying to someone)
        if len(parts) >= 2:
            amount_str = parts[1]
            target_user_obj = message.reply_to_message.from_user
            target_username = target_user_obj.username
            target_id = str(target_user_obj.id)
            target_name = target_user_obj.first_name or "User"
    elif len(parts) >= 3:
        # /tip @username 50
        raw_username = parts[1]
        amount_str = parts[2]
        target_username = clean_username(raw_username)
    else:
        await message.reply(
            f"<b>Usage:</b>\n\n"
            f"  <code>/tip @username 50</code>\n"
            f"  Or reply to a message with <code>/tip 50</code>"
        )
        return

    # Validate amount
    if not amount_str or not is_valid_amount(amount_str):
        await message.reply("Please enter a valid amount.")
        return

    amount = float(amount_str)
    if amount < 1:
        await message.reply("Minimum tip is 1 SIDI.")
        return
    if amount > 10000:
        await message.reply("Maximum tip in groups is 10,000 SIDI.")
        return

    sender_id = str(message.from_user.id)
    sender_name = message.from_user.first_name or "User"
    sender_username = message.from_user.username or sender_name

    # Get sender
    sender = get_user(sender_id)
    if not sender:
        await message.reply(
            f"You need a Sidicoin wallet first.\n"
            f"Start here: https://t.me/{BOT_USERNAME}?start=new"
        )
        return

    sender_balance = float(sender.get("sidi_balance", 0))
    if sender_balance < amount:
        await message.reply(
            f"Insufficient balance. You have <b>{fmt_number(sender_balance)} SIDI</b>."
        )
        return

    # Get target
    if target_username and not target_username.startswith("@"):
        pass

    if target_username:
        target = find_user_by_username(target_username)
        if not target:
            await message.reply(
                f"@{_esc(target_username)} doesn't have a Sidicoin wallet yet.\n"
                f"They can create one: https://t.me/{BOT_USERNAME}?start=new"
            )
            return
        target_id = str(target.get("telegram_id", ""))
        target_name = target.get("full_name", target_username)
    else:
        target = get_user(target_id)
        if not target:
            await message.reply(
                f"{_mention(target_id, target_name)} doesn't have a Sidicoin wallet yet."
            )
            return

    if target_id == sender_id:
        await message.reply("You can't tip yourself.")
        return

    # Execute transfer
    reference = generate_tx_reference()
    update_balance(sender_id, -amount)
    update_balance(target_id, amount)

    # Record transactions
    now = int(time.time())
    add_transaction(sender_id, {
        "type": "tip_sent", "amount": amount,
        "description": f"Tipped @{target.get('username', target_name)} in group",
        "timestamp": now, "reference": reference,
    })
    add_transaction(target_id, {
        "type": "tip_received", "amount": amount,
        "description": f"Tip from @{sender_username} in group",
        "timestamp": now, "reference": reference,
    })

    increment_stat("daily_tx_count", 1)
    increment_stat("daily_volume_ngn", sidi_to_naira(amount))

    sender = get_user(sender_id)
    naira = sidi_to_naira(amount)

    await message.reply(
        f"{STAR} <b>Tip Sent!</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  {_mention(sender_id, sender_name)}  tipped\n"
        f"  {_mention(target_id, target_name)}\n\n"
        f"  <b>{fmt_number(amount)} SIDI</b>  ({fmt_naira(naira)})\n\n"
        f"{DIVIDER}"
    )

    # Notify in DM
    try:
        target_balance = float(get_user(target_id).get("sidi_balance", 0))
        await bot.send_message(
            int(target_id),
            f"\U0001f4b0 <b>You received a tip!</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  From       @{_esc(sender_username)}\n"
            f"  Amount     <b>{fmt_number(amount)} SIDI</b>\n"
            f"  Balance    <b>{fmt_number(target_balance)} SIDI</b>\n\n"
            f"{DIVIDER}",
        )
    except Exception:
        pass


# =====================================================================
#  /giveaway amount winners -- Create a SIDI giveaway
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/giveaway(@\w+)?\s"))
async def cmd_giveaway(message: Message, bot: Bot):
    """Create a SIDI giveaway in a group."""
    parts = (message.text or "").split()

    if len(parts) < 3:
        await message.reply(
            f"<b>Usage:</b>  <code>/giveaway 500 5</code>\n"
            f"(500 SIDI split among 5 winners)"
        )
        return

    amount_str = parts[1]
    winners_str = parts[2]

    if not is_valid_amount(amount_str):
        await message.reply("Invalid amount.")
        return

    amount = float(amount_str)
    try:
        num_winners = int(winners_str)
    except ValueError:
        await message.reply("Invalid number of winners.")
        return

    if amount < 10:
        await message.reply("Minimum giveaway is 10 SIDI.")
        return
    if amount > 100000:
        await message.reply("Maximum giveaway is 100,000 SIDI.")
        return
    if num_winners < 1 or num_winners > 100:
        await message.reply("Winners must be between 1 and 100.")
        return

    creator_id = str(message.from_user.id)
    creator_name = message.from_user.first_name or "User"
    creator = get_user(creator_id)

    if not creator:
        await message.reply(
            f"You need a wallet first: https://t.me/{BOT_USERNAME}?start=new"
        )
        return

    balance = float(creator.get("sidi_balance", 0))
    if balance < amount:
        await message.reply(
            f"Insufficient balance. You have <b>{fmt_number(balance)} SIDI</b>."
        )
        return

    # Deduct and create giveaway
    update_balance(creator_id, -amount)
    giveaway_id = f"GA-{generate_tx_reference()}"
    per_winner = round(amount / num_winners, 2)
    now = int(time.time())

    data = {
        "giveaway_id": giveaway_id,
        "creator_id": creator_id,
        "creator_name": creator_name,
        "group_id": str(message.chat.id),
        "total_amount": amount,
        "num_winners": num_winners,
        "per_winner": per_winner,
        "status": "active",
        "created_at": now,
        "message_id": None,
    }
    create_giveaway(giveaway_id, data)

    add_transaction(creator_id, {
        "type": "giveaway_created", "amount": amount,
        "description": f"Giveaway in {message.chat.title or 'group'}",
        "timestamp": now, "reference": giveaway_id,
    })

    sent = await message.answer(
        f"\U0001f389 <b>GIVEAWAY</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  Hosted by  {_mention(creator_id, creator_name)}\n\n"
        f"  Prize      <b>{fmt_number(amount)} SIDI</b>\n"
        f"  Winners    {num_winners}\n"
        f"  Each gets  <b>{fmt_number(per_winner)} SIDI</b>\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"  Participants: 0\n\n"
        f"{DIVIDER}\n\n"
        f"  Tap below to join! {STAR}",
        reply_markup=giveaway_join_keyboard(giveaway_id),
    )

    # Store the message ID so we can edit it later
    data["message_id"] = sent.message_id
    update_giveaway(giveaway_id, data)


# =====================================================================
#  Giveaway join callback
# =====================================================================

@group_router.callback_query(F.data.startswith("giveaway_join_"))
async def cb_giveaway_join(callback: CallbackQuery, bot: Bot):
    """Handle a user joining a giveaway."""
    giveaway_id = callback.data.replace("giveaway_join_", "")
    user_id = str(callback.from_user.id)
    user_name = callback.from_user.first_name or "User"

    giveaway = get_giveaway(giveaway_id)
    if not giveaway or giveaway.get("status") != "active":
        await callback.answer("This giveaway has ended.", show_alert=True)
        return

    # Must have a wallet
    user = get_user(user_id)
    if not user:
        await callback.answer(
            f"You need a Sidicoin wallet first! Start at @{BOT_USERNAME}",
            show_alert=True,
        )
        return

    if user_id == giveaway.get("creator_id"):
        await callback.answer("You can't join your own giveaway.", show_alert=True)
        return

    added = join_giveaway(giveaway_id, user_id)
    participants = get_giveaway_participants(giveaway_id)
    count = len(participants)

    if added:
        await callback.answer(f"You joined! {count} participants so far.")
    else:
        await callback.answer(f"You already joined! {count} participants.", show_alert=True)
        return

    # Update the giveaway message with new count
    per_winner = giveaway.get("per_winner", 0)
    creator_name = giveaway.get("creator_name", "Someone")
    creator_id = giveaway.get("creator_id", "")
    amount = giveaway.get("total_amount", 0)
    num_winners = giveaway.get("num_winners", 1)

    try:
        # Build participant names (show up to 10)
        participant_lines = ""
        shown = min(count, 10)
        for pid in participants[:shown]:
            p = get_user(pid)
            p_name = p.get("full_name", "User") if p else "User"
            participant_lines += f"  {_mention(pid, p_name)}\n"
        if count > 10:
            participant_lines += f"  ... and {count - 10} more\n"

        await callback.message.edit_text(
            f"\U0001f389 <b>GIVEAWAY</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  Hosted by  {_mention(creator_id, creator_name)}\n\n"
            f"  Prize      <b>{fmt_number(amount)} SIDI</b>\n"
            f"  Winners    {num_winners}\n"
            f"  Each gets  <b>{fmt_number(per_winner)} SIDI</b>\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  Participants: {count}\n\n"
            f"{participant_lines}\n"
            f"{DIVIDER}\n\n"
            f"  Tap below to join! {STAR}",
            reply_markup=giveaway_join_keyboard(giveaway_id),
        )
    except TelegramBadRequest:
        pass

    # Auto-end check: if enough participants (2x winners), creator gets an end button via DM
    if count >= num_winners and count >= 3:
        try:
            await bot.send_message(
                int(creator_id),
                f"Your giveaway <code>{giveaway_id}</code> has "
                f"<b>{count}</b> participants.\n"
                f"Tap below to end it and pick winners!",
                reply_markup=giveaway_end_keyboard(giveaway_id),
            )
        except Exception:
            pass


# =====================================================================
#  Giveaway end callback
# =====================================================================

@group_router.callback_query(F.data.startswith("giveaway_end_"))
async def cb_giveaway_end(callback: CallbackQuery, bot: Bot):
    """End a giveaway and pick random winners."""
    giveaway_id = callback.data.replace("giveaway_end_", "")
    user_id = str(callback.from_user.id)

    giveaway = get_giveaway(giveaway_id)
    if not giveaway:
        await callback.answer("Giveaway not found.", show_alert=True)
        return
    if giveaway.get("status") != "active":
        await callback.answer("This giveaway already ended.", show_alert=True)
        return
    if user_id != giveaway.get("creator_id"):
        await callback.answer("Only the creator can end this giveaway.", show_alert=True)
        return

    participants = get_giveaway_participants(giveaway_id)
    num_winners = giveaway.get("num_winners", 1)
    total_amount = giveaway.get("total_amount", 0)
    per_winner = giveaway.get("per_winner", 0)
    creator_id = giveaway.get("creator_id", "")
    creator_name = giveaway.get("creator_name", "")
    group_id = giveaway.get("group_id", "")

    if len(participants) == 0:
        # No participants -- refund creator
        update_balance(creator_id, total_amount)
        end_giveaway(giveaway_id)
        await callback.answer("No participants. Refunded.", show_alert=True)
        now = int(time.time())
        add_transaction(creator_id, {
            "type": "giveaway_refund", "amount": total_amount,
            "description": f"Giveaway refunded (no participants)",
            "timestamp": now, "reference": giveaway_id,
        })
        return

    # Pick winners
    actual_winners = min(num_winners, len(participants))
    actual_per_winner = round(total_amount / actual_winners, 2)
    winners = random.sample(participants, actual_winners)
    now = int(time.time())

    winner_lines = ""
    for w_id in winners:
        update_balance(w_id, actual_per_winner)
        w_user = get_user(w_id)
        w_name = w_user.get("full_name", "User") if w_user else "User"
        winner_lines += f"  {_mention(w_id, w_name)}  +<b>{fmt_number(actual_per_winner)} SIDI</b>\n"

        add_transaction(w_id, {
            "type": "giveaway_won", "amount": actual_per_winner,
            "description": f"Won giveaway by @{creator_name}",
            "timestamp": now, "reference": giveaway_id,
        })

        # Notify winner in DM
        try:
            await bot.send_message(
                int(w_id),
                f"\U0001f389 <b>You won a giveaway!</b>\n\n"
                f"{DIVIDER}\n\n"
                f"  Prize    +<b>{fmt_number(actual_per_winner)} SIDI</b>\n"
                f"  From     {_esc(creator_name)}\n\n"
                f"{DIVIDER}",
            )
        except Exception:
            pass

    # Refund remainder if fewer winners than planned
    leftover = round(total_amount - (actual_per_winner * actual_winners), 2)
    if leftover > 0.01:
        update_balance(creator_id, leftover)

    end_giveaway(giveaway_id)

    # Announce in group
    results_text = (
        f"\U0001f3c6 <b>GIVEAWAY RESULTS</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  Hosted by  {_mention(creator_id, creator_name)}\n"
        f"  Prize      <b>{fmt_number(total_amount)} SIDI</b>\n"
        f"  Entries    {len(participants)}\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"  <b>Winners:</b>\n\n"
        f"{winner_lines}\n"
        f"{DIVIDER}"
    )

    # Try to edit original message
    msg_id = giveaway.get("message_id")
    if msg_id and group_id:
        try:
            await bot.edit_message_text(
                results_text,
                chat_id=int(group_id),
                message_id=int(msg_id),
            )
            await callback.answer("Winners picked!")
            return
        except Exception:
            pass

    await callback.message.edit_text(results_text)
    await callback.answer("Winners picked!")


# =====================================================================
#  /rain amount -- Distribute SIDI to active group members
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/rain(@\w+)?\s"))
async def cmd_rain(message: Message, bot: Bot):
    """Rain SIDI on active group members."""
    parts = (message.text or "").split()

    if len(parts) < 2:
        await message.reply("<b>Usage:</b>  <code>/rain 100</code>")
        return

    amount_str = parts[1]
    if not is_valid_amount(amount_str):
        await message.reply("Invalid amount.")
        return

    amount = float(amount_str)
    if amount < 5:
        await message.reply("Minimum rain is 5 SIDI.")
        return

    sender_id = str(message.from_user.id)
    sender_name = message.from_user.first_name or "User"
    sender = get_user(sender_id)

    if not sender:
        await message.reply(
            f"You need a wallet first: https://t.me/{BOT_USERNAME}?start=new"
        )
        return

    balance = float(sender.get("sidi_balance", 0))
    if balance < amount:
        await message.reply(
            f"Insufficient balance. You have <b>{fmt_number(balance)} SIDI</b>."
        )
        return

    # Get active members (last 30 minutes)
    group_id = str(message.chat.id)
    active_members = get_active_group_members(group_id, minutes=30)

    # Filter out sender and those without wallets
    eligible = []
    for member_id in active_members:
        if member_id == sender_id:
            continue
        u = get_user(member_id)
        if u and not u.get("is_banned"):
            eligible.append(member_id)

    if len(eligible) == 0:
        await message.reply(
            "No active Sidicoin members found in this group.\n"
            "Members need to have a wallet and be active recently."
        )
        return

    # Cap at 50 recipients
    eligible = eligible[:50]
    per_person = round(amount / len(eligible), 2)
    actual_total = round(per_person * len(eligible), 2)

    update_balance(sender_id, -actual_total)
    now = int(time.time())
    reference = generate_tx_reference()

    add_transaction(sender_id, {
        "type": "rain_sent", "amount": actual_total,
        "description": f"Rained on {len(eligible)} members",
        "timestamp": now, "reference": reference,
    })

    recipient_lines = ""
    count = 0
    for member_id in eligible:
        update_balance(member_id, per_person)
        count += 1
        m_user = get_user(member_id)
        m_name = m_user.get("full_name", "User") if m_user else "User"

        add_transaction(member_id, {
            "type": "rain_received", "amount": per_person,
            "description": f"Rain from @{sender.get('username', sender_name)}",
            "timestamp": now, "reference": reference,
        })

        if count <= 8:
            recipient_lines += f"  {_mention(member_id, m_name)}\n"

    if count > 8:
        recipient_lines += f"  ... and {count - 8} more\n"

    increment_stat("daily_tx_count", count)
    increment_stat("daily_volume_ngn", sidi_to_naira(actual_total))

    await message.reply(
        f"\U0001f327\ufe0f <b>SIDI RAIN</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  {_mention(sender_id, sender_name)} made it rain!\n\n"
        f"  Total      <b>{fmt_number(actual_total)} SIDI</b>\n"
        f"  Each got   <b>{fmt_number(per_person)} SIDI</b>\n"
        f"  Members    {count}\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"{recipient_lines}\n"
        f"{DIVIDER}"
    )


# =====================================================================
#  /pick -- Random winner picker
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/pick(@\w+)?$"))
async def cmd_pick(message: Message):
    """Pick a random active group member."""
    group_id = str(message.chat.id)
    active = get_active_group_members(group_id, minutes=60)

    if len(active) < 2:
        await message.reply("Not enough active members to pick from.")
        return

    winner_id = random.choice(active)
    winner = get_user(winner_id)
    winner_name = winner.get("full_name", "User") if winner else "User"

    phrases = [
        "The chosen one is",
        "Fortune favors",
        "The stars have aligned for",
        "Destiny has chosen",
        "And the winner is",
    ]

    await message.reply(
        f"\U0001f3af <b>Random Pick</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  {random.choice(phrases)}...\n\n"
        f"  {_mention(winner_id, winner_name)}!\n\n"
        f"{DIVIDER}"
    )


# =====================================================================
#  /verify -- Anti-scam verification
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/verify(@\w+)?$"))
async def cmd_verify(message: Message, bot: Bot):
    """Start the verification quiz for a user."""
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name or "User"

    status = get_verification_status(user_id)
    if status.get("verified"):
        await message.reply(
            f"{_mention(user_id, user_name)} is already verified \u2705"
        )
        return

    user = get_user(user_id)
    if not user:
        await message.reply(
            f"Create a wallet first: https://t.me/{BOT_USERNAME}?start=new"
        )
        return

    # Start verification in DM
    try:
        questions = random.sample(VERIFY_QUESTIONS, 3)
        await bot.send_message(
            int(user_id),
            f"\U0001f50d <b>Verification Quiz</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  Answer 3 quick questions to get\n"
            f"  a verified badge on your profile.\n\n"
            f"  You have 60 seconds per question.\n"
            f"  Need 2/3 correct to pass.\n\n"
            f"{DIVIDER}\n\n"
            f"  <b>Question 1:</b>  {questions[0]['q']}",
        )
        # Store verification state
        user["_verify_questions"] = questions
        user["_verify_step"] = 0
        user["_verify_correct"] = 0
        user["_verify_started"] = int(time.time())
        save_user(user_id, user)

        await message.reply(
            f"Verification quiz sent to {_mention(user_id, user_name)} in DM.\n"
            f"Check your private messages!"
        )

    except Exception:
        await message.reply(
            f"{_mention(user_id, user_name)}, I couldn't DM you.\n"
            f"Please start the bot first: https://t.me/{BOT_USERNAME}?start=new"
        )


# =====================================================================
#  /whois @user -- Check user legitimacy
# =====================================================================

@group_router.message(GROUP_FILTER, F.text.regexp(r"^/whois(@\w+)?\s"))
async def cmd_whois(message: Message):
    """Check if a user is legitimate and their Sidicoin status."""
    parts = (message.text or "").split()

    # Parse target
    target_username = None
    target_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_obj = message.reply_to_message.from_user
        target_id = str(target_user_obj.id)
        target_username = target_user_obj.username
        target_name = target_user_obj.first_name or "User"
    elif len(parts) >= 2:
        target_username = clean_username(parts[1])
    else:
        await message.reply(
            "<b>Usage:</b>  <code>/whois @username</code>\n"
            "Or reply to a message with <code>/whois</code>"
        )
        return

    # Look up user
    user = None
    if target_username:
        user = find_user_by_username(target_username)
    elif target_id:
        user = get_user(target_id)

    if not user:
        has_wallet = "\u274c"
        verified = "\u274c"
        display_name = _esc(target_username or target_name or "Unknown")

        await message.reply(
            f"\U0001f50d <b>User Lookup</b>\n\n"
            f"{DIVIDER}\n\n"
            f"  User       @{display_name}\n"
            f"  Wallet     {has_wallet} No wallet\n"
            f"  Verified   {verified} Unverified\n\n"
            f"{THIN_DIVIDER}\n\n"
            f"  This user has no Sidicoin account.\n"
            f"  Exercise caution in transactions.\n\n"
            f"{DIVIDER}"
        )
        return

    uid = str(user.get("telegram_id", ""))
    name = _esc(user.get("full_name", target_username or "User"))
    uname = _esc(user.get("username", ""))
    created = user.get("created_at", 0)
    is_verified = user.get("verified", False)
    is_premium = user.get("is_premium", False)
    is_merchant = user.get("is_merchant", False)
    total_sent = float(user.get("total_sent_sidi", 0))
    total_received = float(user.get("total_received_sidi", 0))
    escrow_count = int(user.get("escrow_completed", 0))
    games_played = int(user.get("games_played", 0))

    # Calculate account age
    now = int(time.time())
    if created:
        days_old = max((now - int(created)) // 86400, 0)
        age_str = f"{days_old} days" if days_old < 365 else f"{days_old // 365}y {days_old % 365}d"
    else:
        age_str = "Unknown"

    # Trust signals
    trust_score = 0
    trust_indicators = []

    if is_verified:
        trust_score += 30
        trust_indicators.append("\u2705 Verified")
    else:
        trust_indicators.append("\u26a0\ufe0f Unverified")

    if days_old > 30:
        trust_score += 20
        trust_indicators.append(f"\u2705 Account age: {age_str}")
    elif days_old > 7:
        trust_score += 10
        trust_indicators.append(f"\u26a0\ufe0f New account: {age_str}")
    else:
        trust_indicators.append(f"\u274c Very new: {age_str}")

    if total_sent > 0 or total_received > 0:
        trust_score += 20
        trust_indicators.append(f"\u2705 Active trader")
    else:
        trust_indicators.append(f"\u26a0\ufe0f No trade history")

    if escrow_count > 0:
        trust_score += 15
        trust_indicators.append(f"\u2705 {escrow_count} escrow(s) completed")

    if is_merchant:
        trust_score += 15
        trust_indicators.append("\u2705 Verified merchant")

    # Trust level label
    if trust_score >= 70:
        trust_label = "HIGH"
    elif trust_score >= 40:
        trust_label = "MEDIUM"
    else:
        trust_label = "LOW"

    indicators_text = "\n".join(f"  {i}" for i in trust_indicators)

    badges = ""
    if is_verified:
        badges += " \u2705"
    if is_premium:
        badges += " \u2b50"
    if is_merchant:
        badges += " \U0001f3e2"

    keyboard = whois_tip_keyboard(uname) if uname else None

    await message.reply(
        f"\U0001f50d <b>User Lookup</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  {name}{badges}\n"
        f"  @{uname}\n\n"
        f"  Trust       <b>{trust_label}</b> ({trust_score}/100)\n"
        f"  Account     {age_str}\n"
        f"  Trades      {fmt_number(total_sent + total_received)} SIDI\n"
        f"  Games       {games_played}\n\n"
        f"{THIN_DIVIDER}\n\n"
        f"{indicators_text}\n\n"
        f"{DIVIDER}",
        reply_markup=keyboard,
    )


# =====================================================================
#  Group AI -- Respond when @mentioned
# =====================================================================

@group_router.message(
    GROUP_FILTER,
    F.text.func(
        lambda t: t and (
            f"@{BOT_USERNAME}" in t.lower()
            or t.lower().startswith("sidi ")
            or t.lower().startswith("sidi,")
        )
    ),
)
async def group_ai_mention(message: Message, bot: Bot):
    """Respond when mentioned in a group with AI streaming."""
    from services.groq import stream_ai_response, get_ai_response

    user_name = message.from_user.first_name or "User"
    text = (message.text or "").strip()

    # Remove the @mention from the text
    clean_text = re.sub(rf"@{BOT_USERNAME}", "", text, flags=re.IGNORECASE).strip()
    clean_text = re.sub(r"^sidi[,\s]+", "", clean_text, flags=re.IGNORECASE).strip()

    if not clean_text:
        await message.reply(
            f"Hey {_esc(user_name)}! Ask me anything about Sidicoin.\n\n"
            f"  <code>@{BOT_USERNAME} how do I send money?</code>"
        )
        return

    loading = await message.reply(f"{STAR} Thinking...")
    await stream_ai_response(
        loading,
        clean_text,
        user_name=user_name,
        suffix="",
        reply_markup=None,
        group_mode=True,
    )


# =====================================================================
#  Reply-based AI (respond to replies to bot messages in groups)
# =====================================================================

@group_router.message(GROUP_FILTER, F.reply_to_message)
async def group_ai_reply(message: Message, bot: Bot):
    """Respond when someone replies to a bot message in a group."""
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    if not message.reply_to_message.from_user.is_bot:
        return

    bot_info = await bot.get_me()
    if message.reply_to_message.from_user.id != bot_info.id:
        return

    from services.groq import stream_ai_response

    user_name = message.from_user.first_name or "User"
    text = sanitize_input(message.text or "")
    if not text:
        return

    loading = await message.reply(f"{STAR} Thinking...")
    await stream_ai_response(
        loading,
        text,
        user_name=user_name,
        suffix="",
        reply_markup=None,
        group_mode=True,
    )
