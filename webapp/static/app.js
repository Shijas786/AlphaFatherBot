// Telegram Web App Client Engine
const tg = window.Telegram?.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

// State
let currentUser = null;
const initData = tg?.initData || "test_user_123456789";

// Haptic feedback helper
function triggerHaptic(type = "light") {
  try {
    if (tg?.HapticFeedback) {
      if (type === "impact") tg.HapticFeedback.impactOccurred("medium");
      else if (type === "success") tg.HapticFeedback.notificationOccurred("success");
      else if (type === "error") tg.HapticFeedback.notificationOccurred("error");
      else tg.HapticFeedback.selectionChanged();
    }
  } catch (e) {}
}

// Show toast helper
function showToast(msg, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.style.borderColor = isError ? "var(--danger)" : "var(--primary)";
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3000);
}

// Authenticated Fetch Wrapper
async function apiFetch(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${initData}`,
    ...(options.headers || {})
  };
  const resp = await fetch(endpoint, { ...options, headers });
  return await resp.json();
}

// Tab Switching
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    triggerHaptic("selection");
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    
    btn.classList.add("active");
    const target = btn.dataset.tab;
    document.getElementById(target).classList.add("active");

    if (target === "tab-history") {
      loadHistory();
      loadListings();
    }
  });
});

// Load User Profile
async function loadUser() {
  try {
    const data = await apiFetch("/api/user");
    if (!data.success) {
      showToast(data.error || "Failed to load user", true);
      return;
    }
    currentUser = data.user;
    renderUser();
  } catch (e) {
    showToast("Server connection error", true);
  }
}

function renderUser() {
  const u = currentUser;
  document.getElementById("user-display").textContent = `@${u.username || u.telegram_id}`;
  
  // Hero Switch
  const activeToggle = document.getElementById("bot-active-toggle");
  activeToggle.checked = u.is_active;
  const heroState = document.getElementById("hero-state-text");
  if (u.is_active) {
    heroState.textContent = "SNIPING ACTIVE 🟢";
    heroState.className = "hero-state active";
    document.getElementById("system-status-badge").textContent = "ACTIVE";
    document.getElementById("system-status-badge").className = "badge badge-active badge-pulse";
  } else {
    heroState.textContent = "PAUSED 🔴";
    heroState.className = "hero-state";
    document.getElementById("system-status-badge").textContent = "PAUSED";
    document.getElementById("system-status-badge").className = "badge";
  }

  // Key Metrics
  document.getElementById("metric-mode").textContent = u.simulation_mode ? "🧪 SIMULATION" : "💰 REAL MONEY";
  document.getElementById("metric-market").textContent = u.trade_mode.toUpperCase();
  document.getElementById("metric-order-size").textContent = `$${u.order_amount_usdt} USDT`;
  document.getElementById("metric-balance").textContent = `$${u.usdt_balance.toFixed(2)} USDT`;

  // Settings Sliders & Labels
  document.getElementById("range-tp").value = u.tp_percent;
  document.getElementById("val-tp").textContent = `+${u.tp_percent}%`;

  document.getElementById("range-sl").value = u.sl_percent;
  document.getElementById("val-sl").textContent = `-${u.sl_percent}%`;

  document.getElementById("range-trailing").value = u.trailing_stop_percent;
  document.getElementById("val-trailing").textContent = `${u.trailing_stop_percent}%`;

  document.getElementById("range-timeout").value = u.max_hold_seconds;
  document.getElementById("val-timeout").textContent = `${u.max_hold_seconds}s`;

  // Pills active state
  updateAmountPills(u.order_amount_usdt);
  updateLeveragePills(u.futures_leverage);

  // API Status box
  const dot = document.querySelector(".status-dot");
  const apiStatusText = document.getElementById("api-status-text");
  if (u.has_api_keys) {
    dot.className = "status-dot connected";
    apiStatusText.textContent = `Binance API Connected ✅ (Balance: $${u.usdt_balance.toFixed(2)} USDT)`;
  } else {
    dot.className = "status-dot";
    apiStatusText.textContent = "No API Key connected yet. Paste keys below.";
  }
}

// Bot Active Toggle Listener
document.getElementById("bot-active-toggle").addEventListener("change", async (e) => {
  const is_active = e.target.checked ? 1 : 0;
  triggerHaptic("impact");
  await apiFetch("/api/user/settings", {
    method: "POST",
    body: JSON.stringify({ is_active })
  });
  currentUser.is_active = is_active;
  renderUser();
});

// Toggle Sim Button
document.getElementById("btn-toggle-sim").addEventListener("click", async () => {
  triggerHaptic("impact");
  const newSim = currentUser.simulation_mode ? 0 : 1;
  await apiFetch("/api/user/settings", {
    method: "POST",
    body: JSON.stringify({ simulation_mode: newSim })
  });
  currentUser.simulation_mode = newSim;
  renderUser();
  showToast(newSim ? "Switched to Simulation Mode" : "Switched to Real Money Mode");
});

// Toggle Market Button
document.getElementById("btn-toggle-market").addEventListener("click", async () => {
  triggerHaptic("impact");
  const newMode = currentUser.trade_mode === "spot" ? "futures" : "spot";
  await apiFetch("/api/user/settings", {
    method: "POST",
    body: JSON.stringify({ trade_mode: newMode })
  });
  currentUser.trade_mode = newMode;
  renderUser();
  showToast(`Switched market to ${newMode.toUpperCase()}`);
});

// Amount pills
function updateAmountPills(amt) {
  document.querySelectorAll("#amount-pills .pill-btn").forEach(p => {
    if (parseFloat(p.dataset.amt) === amt) p.classList.add("active");
    else p.classList.remove("active");
  });
}

document.querySelectorAll("#amount-pills .pill-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    triggerHaptic("selection");
    document.querySelectorAll("#amount-pills .pill-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("input-custom-amount").value = "";
    currentUser.order_amount_usdt = parseFloat(btn.dataset.amt);
  });
});

document.getElementById("input-custom-amount").addEventListener("input", (e) => {
  const val = parseFloat(e.target.value);
  if (val && val >= 10) {
    document.querySelectorAll("#amount-pills .pill-btn").forEach(b => b.classList.remove("active"));
    currentUser.order_amount_usdt = val;
  }
});

// Leverage pills
function updateLeveragePills(lev) {
  document.querySelectorAll("#leverage-pills .pill-btn").forEach(p => {
    if (parseInt(p.dataset.lev) === lev) p.classList.add("active");
    else p.classList.remove("active");
  });
}

document.querySelectorAll("#leverage-pills .pill-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    triggerHaptic("selection");
    document.querySelectorAll("#leverage-pills .pill-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentUser.futures_leverage = parseInt(btn.dataset.lev);
  });
});

// Slider Input listeners
document.getElementById("range-tp").addEventListener("input", (e) => {
  document.getElementById("val-tp").textContent = `+${e.target.value}%`;
});
document.getElementById("range-sl").addEventListener("input", (e) => {
  document.getElementById("val-sl").textContent = `-${e.target.value}%`;
});
document.getElementById("range-trailing").addEventListener("input", (e) => {
  document.getElementById("val-trailing").textContent = `${e.target.value}%`;
});
document.getElementById("range-timeout").addEventListener("input", (e) => {
  document.getElementById("val-timeout").textContent = `${e.target.value}s`;
});

// Save Settings Button
document.getElementById("btn-save-settings").addEventListener("click", async () => {
  triggerHaptic("impact");
  const payload = {
    order_amount_usdt: currentUser.order_amount_usdt,
    futures_leverage: currentUser.futures_leverage,
    tp_percent: parseFloat(document.getElementById("range-tp").value),
    sl_percent: parseFloat(document.getElementById("range-sl").value),
    trailing_stop_percent: parseFloat(document.getElementById("range-trailing").value),
    max_hold_seconds: parseInt(document.getElementById("range-timeout").value)
  };

  const res = await apiFetch("/api/user/settings", {
    method: "POST",
    body: JSON.stringify(payload)
  });

  if (res.success) {
    showToast("Strategy settings saved!");
    loadUser();
  } else {
    showToast("Error saving settings", true);
  }
});

// Connect Binance API Keys
document.getElementById("btn-save-api").addEventListener("click", async () => {
  const key = document.getElementById("input-api-key").value.trim();
  const secret = document.getElementById("input-api-secret").value.trim();

  if (!key || !secret) {
    showToast("Please enter both Key and Secret", true);
    return;
  }

  triggerHaptic("impact");
  const btn = document.getElementById("btn-save-api");
  btn.textContent = "🔄 Validating with Binance...";
  btn.disabled = true;

  try {
    const res = await apiFetch("/api/user/api-keys", {
      method: "POST",
      body: JSON.stringify({ api_key: key, api_secret: secret })
    });

    if (res.success) {
      showToast("Binance API Connected successfully!");
      document.getElementById("input-api-key").value = "";
      document.getElementById("input-api-secret").value = "";
      loadUser();
    } else {
      showToast(res.error || "Binance authentication failed", true);
    }
  } catch (e) {
    showToast("Error verifying keys", true);
  } finally {
    btn.textContent = "🔗 Validate & Connect API";
    btn.disabled = false;
  }
});

// Active Positions & Panic Sell
async function loadActivePositions() {
  try {
    const res = await apiFetch("/api/trades");
    if (!res.success) return;

    const openTrades = res.trades.filter(t => t.status === "OPEN");
    const container = document.getElementById("active-positions-container");
    const countBadge = document.getElementById("active-pos-count");
    countBadge.textContent = `${openTrades.length} OPEN`;

    if (openTrades.length === 0) {
      container.innerHTML = `<div class="empty-state">No open positions. Ready to snipe listings.</div>`;
      return;
    }

    container.innerHTML = openTrades.map(t => `
      <div class="pos-card">
        <div class="pos-header">
          <div class="pos-symbol">${t.symbol} <small>(${t.trade_mode.toUpperCase()})</small></div>
          <span class="pnl-badge ${t.pnl_percent >= 0 ? 'pnl-green' : 'pnl-red'}">
            ${t.pnl_percent >= 0 ? '+' : ''}${t.pnl_percent.toFixed(2)}%
          </span>
        </div>
        <div class="pos-details">
          <div>Entry: $${t.buy_price.toFixed(4)}</div>
          <div>Size: $${t.usdt_spent.toFixed(2)} USDT</div>
        </div>
        <button class="btn btn-danger btn-block btn-sm" onclick="panicSell(${t.id})">
          🚨 PANIC SELL 100% NOW
        </button>
      </div>
    `).join("");
  } catch (e) {}
}

window.panicSell = async function(tradeId) {
  triggerHaptic("impact");
  const res = await apiFetch("/api/trades/panic-sell", {
    method: "POST",
    body: JSON.stringify({ trade_id: tradeId })
  });

  if (res.success) {
    showToast("Position closed at market!");
    loadActivePositions();
  } else {
    showToast(res.error || "Panic sell failed", true);
  }
};

// Activity & History Loaders
async function loadListings() {
  const container = document.getElementById("listings-feed-container");
  try {
    const res = await apiFetch("/api/listings");
    if (!res.success || res.listings.length === 0) {
      container.innerHTML = `<div class="empty-state">No listings detected yet. Waiting for Upbit news...</div>`;
      return;
    }
    container.innerHTML = res.listings.map(l => `
      <div class="feed-item">
        <div class="feed-header">
          <span class="feed-coin">${l.parsed_coin}</span>
          <small>${l.detected_at}</small>
        </div>
        <div>${l.raw_title}</div>
      </div>
    `).join("");
  } catch (e) {}
}

async function loadHistory() {
  const container = document.getElementById("trade-history-container");
  try {
    const res = await apiFetch("/api/trades");
    if (!res.success || res.trades.length === 0) {
      container.innerHTML = `<div class="empty-state">No completed trades yet.</div>`;
      return;
    }
    container.innerHTML = res.trades.map(t => `
      <div class="feed-item">
        <div class="feed-header">
          <strong>${t.symbol} (${t.trade_mode.toUpperCase()})</strong>
          <span class="${t.pnl_percent >= 0 ? 'val-tag' : 'val-tag danger'}">
            ${t.pnl_percent >= 0 ? '+' : ''}${t.pnl_percent.toFixed(1)}% ($${t.pnl_usdt.toFixed(2)})
          </span>
        </div>
        <div>Exit: ${t.exit_reason || t.status} | Size: $${t.usdt_spent}</div>
      </div>
    `).join("");
  } catch (e) {}
}

// Initial Boot & Poller
loadUser();
loadActivePositions();
setInterval(loadActivePositions, 3000);

