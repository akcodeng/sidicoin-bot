"""
Flutterwave webhook handler for international payments.
Handles successful card, mobile money, and bank transfer payments.
"""

import logging

from fastapi import APIRouter, Request, HTTPException

from services.flutterwave import verify_webhook, verify_transaction
from services.redis import (
    get_user, save_user, add_transaction, increment_stat,
    store_pending_payment,
)
from utils.formatting import sidi_to_naira, naira_to_sidi, fmt_number, fmt_naira

logger = logging.getLogger("sidicoin.flutterwave_webhook")

router = APIRouter(prefix="/webhook", tags=["flutterwave"])


@router.post("/flutterwave")
async def flutterwave_webhook(request: Request):
    """
    Handle Flutterwave webhook events.
    Flutterwave sends a 'verif-hash' header to authenticate.
    """
    try:
        raw_body = await request.body()
        signature = request.headers.get("verif-hash", "")

        if not verify_webhook(raw_body, signature):
            logger.warning("Flutterwave webhook: invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        body = await request.json()
        event = body.get("event", "")
        data = body.get("data", {})

        logger.info(f"Flutterwave webhook event: {event}")

        if event == "charge.completed" and data.get("status") == "successful":
            await _handle_successful_charge(data)
        elif event == "transfer.completed":
            await _handle_transfer_complete(data)

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Flutterwave webhook error: {e}", exc_info=True)
        return {"status": "ok"}  # Always return 200 to prevent retries


async def _handle_successful_charge(data: dict):
    """Handle a successful payment (user buying SIDI)."""
    try:
        tx_ref = data.get("tx_ref", "")
        amount = float(data.get("amount", 0))
        currency = data.get("currency", "NGN")
        flw_ref = data.get("flw_ref", "")
        transaction_id = data.get("id", "")

        # Verify the transaction with Flutterwave
        verification = await verify_transaction(str(transaction_id))
        if not verification.get("success") or verification.get("status") != "successful":
            logger.warning(f"Flutterwave verification failed for {tx_ref}")
            return

        # Extract user telegram_id from tx_ref (format: BUY-{telegram_id}-{timestamp})
        parts = tx_ref.split("-")
        if len(parts) < 2:
            logger.error(f"Invalid tx_ref format: {tx_ref}")
            return

        telegram_id = parts[1]
        user = get_user(telegram_id)
        if not user:
            logger.error(f"User not found for Flutterwave payment: {telegram_id}")
            return

        # Convert to NGN equivalent, then to SIDI
        from services.flutterwave import convert_to_ngn
        ngn_amount = convert_to_ngn(amount, currency) if currency != "NGN" else amount
        sidi_amount = naira_to_sidi(ngn_amount)

        # Credit user (zero fees)
        user["sidi_balance"] = float(user.get("sidi_balance", 0)) + sidi_amount
        user["total_bought_ngn"] = float(user.get("total_bought_ngn", 0)) + ngn_amount
        save_user(telegram_id, user)

        import time
        now = int(time.time())

        add_transaction(telegram_id, {
            "type": "buy",
            "amount": sidi_amount,
            "amount_fiat": amount,
            "currency": currency,
            "description": f"Bought {fmt_number(sidi_amount)} SIDI via Flutterwave ({currency})",
            "timestamp": now,
            "reference": tx_ref,
            "flw_ref": flw_ref,
        })

        # Update stats
        increment_stat("total_buy_volume_ngn", ngn_amount)
        increment_stat("daily_volume_ngn", ngn_amount)
        increment_stat("daily_tx_count", 1)
        increment_stat("circulating_supply", sidi_amount)

        # Unlock referral earnings if applicable
        from services.redis import unlock_referral_earnings_on_tx
        unlock_referral_earnings_on_tx(telegram_id)

        # Notify user via bot
        try:
            from main import bot
            from services.notifications import notify_user
            await notify_user(
                bot, telegram_id,
                f"\u2705 <b>Payment Received!</b>\n\n"
                f"+<b>{fmt_number(sidi_amount)} SIDI</b> added to your wallet\n\n"
                f"  Paid: {amount} {currency}\n"
                f"  Ref: <code>{tx_ref}</code>\n\n"
                f"Your money is ready to use \u2726",
            )
        except Exception as e:
            logger.error(f"Could not notify user {telegram_id}: {e}")

        logger.info(
            f"Flutterwave buy credited: {telegram_id} +{sidi_amount} SIDI "
            f"({amount} {currency})"
        )

    except Exception as e:
        logger.error(f"Handle successful charge error: {e}", exc_info=True)


async def _handle_transfer_complete(data: dict):
    """Handle a completed payout/transfer."""
    try:
        reference = data.get("reference", "")
        status = data.get("status", "")
        amount = float(data.get("amount", 0))
        currency = data.get("currency", "NGN")

        logger.info(
            f"Flutterwave transfer {reference}: status={status}, "
            f"amount={amount} {currency}"
        )

        # Transfers are already deducted at creation time.
        # If transfer failed, we need to refund.
        if status == "FAILED":
            parts = reference.split("-")
            if len(parts) >= 2:
                telegram_id = parts[1]
                user = get_user(telegram_id)
                if user:
                    from services.flutterwave import convert_to_ngn
                    ngn_amount = convert_to_ngn(amount, currency) if currency != "NGN" else amount
                    sidi_amount = naira_to_sidi(ngn_amount)

                    user["sidi_balance"] = float(user.get("sidi_balance", 0)) + sidi_amount
                    save_user(telegram_id, user)

                    import time
                    add_transaction(telegram_id, {
                        "type": "refund",
                        "amount": sidi_amount,
                        "description": f"Payout failed, refunded {fmt_number(sidi_amount)} SIDI",
                        "timestamp": int(time.time()),
                        "reference": f"REFUND-{reference}",
                    })

                    try:
                        from main import bot
                        from services.notifications import notify_user
                        await notify_user(
                            bot, telegram_id,
                            f"\u26a0\ufe0f <b>Payout Failed</b>\n\n"
                            f"Your withdrawal of {amount} {currency} could not be completed.\n"
                            f"+<b>{fmt_number(sidi_amount)} SIDI</b> refunded to your wallet.\n\n"
                            f"Please check your bank details and try again \u2726",
                        )
                    except Exception as e:
                        logger.error(f"Could not notify user {telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Handle transfer complete error: {e}", exc_info=True)
