# ⚡ Upbit Listing Sniper & Momentum Trading Bot

An ultra-low latency Telegram-controlled crypto trading bot designed to detect new token listing announcements on **Upbit** in real-time and instantly execute market buy orders on **Binance** (Spot & USDT-M Futures) for multiple users concurrently.

---

## 🚀 Key Features

* **Sub-Second News Ingestion:**
  * **Capo Core WebSocket Stream:** Proprietary ultra-low latency push stream with instant Upbit alert filtering.
  * **Redundant Upbit Notice Scraper:** Fallback poller querying `api-manager.upbit.com` every 1.5s to ensure zero missed announcements.
* **0ms Symbol Resolver:** Pre-caches all Binance Spot & Futures trading pairs and precision rules in RAM at boot.
* **Spot & Futures Market Selection:** Users can choose whether they want to buy on **Binance Spot** or **Binance Futures** (with customizable leverage from 2x to 10x).
* **Multi-User Concurrent Execution:** Dispatches parallel async buy orders for all registered and active users using `asyncio.gather`.
* **🧠 Smart Exit Strategy:**
  * **Trailing Profit Lock:** Tracks peak price; arms when profit reaches e.g. `+8%`, and triggers market sell if price pulls back by e.g. `4%` from the peak.
  * **Hard Take Profit & Stop Loss:** Instant exit if price spikes to moon target (e.g. `+20%`) or dumps (e.g. `-5%`).
  * **Max Hold Timeout:** Auto-sells at market after $N$ seconds (e.g. 60s, 90s, 120s) to avoid holding bags after the pump fades.
  * **🚨 1-Click Panic Sell:** Instant emergency button delivered with every buy alert and in the Mini App.
* **📱 Telegram Mini App (Web Dashboard):** A native, responsive in-Telegram WebApp for managing settings, viewing active positions, and clicking Panic Sell.
* **🧪 Simulation / Paper Trading Mode:** Test the bot in real-time without risking real funds.
* **🔒 Military-Grade Key Security:** User Binance API credentials are encrypted at rest using **AES-256-GCM** (Fernet authenticated encryption).
* **👮 Admin Suite:**
  * `/simulate_listing <COIN>`: Test-fire an announcement for any coin (e.g. `/simulate_listing DRIFT`) to test the entire pipeline end-to-end.
  * `/broadcast <message>`: Send announcements to all registered users.
  * `/stats`: Live system and user metrics.

---

## 📁 Project Architecture

```
├── config.py                 # Environment variables and configurations
├── main.py                   # System entry point running listeners and Telegram bot
├── database/
│   ├── db.py                 # SQLite async database operations
│   └── encryption.py         # AES-256 Fernet key encryption/decryption
├── services/
│   ├── tree_news_listener.py # Tree News WebSocket stream client & regex parser
│   ├── upbit_notice_scraper.py # Redundant Upbit official notice scraper
│   ├── symbol_cache.py       # In-memory Binance symbol & precision cache
│   ├── binance_service.py    # Binance Spot & Futures REST API execution
│   ├── position_tracker.py   # Smart exit engine (Trailing SL, TP, Timeout, Panic)
│   └── trade_dispatcher.py   # Multi-user parallel order dispatcher
├── webapp/                   # Telegram Mini App
│   ├── auth.py               # Telegram WebApp initData HMAC validation
│   ├── routes.py             # REST API routes (user, settings, trades, panic sell)
│   ├── server.py             # aiohttp async web server
│   └── static/               # Frontend SPA (HTML, CSS, JS)
├── bot/
│   ├── telegram_bot.py       # Telegram application setup & notification callbacks
│   ├── keyboards.py          # Interactive Telegram menus & inline buttons
│   └── handlers/
│       ├── start.py          # /start command & dashboard view
│       ├── settings.py       # Strategy customization menus
│       ├── api_keys.py       # Secure API key connection & validation
│       ├── trades.py         # Trade history & manual panic sell
│       └── admin.py          # Admin test simulation & broadcast
├── requirements.txt
├── .env.example
└── .env
```

---

## 📱 Telegram Mini App (TMA) Setup

The bot comes with an integrated, modern **Telegram Mini App** built into the server!

### How to Enable in Telegram:
1. Open [@BotFather](https://t.me/BotFather) on Telegram.
2. Send `/mybots` -> Select your bot -> **Bot Settings** -> **Menu Button** -> **Configure menu button**.
3. Set the URL to your bot's HTTPS WebApp URL (e.g. `https://your-domain.com` or via Cloudflare Tunnel / ngrok: `https://xxxx.ngrok-free.app`).
4. In `.env`, set:
   ```ini
   WEBAPP_URL=https://your-domain.com
   ```
5. When users open the bot or click `🚀 Open Sniper Mini App` or the menu button, the native Mini App opens with:
   * **Live Dashboard:** Toggle bot ON/OFF, switch between Real/Simulation mode, view live Binance balance.
   * **Active Positions:** See real-time PnL, open trades, and click **🚨 PANIC SELL 100% NOW**.
   * **Strategy Controls:** Adjust order size, Spot vs Futures, Take Profit %, Stop Loss %, Trailing Stop %, and Hold Timeout.
   * **Binance API:** Connect & validate API keys with instant balance detection.
   * **Live Activity:** Real-time Upbit listing notices feed & completed trade history.

---

## 🛠️ Setup & Installation

### 1. Requirements
* macOS / Linux / Windows
* Python 3.9+

### 2. Configure Environment (`.env`)
Open `.env` and fill in your credentials:

```ini
# Telegram Bot Token (obtain from @BotFather on Telegram)
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Your numeric Telegram user ID (from @userinfobot)
ADMIN_USER_ID=123456789

# Master encryption key (pre-generated)
ENCRYPTION_MASTER_KEY=5x7leB-lrBlllbp0BV2o7oVIa4JjfV8dmmwwsLAF39U=

# Telegram Mini App URL (set when hosting with HTTPS / ngrok)
WEBAPP_URL=https://your-domain.com
```

### 3. Run the Bot
```bash
# Activate the virtual environment
source .venv/bin/activate

# Start the bot
python main.py
```

---

## 🤖 Using the Telegram Bot

1. Open your Telegram bot and send `/start`.
2. **Dashboard Controls:**
   * **🚀 Open Sniper Mini App:** Launches the interactive WebApp dashboard inside Telegram!
   * **🟢 Status:** Toggle the bot between `ACTIVE` and `PAUSED`.
   * **🧪 Mode:** Toggle between `SIMULATION (Paper Trading)` and `REAL FUNDS`.
   * **📈 Market:** Switch between `SPOT` and `FUTURES`.
   * **🔑 Connect Binance API:** Connect your API key securely (ensure withdrawals are disabled).
   * **⚙️ Strategy Settings:** Configure order size ($25 - $1000), Take Profit %, Stop Loss %, Trailing Pullback %, and Timeout.
   * **📊 Trade History:** View recent trades, fill prices, and realized PnL.

3. **Admin Testing:**
   Send `/simulate_listing DRIFT` or `/simulate_listing TIA` to test how orders execute, notifications fire, and the Smart Exit tracks live prices!
