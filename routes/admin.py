"""
Admin REST API routes for server-side monitoring.
These provide lightweight JSON endpoints for checking
bot health and stats from the deployment server without Telegram.
Protected by ADMIN_TELEGRAM_ID in header (X-Admin-Id).
"""

import os
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.redis import (
    get_all_user_ids,
    get_all_stats,
    get_user,
    get_stat,
    get_leaderboard,
)
from utils.formatting import sidi_to_naira, fmt_number

router = APIRouter(prefix="/admin")
logger = logging.getLogger("sidicoin.routes.admin")

ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")


def _verify_admin(request: Request) -> bool:
    """Verify admin access via X-Admin-Id header."""
    admin_id = request.headers.get("X-Admin-Id", "")
    return admin_id == ADMIN_TELEGRAM_ID and ADMIN_TELEGRAM_ID != ""


@router.get("/stats")
async def admin_stats(request: Request):
    """Platform statistics overview."""
    if not _verify_admin(request):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=403)

    try:
        stats = get_all_stats()
        user_ids = get_all_user_ids()
        total_users = len(user_ids)

        active_24h = 0
        import time
        now = int(time.time())
        for uid in user_ids[:500]:
            user = get_user(uid)
            if user and (now - int(user.get("last_active", 0))) < 86400:
                active_24h += 1

        return JSONResponse(content={
            "total_users": total_users,
            "active_24h": active_24h,
            "total_holders": stats.get("total_holders", 0),
            "circulating_supply": stats.get("circulating_supply", 0),
            "daily_volume_ngn": stats.get("daily_volume_ngn", 0),
            "daily_tx_count": stats.get("daily_tx_count", 0),
            "total_fees_sidi": stats.get("total_fees_sidi", 0),
            "total_fees_ngn": sidi_to_naira(stats.get("total_fees_sidi", 0)),
            "premium_subscriptions": stats.get("premium_subscriptions", 0),
        })
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/users")
async def admin_users(request: Request):
    """List all users summary."""
    if not _verify_admin(request):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=403)

    try:
        user_ids = get_all_user_ids()
        users = []
        for uid in user_ids[:200]:
            user = get_user(uid)
            if user:
                users.append({
                    "telegram_id": user.get("telegram_id"),
                    "username": user.get("username"),
                    "full_name": user.get("full_name"),
                    "balance": float(user.get("sidi_balance", 0)),
                    "is_premium": user.get("is_premium", False),
                    "is_banned": user.get("is_banned", False),
                    "referral_count": int(user.get("referral_count", 0)),
                    "last_active": int(user.get("last_active", 0)),
                    "joined_date": int(user.get("joined_date", 0)),
                })
        return JSONResponse(content={"count": len(users), "users": users})
    except Exception as e:
        logger.error(f"Admin users error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/user/{telegram_id}")
async def admin_user_detail(telegram_id: str, request: Request):
    """Get detailed user profile."""
    if not _verify_admin(request):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=403)

    try:
        user = get_user(telegram_id)
        if not user:
            return JSONResponse(content={"error": "User not found"}, status_code=404)

        # Remove sensitive data
        safe = {k: v for k, v in user.items() if k != "private_key"}
        safe["balance_ngn"] = sidi_to_naira(float(user.get("sidi_balance", 0)))
        safe["transaction_count"] = len(user.get("transactions", []))
        safe["contact_count"] = len(user.get("saved_contacts", []))

        return JSONResponse(content=safe, default=str)
    except Exception as e:
        logger.error(f"Admin user detail error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/leaderboard")
async def admin_leaderboard(request: Request):
    """Top holders leaderboard."""
    if not _verify_admin(request):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=403)

    try:
        leaders = get_leaderboard(20)
        result = []
        for uid, score in leaders:
            user = get_user(uid)
            result.append({
                "telegram_id": uid,
                "username": user.get("username", "") if user else "",
                "balance": score,
                "balance_ngn": sidi_to_naira(score),
            })
        return JSONResponse(content={"leaderboard": result})
    except Exception as e:
        logger.error(f"Admin leaderboard error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/health")
async def admin_health(request: Request):
    """Detailed health check for monitoring."""
    try:
        from services.redis import redis
        # Quick Redis ping
        redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return JSONResponse(content={
        "status": "ok" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "error",
        "service": "Sidicoin Bot",
        "domain": "coin.sidihost.sbs",
    })
