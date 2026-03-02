"""
Korapay webhook route.
Handles payment confirmations for buy SIDI and premium subscriptions.
Endpoint: POST /webhook/korapay
Verifies HMAC-SHA512 signature before processing.
"""

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.korapay import verify_webhook_signature
from services.redis import (
    get_pending_payment,
    delete_pending_payment,
    get_user,
    update_balance,
    add_transaction,
    save_user,
    activate_premium,
    credit_referrer,
    increment_stat,
    clear_pending_action,
    unlock_referral_earnings_on_tx,
)
from services.notifications import notify_user, notify_admin
from utils.formatting import (
    fmt_number,
    sidi_to_naira,
    fmt_naira,
    generate_tx_reference,
    generate_receipt,
    STAR,
    DIVIDER,
)

router = APIRouter()
logger = logging.getLogger("sidicoin.routes.korapay")


@router.post("/webhook/korapay")
async def korapay_webhook(request: Request):
    """
    Process Korapay payment webhook.
    Steps:
    1. Verify HMAC-SHA512 signature
    2. Extract payment reference and status
    3. Match to pending payment in Redis
    4. Credit user SIDI or activate premium
    5. Notify user and referrer
    """
    try:
        raw_body = await request.body()
        signature = request.headers.get("x-korapay-signature", "")

        # Verify webhook authenticity
        if not verify_webhook_signature(raw_body, signature):
            logger.warning("Korapay webhook signature verification failed")
            return JSONResponse(
                content={"status": "error", "message": "Invalid signature"},
                status_code=401,
            )

        body = await request.json()
        event = body.get("event", "")
        data = body.get("data", {})

        logger.info(f"Korapay webhook received: event={event}")

        # Only process successful charge events
        if event not in ("charge.success", "charge.completed"):
            logger.info(f"Ignoring Korapay event: {event}")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        reference = data.get("reference", "")
        status = data.get("status", "")
        amount_paid = float(data.get("amount", 0))

        if status not in ("success", "completed"):
            logger.info(f"Ignoring non-success payment: ref={reference}, status={status}")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        # Look up the pending payment
        pending = get_pending_payment(reference)
        if not pending:
            logger.warning(f"No pending payment found for reference: {reference}")
            # Notify admin about unmatched payment
            from main import bot
            await notify_admin(
                bot,
                f"⚠️ Unmatched Korapay payment\n"
                f"Reference: {reference}\n"
                f"Amount: ₦{fmt_number(amount_paid)}\n"
                f"Status: {status}",
            )
            return JSONResponse(content={"status": "ok"}, status_code=200)

        telegram_id = pending.get("telegram_id", "")
        payment_type = pending.get("type", "buy")

        from main import bot

        if payment_type == "buy":
            await _process_buy_payment(bot, telegram_id, pending, reference, amount_paid)
        elif payment_type == "premium":
            await _process_premium_payment(bot, telegram_id, pending, reference)
        else:
            logger.warning(f"Unknown payment type: {payment_type}")

        # Clean up pending payment
        delete_pending_payment(reference)
        clear_pending_action(telegram_id)

        return JSONResponse(content={"status": "ok"}, status_code=200)

    except Exception as e:
        logger.error(f"Korapay webhook processing error: {e}", exc_info=True)
        return JSONResponse(content={"status": "ok"}, status_code=200)


async def _process_buy_payment(bot, telegram_id: str, pending: dict, reference: str, amount_paid: float):
    """Process a successful buy SIDI payment."""
    sidi_amount = float(pending.get("sidi_amount", 0))
    expected_ngn = float(pending.get("ngn_amount", 0))

    if sidi_amount <= 0:
        logger.error(f"Invalid SIDI amount for buy payment: {sidi_amount}")
        return

    # Verify payment amount matches expected (allow 1% tolerance for bank rounding)
    if expected_ngn > 0 and amount_paid > 0:
        tolerance = expected_ngn * 0.01
        if abs(amount_paid - expected_ngn) > tolerance:
            logger.warning(
                f"Payment amount mismatch: expected ₦{expected_ngn}, got ₦{amount_paid} "
                f"(ref={reference}, user={telegram_id})"
            )
            # Still process but notify admin of discrepancy
            await notify_admin(
                bot,
                f"⚠️ Payment amount mismatch\n"
                f"User: {telegram_id}\n"
                f"Expected: ₦{fmt_number(expected_ngn)}\n"
                f"Received: ₦{fmt_number(amount_paid)}\n"
                f"Reference: {reference}\n"
                f"SIDI credited: {fmt_number(sidi_amount)}",
            )

    # Credit user
    success = update_balance(telegram_id, sidi_amount)
    if not success:
        logger.error(f"Failed to credit {sidi_amount} SIDI to user {telegram_id}")
        await notify_admin(
            bot,
            f"CRITICAL: Failed to credit {fmt_number(sidi_amount)} SIDI to user {telegram_id}\n"
            f"Reference: {reference}\nAmount paid: ₦{fmt_number(amount_paid)}",
        )
        return

    # Record transaction
    now = int(time.time())
    add_transaction(telegram_id, {
        "type": "buy",
        "amount": sidi_amount,
        "description": f"Bought {fmt_number(sidi_amount)} SIDI for ₦{fmt_number(amount_paid)}",
        "timestamp": now,
        "reference": reference,
    })

    # Update stats
    user = get_user(telegram_id)
    if user:
        user["total_bought_ngn"] = float(user.get("total_bought_ngn", 0)) + amount_paid
        save_user(telegram_id, user)

    increment_stat("circulating_supply", sidi_amount)
    increment_stat("daily_volume_ngn", amount_paid)
    increment_stat("daily_tx_count", 1)

    # Refresh user for balance
    user = get_user(telegram_id)
    new_balance = float(user.get("sidi_balance", 0)) if user else sidi_amount

    # Notify user with beautiful confirmation
    from bot.keyboards import after_buy_keyboard
    text = (
        f"{STAR} <b>Payment Confirmed!</b>\n\n"
        f"{DIVIDER}\n\n"
        f"  \U0001f4b3 +<b>{fmt_number(sidi_amount)} SIDI</b>\n"
        f"  \U0001f4b5 Paid: {fmt_naira(amount_paid)}\n"
        f"  \U0001f48e Balance: <b>{fmt_number(new_balance)} SIDI</b>\n"
        f"       ({fmt_naira(sidi_to_naira(new_balance))})\n\n"
        f"{DIVIDER}\n\n"
        f"  Your SIDI is ready to use {STAR}"
    )
    await notify_user(bot, telegram_id, text, reply_markup=after_buy_keyboard())

    logger.info(f"Buy payment processed: {telegram_id} +{sidi_amount} SIDI (₦{amount_paid})")

    # Unlock referral earnings when user makes a transaction (buy)
    unlock_referral_earnings_on_tx(telegram_id)

    # Credit referrer +10 SIDI for purchase
    if user and user.get("referred_by"):
        try:
            referrer_id = user["referred_by"]
            credit_referrer(referrer_id, 10.0, "purchase")
            referrer = get_user(referrer_id)
            if referrer:
                await notify_user(
                    bot,
                    referrer_id,
                    f"💰 Your referral just bought SIDI!\n"
                    f"+<b>10 SIDI</b> ({fmt_naira(sidi_to_naira(10))}) referral bonus added ✦",
                )
        except Exception as e:
            logger.error(f"Referral bonus error on buy: {e}")


async def _process_premium_payment(bot, telegram_id: str, pending: dict, reference: str):
    """Process a successful premium subscription payment."""
    success = activate_premium(telegram_id)

    if not success:
        logger.error(f"Failed to activate premium for user {telegram_id}")
        await notify_admin(
            bot,
            f"CRITICAL: Failed to activate premium for user {telegram_id}\n"
            f"Reference: {reference}",
        )
        return

    # Record transaction
    now = int(time.time())
    add_transaction(telegram_id, {
        "type": "premium",
        "amount": 0,
        "description": "Premium subscription activated (30 days)",
        "timestamp": now,
        "reference": reference,
    })

    increment_stat("premium_subscriptions", 1)
    increment_stat("daily_volume_ngn", 1500)

    # Notify user with beautiful premium message
    from bot.keyboards import home_keyboard
    text = (
        f"{STAR} <b>Premium Activated!</b>\n\n"
        f"Welcome to Sidicoin Premium {STAR}\n\n"
        f"{DIVIDER}\n\n"
        f"  Your benefits (30 days):\n\n"
        f"  \u26a1 500,000 SIDI daily limit\n"
        f"  \U0001f4b0 0.8% reduced fees\n"
        f"  \U0001f48e 5 SIDI daily check-in\n"
        f"  {STAR} Premium badge\n"
        f"  \U0001f3c6 Priority support\n\n"
        f"{DIVIDER}\n\n"
        f"  Thank you for upgrading {STAR}"
    )
    await notify_user(bot, telegram_id, text, reply_markup=home_keyboard())

    logger.info(f"Premium activated for user {telegram_id}")
