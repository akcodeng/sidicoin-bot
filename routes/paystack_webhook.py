"""
Paystack webhook handler for card, mobile money, and bank transfer payments.
Paystack verifies webhooks via HMAC-SHA512 (x-paystack-signature header).
"""

import logging
import time

from fastapi import APIRouter, Request, HTTPException

from services.paystack import verify_webhook, verify_transaction, convert_to_ngn
from services.redis import (
    get_user, save_user, add_transaction, increment_stat,
    unlock_referral_earnings_on_tx,
)
from utils.formatting import naira_to_sidi, fmt_number, fmt_naira

logger = logging.getLogger("sidicoin.paystack_webhook")

router = APIRouter(prefix="/webhook", tags=["paystack"])


@router.post("/paystack")
async def paystack_webhook(request: Request):
    """
    Handle Paystack webhook events.
    Paystack sends x-paystack-signature header (HMAC-SHA512).
    """
    try:
        raw_body = await request.body()
        signature = request.headers.get("x-paystack-signature", "")

        if not verify_webhook(raw_body, signature):
            logger.warning("Paystack webhook: invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        body = await request.json()
        event = body.get("event", "")
        data = body.get("data", {})

        logger.info(f"Paystack webhook event: {event}")

        if event == "charge.success":
            await _handle_charge_success(data)
        elif event == "transfer.success":
            await _handle_transfer_success(data)
        elif event == "transfer.failed":
            await _handle_transfer_failed(data)
        elif event == "transfer.reversed":
            await _handle_transfer_failed(data)

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Paystack webhook error: {e}", exc_info=True)
        return {"status": "ok"}  # Always return 200 to prevent retries


async def _handle_charge_success(data: dict):
    """Handle a successful payment (user buying SIDI)."""
    try:
        reference = data.get("reference", "")
        # Paystack returns amount in kobo/pesewas
        amount_minor = float(data.get("amount", 0))
        amount = amount_minor / 100.0
        currency = data.get("currency", "NGN")
        channel = data.get("channel", "")
        gateway_response = data.get("gateway_response", "")

        # Double-verify the transaction with Paystack
        verification = await verify_transaction(reference)
        if not verification.get("success") or verification.get("status") != "success":
            logger.warning(f"Paystack verification failed for {reference}: {verification}")
            return

        # Extract user telegram_id from reference (format: BUY-{telegram_id}-{timestamp})
        parts = reference.split("-")
        if len(parts) < 2:
            logger.error(f"Invalid reference format: {reference}")
            return

        telegram_id = parts[1]
        user = get_user(telegram_id)
        if not user:
            logger.error(f"User not found for Paystack payment: {telegram_id}")
            return

        # Convert to NGN equivalent, then to SIDI
        ngn_amount = convert_to_ngn(amount, currency) if currency != "NGN" else amount
        sidi_amount = naira_to_sidi(ngn_amount)

        # Credit user (zero fees)
        user["sidi_balance"] = float(user.get("sidi_balance", 0)) + sidi_amount
        user["total_bought_ngn"] = float(user.get("total_bought_ngn", 0)) + ngn_amount
        save_user(telegram_id, user)

        now = int(time.time())

        add_transaction(telegram_id, {
            "type": "buy",
            "amount": sidi_amount,
            "amount_fiat": amount,
            "currency": currency,
            "channel": channel,
            "description": f"Bought {fmt_number(sidi_amount)} SIDI via Paystack ({currency} {channel})",
            "timestamp": now,
            "reference": reference,
        })

        # Update stats
        increment_stat("total_buy_volume_ngn", ngn_amount)
        increment_stat("daily_volume_ngn", ngn_amount)
        increment_stat("daily_tx_count", 1)
        increment_stat("circulating_supply", sidi_amount)

        # Unlock referral earnings
        unlock_referral_earnings_on_tx(telegram_id)

        # Notify user via bot
        try:
            from main import bot
            from services.notifications import notify_user
            await notify_user(
                bot, telegram_id,
                f"\u2705 <b>Payment Received!</b>\n\n"
                f"+<b>{fmt_number(sidi_amount)} SIDI</b> added to your wallet\n\n"
                f"  Paid: {amount} {currency} ({channel})\n"
                f"  Ref: <code>{reference}</code>\n\n"
                f"Your money is ready to use \u2726",
            )
        except Exception as e:
            logger.error(f"Could not notify user {telegram_id}: {e}")

        logger.info(
            f"Paystack buy credited: {telegram_id} +{sidi_amount} SIDI "
            f"({amount} {currency} via {channel})"
        )

    except Exception as e:
        logger.error(f"Handle charge success error: {e}", exc_info=True)


async def _handle_transfer_success(data: dict):
    """Handle a successful payout/transfer."""
    try:
        reference = data.get("reference", "")
        amount_minor = float(data.get("amount", 0))
        amount = amount_minor / 100.0
        currency = data.get("currency", "NGN")

        logger.info(
            f"Paystack transfer success: {reference}, "
            f"amount={amount} {currency}"
        )
        # Transfers are already deducted at creation time. Nothing to do.

    except Exception as e:
        logger.error(f"Handle transfer success error: {e}", exc_info=True)


async def _handle_transfer_failed(data: dict):
    """Handle a failed or reversed payout. Refund the user."""
    try:
        reference = data.get("reference", "")
        amount_minor = float(data.get("amount", 0))
        amount = amount_minor / 100.0
        currency = data.get("currency", "NGN")
        reason = data.get("reason", data.get("gateway_response", "Unknown"))

        logger.warning(
            f"Paystack transfer failed: {reference}, "
            f"amount={amount} {currency}, reason={reason}"
        )

        # Extract user telegram_id from reference
        parts = reference.split("-")
        if len(parts) < 2:
            return

        telegram_id = parts[1]
        user = get_user(telegram_id)
        if not user:
            return

        ngn_amount = convert_to_ngn(amount, currency) if currency != "NGN" else amount
        sidi_amount = naira_to_sidi(ngn_amount)

        # Refund
        user["sidi_balance"] = float(user.get("sidi_balance", 0)) + sidi_amount
        save_user(telegram_id, user)

        add_transaction(telegram_id, {
            "type": "refund",
            "amount": sidi_amount,
            "description": f"Payout failed, refunded {fmt_number(sidi_amount)} SIDI ({reason})",
            "timestamp": int(time.time()),
            "reference": f"REFUND-{reference}",
        })

        # Notify user
        try:
            from main import bot
            from services.notifications import notify_user
            await notify_user(
                bot, telegram_id,
                f"\u26a0\ufe0f <b>Payout Failed</b>\n\n"
                f"Your withdrawal of {amount} {currency} could not be completed.\n"
                f"Reason: {reason}\n\n"
                f"+<b>{fmt_number(sidi_amount)} SIDI</b> refunded to your wallet.\n\n"
                f"Please check your bank details and try again \u2726",
            )
        except Exception as e:
            logger.error(f"Could not notify user {telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Handle transfer failed error: {e}", exc_info=True)
