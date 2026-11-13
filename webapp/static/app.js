// The Capo Terminal Engine
const tg = window.Telegram?.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

let currentUser = null;
const initData = tg?.initData || "test_user_123456789";

// Haptic feedback
function haptic(type = "light") {
  try {
    if (tg?.HapticFeedback) {
      if (type === "impact") tg.HapticFeedback.impactOccurred("medium");
      else if (type === "success") tg.HapticFeedback.notificationOccurred("success");
      else if (type === "error") tg.HapticFeedback.notificationOccurred("error");
      else tg.HapticFeedback.selectionChanged();
    }
  } catch (e) {}
}

// Toast popup
function showToast(msg) {
  const toast = document.getElementById("terminal-toast");
  toast.textContent = msg;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 2500);
}

// Authenticated API request
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${initData}`,
    ...(options.headers || {})
  };
  const resp = await fetch(path, { ...options, headers });
  return await resp.json();
}

// Navigation Tabs
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    haptic("selection");
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
    
    btn.classList.add("active");
    const target = btn.dataset.tab;
    document.getElementById(target).classList.add("active");

    if (target === "tab-logs") {
      loadLogs();
      loadListings();
    }
  });
});

// Load and Render User State
async function loadUserData() {
  try {
    const res = await api("/api/user");
    if (!res.success) {
      showToast(res.error || "Failed to load state");
      return;
    }
    currentUser = res.user;
    renderTerminal();
  } catch (e) {
    showToast("Connection to backend failed");
  }
}

function renderTerminal() {
  const u = currentUser;
  document.getElementById("user-display").textContent = `@${u.username || u.telegram_id}`;

  // Power Switch & Status Banner
  const powerSwitch = document.getElementById("bot-power-switch");
  powerSwitch.checked = u.is_active;
  const masterTitle = document.getElementById("master-status-text");
  const pill = document.getElementById("terminal-state-pill");
  const radar = document.getElementById("radar-light");

  if (u.is_active) {
    masterTitle.textContent = "ENGINE ARMED 🟢";
    masterTitle.className = "master-title active";
    pill.textContent = "SNIPING ACTIVE";
    pill.className = "live-pill active";
    radar.className = "status-radar active";
  } else {
    masterTitle.textContent = "SYSTEM PAUSED ⚪";
    masterTitle.className = "master-title";
    pill.textContent = "STANDBY";
    pill.className = "live-pill";
    radar.className = "status-radar";
  }

  // Metric Boxes
  const totalBal = u.total_balance !== undefined ? u.total_balance : u.usdt_balance;
  document.getElementById("box-balance").textContent = `$${totalBal.toFixed(2)}`;
  document.getElementById("box-size").textContent = `$${u.order_amount_usdt.toFixed(2)}`;
  document.getElementById("box-market").textContent = u.trade_mode.toUpperCase();
  document.getElementById("box-timeout").textContent = `${u.max_hold_seconds}s`;

  // API status text
  const apiInd = document.getElementById("api-indicator");
  const apiBadge = document.getElementById("api-status-badge");
  const apiVerified = document.getElementById("api-summary-verified");
  const apiBal = document.getElementById("api-summary-balance");

  if (u.has_api_keys) {
    if (u.api_error) {
      if (apiInd) {
        apiInd.textContent = "API Error ⚠️";
        apiInd.style.color = "#f87171";
      }
      if (apiBadge) {
        apiBadge.textContent = "ERROR ⚠️";
        apiBadge.style.color = "#f87171";
      }
      if (apiVerified) {
        apiVerified.textContent = "FAILED";
        apiVerified.style.color = "#f87171";
      }
      if (apiBal) {
        apiBal.textContent = u.api_error.slice(0, 30);
        apiBal.style.color = "#f87171";
      }
    } else {
      if (apiInd) {
        apiInd.textContent = "API Connected ✔";
        apiInd.style.color = "#ffffff";
      }
      if (apiBadge) {
        apiBadge.textContent = "CONNECTED ✔";
        apiBadge.style.color = "#ffffff";
      }
      if (apiVerified) {
        apiVerified.textContent = "YES";
        apiVerified.style.color = "#ffffff";
      }
      if (apiBal) {
        let detail = "";
        const spotSum = (u.spot_usdt || 0) + (u.spot_usdc || 0);
        const futSum = (u.futures_usdt || 0) + (u.futures_usdc || 0);
        if (spotSum > 0 && futSum > 0) {
          detail = ` (Spot: $${spotSum.toFixed(2)} | Fut: $${futSum.toFixed(2)})`;
        }
        apiBal.textContent = `$${totalBal.toFixed(2)}${detail}`;
        apiBal.style.color = "#ffffff";
      }
    }
  } else {
    if (apiInd) {
      apiInd.textContent = "No API Key ✖";
      apiInd.style.color = "#8e929b";
    }
    if (apiBadge) {
      apiBadge.textContent = "DISCONNECTED";
      apiBadge.style.color = "#8e929b";
    }
    if (apiVerified) {
      apiVerified.textContent = "NO";
    }
    if (apiBal) {
      apiBal.textContent = "--";
    }
  }

  // Ledger Stats
  if (u.stats) {
    document.getElementById("ledger-gross-profit").textContent = `$${u.stats.gross_pnl_usdt.toFixed(2)} USDT`;
    document.getElementById("ledger-platform-fee").textContent = `$${u.stats.platform_fee_accrued_usdt.toFixed(2)} USDT`;
    document.getElementById("ledger-net-profit").textContent = `$${u.stats.net_user_profit_usdt.toFixed(2)} USDT`;
    document.getElementById("ledger-win-rate").textContent = `${u.stats.win_rate}% (${u.stats.total_trades} Trades)`;
  }

  // Strategy Sliders & Labels
  document.getElementById("slider-tp").value = u.tp_percent;
  document.getElementById("label-tp").textContent = `+${u.tp_percent}%`;

  document.getElementById("slider-sl").value = u.sl_percent;
  document.getElementById("label-sl").textContent = `-${u.sl_percent}%`;

  document.getElementById("slider-timeout").value = u.max_hold_seconds;
  document.getElementById("label-timeout").textContent = `${u.max_hold_seconds}s`;

  // Market Segmented Control
  document.querySelectorAll("#market-selector .seg-btn").forEach(b => {
    if (b.dataset.market === u.trade_mode) b.classList.add("active");
    else b.classList.remove("active");
  });

  const levBlock = document.getElementById("leverage-block");
  if (u.trade_mode === "futures") {
    levBlock.style.display = "block";
    document.querySelectorAll("#leverage-selector .seg-btn").forEach(b => {
      if (parseInt(b.dataset.lev) === u.futures_leverage) b.classList.add("active");
      else b.classList.remove("active");
    });
  } else {
    levBlock.style.display = "none";
  }

  // Order Amount Chips
  document.querySelectorAll("#amount-chips .chip").forEach(c => {
    if (parseFloat(c.dataset.val) === u.order_amount_usdt) c.classList.add("active");
    else c.classList.remove("active");
  });
}

// Power Toggle Listener
document.getElementById("bot-power-switch").addEventListener("change", async (e) => {
  haptic("impact");
  const is_active = e.target.checked ? 1 : 0;
  
  if (is_active && !currentUser.has_api_keys) {
    showToast("Connect your Binance API Key first!");
    e.target.checked = false;
    return;
  }

  await api("/api/user/settings", {
    method: "POST",
    body: JSON.stringify({ is_active })
  });
  currentUser.is_active = is_active;
  renderTerminal();
  showToast(is_active ? "Execution Engine ARMED" : "Execution Engine PAUSED");
});

// Quick Market Toggle from Metric Box
document.getElementById("btn-quick-market-toggle").addEventListener("click", async () => {
  haptic("impact");
  const newMode = currentUser.trade_mode === "spot" ? "futures" : "spot";
  await api("/api/user/settings", {
    method: "POST",
    body: JSON.stringify({ trade_mode: newMode })
  });
  currentUser.trade_mode = newMode;
  renderTerminal();
  showToast(`Market switched to ${newMode.toUpperCase()}`);
});

// Strategy: Market Selector
document.querySelectorAll("#market-selector .seg-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    haptic("selection");
    document.querySelectorAll("#market-selector .seg-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentUser.trade_mode = btn.dataset.market;
    document.getElementById("leverage-block").style.display = (currentUser.trade_mode === "futures") ? "block" : "none";
  });
});

// Strategy: Leverage Selector
document.querySelectorAll("#leverage-selector .seg-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    haptic("selection");
    document.querySelectorAll("#leverage-selector .seg-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentUser.futures_leverage = parseInt(btn.dataset.lev);
  });
});

// Strategy: Amount Chips
document.querySelectorAll("#amount-chips .chip").forEach(chip => {
  chip.addEventListener("click", () => {
    haptic("selection");
    document.querySelectorAll("#amount-chips .chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    document.getElementById("input-custom-order-size").value = "";
    currentUser.order_amount_usdt = parseFloat(chip.dataset.val);
  });
});

document.getElementById("input-custom-order-size").addEventListener("input", (e) => {
  const val = parseFloat(e.target.value);
  if (val && val >= 10) {
    document.querySelectorAll("#amount-chips .chip").forEach(c => c.classList.remove("active"));
    currentUser.order_amount_usdt = val;
  }
});

// Sliders live text
document.getElementById("slider-tp").addEventListener("input", (e) => {
  document.getElementById("label-tp").textContent = `+${e.target.value}%`;
});
document.getElementById("slider-sl").addEventListener("input", (e) => {
  document.getElementById("label-sl").textContent = `-${e.target.value}%`;
});
document.getElementById("slider-timeout").addEventListener("input", (e) => {
  document.getElementById("label-timeout").textContent = `${e.target.value}s`;
});

// Save Strategy Button
document.getElementById("btn-save-strategy").addEventListener("click", async () => {
  haptic("impact");
  const payload = {
    trade_mode: currentUser.trade_mode,
    futures_leverage: currentUser.futures_leverage,
    order_amount_usdt: currentUser.order_amount_usdt,
    tp_percent: parseFloat(document.getElementById("slider-tp").value),
    sl_percent: parseFloat(document.getElementById("slider-sl").value),
    max_hold_seconds: parseInt(document.getElementById("slider-timeout").value)
  };

  const res = await api("/api/user/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });

  if (res.success) {
    showToast("Strategy parameters saved ✔");
    loadUserData();
  } else {
    showToast("Error saving strategy");
  }
});

// Connect API Keys
document.getElementById("btn-connect-api").addEventListener("click", async () => {
  const key = document.getElementById("input-api-key").value.trim();
  const secret = document.getElementById("input-api-secret").value.trim();

  if (!key || !secret) {
    showToast("Enter both API Key & Secret");
    return;
  }

  haptic("impact");
  const btn = document.getElementById("btn-connect-api");
  btn.textContent = "VERIFYING WITH BINANCE...";
  btn.disabled = true;

  try {
    const res = await api("/api/user/api-keys", {
      method: "POST",
      body: JSON.stringify({ api_key: key, api_secret: secret })
    });

    if (res.success) {
      showToast("Binance API Connected & Verified ✔");
      document.getElementById("input-api-key").value = "";
      document.getElementById("input-api-secret").value = "";
      loadUserData();
    } else {
      showToast(res.error || "Authentication failed");
    }
  } catch (e) {
    showToast("Connection error");
  } finally {
    btn.textContent = "VALIDATE & CONNECT API";
    btn.disabled = false;
  }
});

// Active Positions Loader & Real-Time Panic Exit
async function loadActivePositions() {
  try {
    const res = await api("/api/trades");
    if (!res.success) return;

    const openTrades = res.trades.filter(t => t.status === "OPEN");
    const container = document.getElementById("active-positions-feed");
    const countTag = document.getElementById("active-count-tag");
    countTag.textContent = `${openTrades.length} OPEN`;

    if (openTrades.length === 0) {
      container.innerHTML = `
        <div class="terminal-empty">
          <div class="empty-icon">⬡</div>
          <div class="empty-title">NO ACTIVE TRADES</div>
          <div class="empty-desc">Engine is monitoring Upbit feed. Orders will appear here upon announcement.</div>
        </div>
      `;
      return;
    }

    container.innerHTML = openTrades.map(t => `
      <div class="trade-card">
        <div class="trade-card-header">
          <div class="trade-pair">${t.symbol} <small style="color:#71717a">(${t.trade_mode.toUpperCase()})</small></div>
          <span class="trade-pnl-pill ${t.pnl_percent >= 0 ? 'profit' : 'loss'}">
            ${t.pnl_percent >= 0 ? '+' : ''}${t.pnl_percent.toFixed(2)}%
          </span>
        </div>
        <div class="trade-stats">
          <div>ENTRY: $${t.buy_price.toFixed(4)}</div>
          <div>MARK: $${(t.current_price || t.buy_price).toFixed(4)}</div>
          <div>SIZE: $${t.usdt_spent.toFixed(2)} USDT</div>
          <div>TYPE: ${t.trade_mode.toUpperCase()}</div>
        </div>
        <button class="btn-panic" onclick="panicClose(${t.id})">
          🚨 SELL AT MARKET (100%)
        </button>
      </div>
    `).join("");
  } catch (e) {}
}

window.panicClose = async function(tradeId) {
  haptic("impact");
  const res = await api("/api/trades/panic-sell", {
    method: "POST",
    body: JSON.stringify({ trade_id: tradeId })
  });

  if (res.success) {
    showToast("Order closed at market ✔");
    loadActivePositions();
  } else {
    showToast(res.error || "Failed to close position");
  }
};

// Listings Banner & Log
async function loadListings() {
  try {
    const res = await api("/api/listings");
    if (!res.success || res.listings.length === 0) return;

    // Latest banner
    const latest = res.listings[0];
    document.getElementById("news-time").textContent = latest.detected_at || "JUST NOW";
    document.getElementById("news-headline").textContent = `[${latest.parsed_coin}] ${latest.raw_title}`;

    // Logs view
    const hist = document.getElementById("listings-history-container");
    hist.innerHTML = res.listings.map(l => `
      <div class="log-row">
        <div>
          <span class="log-coin">${l.parsed_coin}</span>
          <div class="log-meta">${l.raw_title}</div>
        </div>
        <div class="log-meta">${l.detected_at}</div>
      </div>
    `).join("");
  } catch (e) {}
}

async function loadLogs() {
  try {
    const res = await api("/api/trades");
    const container = document.getElementById("trade-ledger-container");
    if (!res.success || res.trades.length === 0) {
      container.innerHTML = `<div class="terminal-empty">No closed trades recorded yet.</div>`;
      return;
    }

    container.innerHTML = res.trades.map(t => `
      <div class="log-row">
        <div>
          <span class="log-coin">${t.symbol} (${t.trade_mode.toUpperCase()})</span>
          <div class="log-meta">Size: $${t.usdt_spent} | Exit: ${t.exit_reason || t.status}${t.fee_usdt > 0 ? ` | Fee (10%): $${t.fee_usdt.toFixed(2)}` : ''}</div>
        </div>
        <div style="font-family: var(--font-mono); font-weight:700; color:${t.pnl_percent >= 0 ? 'var(--pnl-green)' : 'var(--pnl-red)'}">
          ${t.pnl_percent >= 0 ? '+' : ''}${t.pnl_percent.toFixed(2)}% ($${t.pnl_usdt.toFixed(2)})
        </div>
      </div>
    `).join("");
  } catch (e) {}
}

// Startup
loadUserData();
loadActivePositions();
loadListings();
setInterval(loadActivePositions, 2000);
setInterval(loadListings, 5000);
