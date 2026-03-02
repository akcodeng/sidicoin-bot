"""
Inline keyboard builders for Sidicoin bot.
Every message must end with relevant action buttons.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ── Home / Main menu ───────────────────────────────────────────

def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Send", callback_data="cmd_send"),
            InlineKeyboardButton(text="💳 Buy", callback_data="cmd_buy"),
        ],
        [
            InlineKeyboardButton(text="💰 Sell", callback_data="cmd_sell"),
            InlineKeyboardButton(text="🎁 Refer", callback_data="cmd_refer"),
        ],
        [
            InlineKeyboardButton(text="📊 Balance", callback_data="cmd_balance"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="cmd_settings"),
        ],
    ])


# ── Welcome keyboard ──────────────────────────────────────────

def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 My Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="📤 Send Money", callback_data="cmd_send"),
        ],
        [
            InlineKeyboardButton(text="💳 Buy SIDI", callback_data="cmd_buy"),
            InlineKeyboardButton(text="❓ Help", callback_data="cmd_help"),
        ],
    ])


# ── Onboarding keyboards ──────────────────────────────────────

def onboarding_step1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Get Started →", callback_data="onboard_2")],
    ])


def onboarding_step2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Got it →", callback_data="onboard_3")],
    ])


def onboarding_step3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Buy SIDI", callback_data="cmd_buy"),
            InlineKeyboardButton(text="🎁 Refer Friends", callback_data="cmd_refer"),
        ],
    ])


# ── Balance keyboard ──────────────────────────────────────────

def balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Send", callback_data="cmd_send"),
            InlineKeyboardButton(text="💳 Buy", callback_data="cmd_buy"),
        ],
        [
            InlineKeyboardButton(text="💰 Sell", callback_data="cmd_sell"),
            InlineKeyboardButton(text="📋 History", callback_data="cmd_history"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Send confirmation ─────────────────────────────────────────

def send_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data="send_confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="send_cancel"),
        ],
    ])


def send_large_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Yes, Confirm Large Transfer", callback_data="send_confirm"),
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data="send_cancel"),
        ],
    ])


# ── Post-send keyboards ───────────────────────────────────────

def after_send_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Send More", callback_data="cmd_send"),
            InlineKeyboardButton(text="💎 Wallet", callback_data="cmd_balance"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


def received_money_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Cash Out", callback_data="cmd_sell"),
            InlineKeyboardButton(text="📤 Send Back", callback_data="cmd_send"),
        ],
        [InlineKeyboardButton(text="💎 Wallet", callback_data="cmd_balance")],
    ])


# ── Buy flow ──────────────────────────────────────────────────

def buy_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Proceed to Pay", callback_data="buy_proceed")],
        [InlineKeyboardButton(text="Cancel", callback_data="buy_cancel")],
    ])


def buy_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="I Have Paid", callback_data="buy_paid")],
        [InlineKeyboardButton(text="Cancel", callback_data="buy_cancel")],
    ])


def after_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Send SIDI", callback_data="cmd_send"),
            InlineKeyboardButton(text="💎 View Wallet", callback_data="cmd_balance"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Sell flow ─────────────────────────────────────────────────

def sell_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Cashout", callback_data="sell_confirm")],
        [InlineKeyboardButton(text="🏦 Change Bank", callback_data="sell_change_bank")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="sell_cancel")],
    ])


def sell_bank_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, Use This Account", callback_data="sell_bank_yes")],
        [InlineKeyboardButton(text="🏦 Use Different Account", callback_data="sell_change_bank")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="sell_cancel")],
    ])


def after_sell_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="📋 History", callback_data="cmd_history"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── History filter ─────────────────────────────────────────────

def history_filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="All", callback_data="history_all"),
            InlineKeyboardButton(text="Sent", callback_data="history_sent"),
            InlineKeyboardButton(text="Received", callback_data="history_received"),
            InlineKeyboardButton(text="Buy/Sell", callback_data="history_buysell"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Referral ───────────────────────────────────────────────────

def refer_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Copy Link", callback_data="refer_copy"),
            InlineKeyboardButton(
                text="📲 Share",
                switch_inline_query=f"Join Sidicoin! Get 80 SIDI free: {referral_link}",
            ),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Premium ────────────────────────────────────────────────────

def premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Upgrade Now — ₦1,500/month", callback_data="premium_upgrade")],
        [InlineKeyboardButton(text="Maybe Later", callback_data="cmd_home")],
    ])


def premium_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="I Have Paid", callback_data="premium_paid")],
        [InlineKeyboardButton(text="Cancel", callback_data="cmd_home")],
    ])


# ── Leaderboard ───────────────────────────────────────────────

def leaderboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Weekly", callback_data="leaderboard_weekly"),
            InlineKeyboardButton(text="All Time", callback_data="leaderboard_all"),
            InlineKeyboardButton(text="Referrals", callback_data="leaderboard_referrals"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Settings ───────────────────────────────────────────────────

def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 Update Bank", callback_data="settings_bank"),
            InlineKeyboardButton(text="🔔 Notifications", callback_data="settings_notif"),
        ],
        [
            InlineKeyboardButton(text="📋 Copy Wallet Address", callback_data="settings_wallet"),
            InlineKeyboardButton(text="❓ Help", callback_data="cmd_help"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Help ───────────────────────────────────────────────────────

def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Send", callback_data="cmd_send"),
            InlineKeyboardButton(text="💳 Buy", callback_data="cmd_buy"),
        ],
        [
            InlineKeyboardButton(text="💰 Sell", callback_data="cmd_sell"),
            InlineKeyboardButton(text="📊 Balance", callback_data="cmd_balance"),
        ],
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])


# ── Contacts ───────────────────────────────────────────────────

def contacts_keyboard(contacts: list[dict]) -> InlineKeyboardMarkup:
    """Build keyboard from saved contacts (quick send buttons)."""
    buttons = []
    for contact in contacts[:10]:
        username = contact.get("username", "")
        name = contact.get("full_name", username)
        display = f"📤 {name}" if name else f"📤 @{username}"
        buttons.append([
            InlineKeyboardButton(
                text=display,
                callback_data=f"contact_send_{contact.get('telegram_id', '')}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Generic ────────────────────────────────────────────────────

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")],
    ])


def home_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Home", callback_data="cmd_home")],
    ])
