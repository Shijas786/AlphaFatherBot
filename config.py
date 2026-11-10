import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0")) if os.getenv("ADMIN_USER_ID") else None

# Encryption Key
ENCRYPTION_MASTER_KEY = os.getenv("ENCRYPTION_MASTER_KEY", "")

# Tree News
TREE_NEWS_WS_URL = os.getenv("TREE_NEWS_WS_URL", "wss://news.treeofalpha.com/ws")
TREE_NEWS_API_KEY = os.getenv("TREE_NEWS_API_KEY", "")

# Binance URLs
BINANCE_SPOT_BASE_URL = os.getenv("BINANCE_SPOT_BASE_URL", "https://api.binance.com")
BINANCE_FUTURES_BASE_URL = os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com")

# Database Path
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/bot.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# WebApp Server Settings
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")


