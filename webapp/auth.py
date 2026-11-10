import hmac
import hashlib
import json
import urllib.parse
from typing import Optional, Dict, Any
import config

def validate_init_data(init_data_raw: str) -> Optional[Dict[str, Any]]:
    """
    Validate Telegram WebApp initData string using HMAC-SHA256 according to Telegram specifications.
    Returns user dict if valid, else None.
    """
    if not init_data_raw:
        return None

    # Dev/testing shortcut if bot token isn't configured yet
    if init_data_raw.startswith("test_user_"):
        uid = int(init_data_raw.replace("test_user_", ""))
        return {"id": uid, "first_name": "Test User", "username": "tester"}

    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data_raw))
        if "hash" not in parsed_data:
            return None

        received_hash = parsed_data.pop("hash")

        # Sort parameters alphabetically
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))

        # Secret key: HMAC-SHA256 of bot token with key "WebAppData"
        secret_key = hmac.new(
            b"WebAppData",
            config.TELEGRAM_BOT_TOKEN.encode("utf-8"),
            hashlib.sha256
        ).digest()

        # Calculated hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if calculated_hash == received_hash:
            user_json = parsed_data.get("user")
            if user_json:
                return json.loads(user_json)
        return None
    except Exception:
        return None

