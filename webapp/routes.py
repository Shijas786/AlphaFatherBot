import json
import logging
from aiohttp import web
from database.db import (
    get_user,
    create_or_update_user,
    update_user_fields,
    get_user_trades,
    get_recent_listings,
    get_user_profit_stats,
    get_active_groups,
    get_all_users,
    get_active_traders
)
from database.encryption import encrypt_secret, decrypt_secret
from services.binance_service import binance_service
from services.position_tracker import position_tracker
from webapp.auth import validate_init_data

logger = logging.getLogger(__name__)

def get_auth_user(request: web.Request) -> dict:
    """Extract and validate user from Authorization header (Telegram initData)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        init_data = auth_header[7:].strip()
    else:
        init_data = auth_header.strip()

    user_info = validate_init_data(init_data)
    if not user_info or "id" not in user_info:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Invalid or missing Telegram authentication"}),
            content_type="application/json"
        )
    return user_info

async def api_get_user(request: web.Request):
    """GET /api/user - Retrieve user profile and settings."""
    tg_user = get_auth_user(request)
    user_id = tg_user["id"]
    
    user = await get_user(user_id)
    if not user:
        user = await create_or_update_user(
            telegram_id=user_id,
            username=tg_user.get("username", ""),
            first_name=tg_user.get("first_name", "")
        )

    has_api = bool(user.get("binance_api_key"))
    balances = {
        "usdt": 0.0,
        "usdc": 0.0,
        "spot_usdt": 0.0,
        "spot_usdc": 0.0,
        "futures_usdt": 0.0,
        "futures_usdc": 0.0,
        "total": 0.0,
        "error": None,
        "error_code": None
    }
    if has_api:
        try:
            k = decrypt_secret(user.get("binance_api_key"))
            s = decrypt_secret(user.get("binance_api_secret"))
            balances = await binance_service.get_balances(k, s, is_futures=(user.get("trade_mode") == "futures"))
        except Exception as e:
            balances["error"] = str(e)

    stats = await get_user_profit_stats(user_id)

    return web.json_response({
        "success": True,
        "user": {
            "telegram_id": user["telegram_id"],
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
            "is_active": bool(user.get("is_active", 0)),
            "trade_mode": user.get("trade_mode", "spot"),
            "order_amount_usdt": user.get("order_amount_usdt", 50.0),
            "futures_leverage": user.get("futures_leverage", 3),
            "tp_percent": user.get("tp_percent", 15.0),
            "sl_percent": user.get("sl_percent", 5.0),
            "max_hold_seconds": user.get("max_hold_seconds", 60),
            "has_api_keys": has_api,
            "api_error": balances.get("error"),
            "api_error_code": balances.get("error_code"),
            "usdt_balance": balances.get("usdt", 0.0),
            "usdc_balance": balances.get("usdc", 0.0),
            "spot_usdt": balances.get("spot_usdt", 0.0),
            "spot_usdc": balances.get("spot_usdc", 0.0),
            "futures_usdt": balances.get("futures_usdt", 0.0),
            "futures_usdc": balances.get("futures_usdc", 0.0),
            "total_balance": balances.get("total", 0.0),
            "stats": stats
        }
    })

async def api_update_settings(request: web.Request):
    """POST /api/user/settings - Update trading parameters."""
    tg_user = get_auth_user(request)
    user_id = tg_user["id"]
    data = await request.json()

    allowed_fields = [
        "is_active", "trade_mode", "order_amount_usdt",
        "futures_leverage", "tp_percent", "sl_percent", "max_hold_seconds"
    ]

    updates = {}
    for k in allowed_fields:
        if k in data:
            updates[k] = data[k]

    if updates:
        await update_user_fields(user_id, **updates)

    return web.json_response({"success": True, "message": "Settings updated"})

async def api_save_api_keys(request: web.Request):
    """POST /api/user/api-keys - Connect Binance API."""
    tg_user = get_auth_user(request)
    user_id = tg_user["id"]
    data = await request.json()

    api_key = data.get("api_key", "").strip()
    api_secret = data.get("api_secret", "").strip()

    if not api_key or not api_secret:
        return web.json_response({"success": False, "error": "Both API Key and Secret are required."}, status=400)

    # Test credentials with Binance
    user = await get_user(user_id)
    is_futures = (user.get("trade_mode") == "futures") if user else False
    is_valid, msg = await binance_service.test_credentials(api_key, api_secret, check_futures=is_futures)

    if not is_valid:
        return web.json_response({"success": False, "error": msg}, status=400)

    # Encrypt and save
    enc_k = encrypt_secret(api_key)
    enc_s = encrypt_secret(api_secret)
    await update_user_fields(user_id, binance_api_key=enc_k, binance_api_secret=enc_s)

    balance = await binance_service.get_balance(api_key, api_secret, is_futures=is_futures)
    return web.json_response({
        "success": True,
        "message": "Binance API keys connected successfully!",
        "balance": balance
    })

async def api_get_trades(request: web.Request):
    """GET /api/trades - List user's recent trades and active positions with live mark prices."""
    tg_user = get_auth_user(request)
    user_id = tg_user["id"]
    user = await get_user(user_id)
    trades = await get_user_trades(user_id, limit=20)

    # For any open trade, calculate live real-time price & PnL
    for t in trades:
        if t.get("status") == "OPEN":
            symbol = t["symbol"]
            is_futures = (t.get("trade_mode") == "futures")
            buy_price = float(t.get("buy_price", 0.0))
            if buy_price > 0:
                current_p = await binance_service.get_symbol_price(symbol, is_futures=is_futures)
                if current_p > 0:
                    t["current_price"] = current_p
                    leverage = user.get("futures_leverage", 1) if (user and is_futures) else 1
                    t["pnl_percent"] = ((current_p - buy_price) / buy_price) * 100.0 * leverage

    return web.json_response({"success": True, "trades": trades})

async def api_panic_sell(request: web.Request):
    """POST /api/trades/panic-sell - Trigger immediate panic sell."""
    tg_user = get_auth_user(request)
    user_id = tg_user["id"]
    data = await request.json()
    trade_id = int(data.get("trade_id", 0))

    user = await get_user(user_id)
    if not user:
        return web.json_response({"success": False, "error": "User not found"}, status=404)

    res = await position_tracker.panic_sell_manual(trade_id, user)
    return web.json_response(res)

async def api_get_listings(request: web.Request):
    """GET /api/listings - Get recent detected Upbit listings feed."""
    listings = await get_recent_listings(limit=15)
    return web.json_response({"success": True, "listings": listings})

async def api_get_server_ip(request: web.Request):
    """GET /api/ip - Get server outbound IP for Binance trusted IP whitelist."""
    try:
        session = await binance_service.get_session()
        async with session.get("https://api.ipify.org?format=json", timeout=3) as resp:
            if resp.status == 200:
                data = await resp.json()
                return web.json_response({"success": True, "ip": data.get("ip")})
    except Exception as e:
        logger.error(f"Failed to fetch outbound IP: {e}")
    return web.json_response({"success": False, "error": "Could not determine IP"})

async def api_get_system_status(request: web.Request):
    """GET /api/status - Live health, registered groups, and sniper engine metrics."""
    groups = await get_active_groups()
    users = await get_all_users()
    active_traders = await get_active_traders()
    listings = await get_recent_listings(limit=5)

    outbound_ip = "Unknown"
    try:
        session = await binance_service.get_session()
        async with session.get("https://api.ipify.org?format=json", timeout=3) as resp:
            if resp.status == 200:
                data = await resp.json()
                outbound_ip = data.get("ip", "Unknown")
    except Exception:
        pass

    return web.json_response({
        "success": True,
        "engine": "The Capo Sniper v2.0",
        "outbound_ip": outbound_ip,
        "active_groups_count": len(groups),
        "groups": [{"chat_id": g["chat_id"], "title": g["title"], "chat_type": g["chat_type"]} for g in groups],
        "registered_users": len(users),
        "active_snipers": len(active_traders),
        "recent_listings_count": len(listings)
    })


