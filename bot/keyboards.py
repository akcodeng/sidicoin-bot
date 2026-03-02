"""
Inline keyboard builders for SidiApp bot.
Every message must end with relevant action buttons.
Uses descriptive, branded button labels.
"""

import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo


# =====================================================================
#  HOME / MAIN MENU
# =====================================================================

def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4e4 Send Money", callback_data="cmd_send"),
            InlineKeyboardButton(text="\U0001f4b3 Buy SIDI", callback_data="cmd_buy"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4b0 Cash Out", callback_data="cmd_sell"),
            InlineKeyboardButton(text="\U0001f6e1 Escrow", callback_data="cmd_escrow"),
        ],
        [
            InlineKeyboardButton(text="\U0001f381 Earn Free", callback_data="cmd_refer"),
            InlineKeyboardButton(text="\U0001f3ae Games", callback_data="cmd_game"),
        ],
        [
            InlineKeyboardButton(text="\U0001f48e My Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="\u2699\ufe0f Account", callback_data="cmd_settings"),
        ],
    ])


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f48e My Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="\U0001f4e4 Send Money", callback_data="cmd_send"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4b3 Buy SIDI", callback_data="cmd_buy"),
            InlineKeyboardButton(text="\u2753 How It Works", callback_data="cmd_help"),
        ],
    ])


# =====================================================================
#  ONBOARDING
# =====================================================================

def onboarding_step1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Let's Go \u2192", callback_data="onboard_2")],
    ])


def onboarding_step2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Got It \u2192", callback_data="onboard_3")],
    ])


def onboarding_step3_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4b3 Buy SIDI Now", callback_data="cmd_buy"),
            InlineKeyboardButton(text="\U0001f381 Refer & Earn", callback_data="cmd_refer"),
        ],
        [
            InlineKeyboardButton(text="\u2705 Daily Check-In", callback_data="cmd_checkin"),
            InlineKeyboardButton(text="\U0001f3ae Play Games", callback_data="cmd_game"),
        ],
    ])


# =====================================================================
#  BALANCE / WALLET
# =====================================================================

def balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4e4 Send", callback_data="cmd_send"),
            InlineKeyboardButton(text="\U0001f4b3 Buy", callback_data="cmd_buy"),
            InlineKeyboardButton(text="\U0001f4b0 Sell", callback_data="cmd_sell"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4cb History", callback_data="cmd_history"),
            InlineKeyboardButton(text="\U0001f3c6 Rank", callback_data="cmd_leaderboard"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  SEND FLOW
# =====================================================================

def send_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\u2705 Confirm Transfer", callback_data="send_confirm"),
        ],
        [
            InlineKeyboardButton(text="\u274c Cancel", callback_data="send_cancel"),
        ],
    ])


def send_large_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u26a0\ufe0f Confirm Large Transfer",
                callback_data="send_confirm",
            ),
        ],
        [
            InlineKeyboardButton(text="\u274c Cancel", callback_data="send_cancel"),
        ],
    ])


def after_send_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4c4 Download Receipt", callback_data="receipt_download"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4e4 Send More", callback_data="cmd_send"),
            InlineKeyboardButton(text="\U0001f48e Wallet", callback_data="cmd_balance"),
        ],
        [
            InlineKeyboardButton(text="\U0001f381 Share SidiApp", callback_data="cmd_refer"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


def received_money_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4b0 Cash Out", callback_data="cmd_sell"),
            InlineKeyboardButton(text="\U0001f4e4 Send Back", callback_data="cmd_send"),
        ],
        [
            InlineKeyboardButton(text="\U0001f48e My Wallet", callback_data="cmd_balance"),
        ],
    ])


# =====================================================================
#  BUY FLOW
# =====================================================================

def buy_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 Proceed to Pay", callback_data="buy_proceed")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="buy_cancel")],
    ])


def buy_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4b8 I Have Paid", callback_data="buy_paid")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="buy_cancel")],
    ])


def after_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4c4 Download Receipt", callback_data="receipt_download"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4e4 Send SIDI", callback_data="cmd_send"),
            InlineKeyboardButton(text="\U0001f48e Wallet", callback_data="cmd_balance"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  SELL / CASHOUT FLOW
# =====================================================================

def sell_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 Confirm Cashout", callback_data="sell_confirm")],
        [InlineKeyboardButton(text="\U0001f3e6 Change Bank", callback_data="sell_change_bank")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="sell_cancel")],
    ])


def sell_bank_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 Use This Account", callback_data="sell_bank_yes")],
        [InlineKeyboardButton(text="\U0001f3e6 Different Account", callback_data="sell_change_bank")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="sell_cancel")],
    ])


def after_sell_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4c4 Download Receipt", callback_data="receipt_download"),
        ],
        [
            InlineKeyboardButton(text="\U0001f48e Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="\U0001f4cb History", callback_data="cmd_history"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  HISTORY FILTER
# =====================================================================

def history_filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="All", callback_data="history_all"),
            InlineKeyboardButton(text="Sent", callback_data="history_sent"),
            InlineKeyboardButton(text="Received", callback_data="history_received"),
            InlineKeyboardButton(text="Buy/Sell", callback_data="history_buysell"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  REFERRAL
# =====================================================================

def refer_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\U0001f4cb Copy Link",
                callback_data="refer_copy",
            ),
            InlineKeyboardButton(
                text="\U0001f4f2 Share Now",
                switch_inline_query=(
                    f"Join me on SidiApp and get 10 SIDI (\u20a6250) free! "
                    f"Send money anywhere in Africa instantly. {referral_link}"
                ),
            ),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  PREMIUM
# =====================================================================

def premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u2b50 Upgrade to Premium \u2014 \u20a61,500/mo",
                callback_data="premium_upgrade",
            )
        ],
        [InlineKeyboardButton(text="Maybe Later", callback_data="cmd_home")],
    ])


def premium_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4b8 I Have Paid", callback_data="premium_paid")],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
    ])


# =====================================================================
#  LEADERBOARD
# =====================================================================

def leaderboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4c8 All Time", callback_data="leaderboard_all"),
            InlineKeyboardButton(text="\U0001f465 Referrals", callback_data="leaderboard_referrals"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  SETTINGS
# =====================================================================

def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f3e6 Update Bank", callback_data="settings_bank"),
            InlineKeyboardButton(text="\U0001f4cb Wallet Address", callback_data="settings_wallet"),
        ],
        [
            InlineKeyboardButton(text="\u2b50 Premium", callback_data="cmd_premium"),
            InlineKeyboardButton(text="\u2753 Help", callback_data="cmd_help"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  HELP
# =====================================================================

def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f4e4 Send", callback_data="cmd_send"),
            InlineKeyboardButton(text="\U0001f4b3 Buy", callback_data="cmd_buy"),
            InlineKeyboardButton(text="\U0001f4b0 Sell", callback_data="cmd_sell"),
        ],
        [
            InlineKeyboardButton(text="\U0001f48e Wallet", callback_data="cmd_balance"),
            InlineKeyboardButton(text="\U0001f381 Refer", callback_data="cmd_refer"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  CONTACTS
# =====================================================================

def contacts_keyboard(contacts: list[dict]) -> InlineKeyboardMarkup:
    """Build keyboard from saved contacts (quick send buttons)."""
    buttons = []
    for contact in contacts[:10]:
        username = contact.get("username", "")
        name = contact.get("full_name", username)
        display = f"\U0001f4e4 {name or f'@{username}'}"
        buttons.append([
            InlineKeyboardButton(
                text=display,
                callback_data=f"contact_send_{contact.get('telegram_id', '')}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================================
#  GAMES
# =====================================================================

def game_menu_keyboard() -> InlineKeyboardMarkup:
    base_url = os.getenv("WEBHOOK_BASE_URL", "https://coin.sidihost.sbs")
    game_url = f"{base_url}/game"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\U0001f3ae Play Now",
                web_app=WebAppInfo(url=game_url),
            ),
        ],
        [
            InlineKeyboardButton(text="\U0001fa99 Coin Flip", callback_data="game_coinflip"),
            InlineKeyboardButton(text="\U0001f3b2 Dice Roll", callback_data="game_dice"),
        ],
        [
            InlineKeyboardButton(text="\U0001f3b0 Lucky Number", callback_data="game_lucky"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


def coinflip_bet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 SIDI", callback_data="flip_bet_1"),
            InlineKeyboardButton(text="2 SIDI", callback_data="flip_bet_2"),
            InlineKeyboardButton(text="5 SIDI", callback_data="flip_bet_5"),
        ],
        [
            InlineKeyboardButton(text="10 SIDI", callback_data="flip_bet_10"),
            InlineKeyboardButton(text="Custom", callback_data="flip_bet_custom"),
        ],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
    ])


def coinflip_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f7e1 Heads", callback_data="flip_heads"),
            InlineKeyboardButton(text="\U0001f535 Tails", callback_data="flip_tails"),
        ],
    ])


def dice_bet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 SIDI", callback_data="dice_bet_1"),
            InlineKeyboardButton(text="2 SIDI", callback_data="dice_bet_2"),
            InlineKeyboardButton(text="5 SIDI", callback_data="dice_bet_5"),
        ],
        [
            InlineKeyboardButton(text="10 SIDI", callback_data="dice_bet_10"),
        ],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
    ])


def dice_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="dice_pick_1"),
            InlineKeyboardButton(text="2", callback_data="dice_pick_2"),
            InlineKeyboardButton(text="3", callback_data="dice_pick_3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="dice_pick_4"),
            InlineKeyboardButton(text="5", callback_data="dice_pick_5"),
            InlineKeyboardButton(text="6", callback_data="dice_pick_6"),
        ],
    ])


def lucky_number_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 SIDI", callback_data="lucky_bet_1"),
            InlineKeyboardButton(text="2 SIDI", callback_data="lucky_bet_2"),
            InlineKeyboardButton(text="5 SIDI", callback_data="lucky_bet_5"),
        ],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
    ])


def after_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f504 Play Again", callback_data="cmd_game"),
            InlineKeyboardButton(text="\U0001f48e Wallet", callback_data="cmd_balance"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  GENERIC
# =====================================================================

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cancel_action")],
    ])


def home_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  ESCROW
# =====================================================================

def escrow_create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f6d2 P2P Trade", callback_data="escrow_new_p2p"),
            InlineKeyboardButton(text="\U0001f30d Cross-Border", callback_data="escrow_new_xborder"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4cb My Escrows", callback_data="escrow_list"),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


def escrow_detail_keyboard(escrow_id: str, user_role: str, status: str) -> InlineKeyboardMarkup:
    """Dynamic buttons based on escrow state and user role."""
    buttons = []

    if status == "pending" and user_role == "buyer":
        buttons.append([InlineKeyboardButton(
            text="\U0001f4b3 Fund Escrow", callback_data=f"escrow_fund_{escrow_id}",
        )])
    if status == "funded" and user_role == "seller":
        buttons.append([InlineKeyboardButton(
            text="\U0001f4e6 Mark Delivered", callback_data=f"escrow_deliver_{escrow_id}",
        )])
    if status in ("funded", "delivered") and user_role == "buyer":
        buttons.append([InlineKeyboardButton(
            text="\u2705 Confirm & Release", callback_data=f"escrow_confirm_{escrow_id}",
        )])
    if status in ("funded", "delivered"):
        buttons.append([InlineKeyboardButton(
            text="\u26a0\ufe0f Raise Dispute", callback_data=f"escrow_dispute_{escrow_id}",
        )])
    if status == "pending":
        buttons.append([InlineKeyboardButton(
            text="\u274c Cancel", callback_data=f"escrow_cancel_{escrow_id}",
        )])

    buttons.append([InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def escrow_list_keyboard(escrows: list) -> InlineKeyboardMarkup:
    """Build keyboard from user's escrows."""
    buttons = []
    for esc in escrows[:8]:
        eid = esc.get("escrow_id", "")
        status = esc.get("status", "")
        amount = esc.get("amount_sidi", 0)
        desc = esc.get("description", "")[:20]
        status_icon = {
            "pending": "\u23f3", "funded": "\U0001f4b3", "delivered": "\U0001f4e6",
            "disputed": "\u26a0\ufe0f", "released": "\u2705", "cancelled": "\u274c",
        }.get(status, "\u2022")
        buttons.append([InlineKeyboardButton(
            text=f"{status_icon} {desc or eid[:8]} | {amount} SIDI",
            callback_data=f"escrow_view_{eid}",
        )])
    buttons.append([
        InlineKeyboardButton(text="\u2795 New Escrow", callback_data="cmd_escrow"),
        InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================================
#  SUPPORT / DONATE
# =====================================================================

def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\U0001f4b0 Support with SIDI",
                callback_data="support_sidi",
            ),
        ],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


# =====================================================================
#  FUND METHOD (international)
# =====================================================================

def fund_method_keyboard(country_code: str) -> InlineKeyboardMarkup:
    """Dynamic funding method based on user's country."""
    buttons = []

    from services.paystack import get_country_config
    config = get_country_config(country_code)
    methods = config.get("methods", ["card"])

    if "bank_transfer" in methods:
        buttons.append([InlineKeyboardButton(
            text="\U0001f3e6 Bank Transfer (NGN)", callback_data="fund_bank_ngn",
        )])
    if "card" in methods:
        buttons.append([InlineKeyboardButton(
            text="\U0001f4b3 Card (Visa/Mastercard)", callback_data="fund_card",
        )])
    if any(m.startswith("mobile_money") or m == "mpesa" for m in methods):
        buttons.append([InlineKeyboardButton(
            text="\U0001f4f1 Mobile Money", callback_data="fund_mobile_money",
        )])
    if "ussd" in methods:
        buttons.append([InlineKeyboardButton(
            text="\U0001f4de USSD", callback_data="fund_ussd",
        )])

    buttons.append([InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =====================================================================
#  MERCHANT
# =====================================================================

def merchant_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f517 Generate Payment Link", callback_data="merchant_create_link")],
        [InlineKeyboardButton(text="\U0001f4ca My Stats", callback_data="merchant_stats")],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


def merchant_apply_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4dd Apply for Merchant", callback_data="merchant_apply")],
        [InlineKeyboardButton(text="\U0001f3e0 Home", callback_data="cmd_home")],
    ])


def merchant_pay_confirm_keyboard(merchant_id: str, amount: float, ref: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"\u2705 Pay {amount} SIDI",
            callback_data=f"merchant_pay_{merchant_id}_{amount}_{ref}",
        )],
        [InlineKeyboardButton(text="\u274c Cancel", callback_data="cmd_home")],
    ])


# =====================================================================
#  GROUP KEYBOARDS
# =====================================================================

def giveaway_join_keyboard(giveaway_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="\U0001f389 Join Giveaway",
            callback_data=f"giveaway_join_{giveaway_id}",
        )],
    ])


def giveaway_end_keyboard(giveaway_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="\U0001f3c1 End & Pick Winners",
            callback_data=f"giveaway_end_{giveaway_id}",
        )],
    ])


def verify_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="\u2705 Start Verification",
            callback_data="verify_start",
        )],
    ])


def whois_tip_keyboard(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"\U0001f4b0 Tip @{username}",
            url=f"https://t.me/SidiAppBot?start=tip_{username}",
        )],
    ])
