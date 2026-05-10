const state = {
  report: null,
  config: null,
  settings: null,
  liveState: null,
  brokerOrders: [],
  iciciOrderBook: null,
};

const $ = (id) => document.getElementById(id);

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed: ${response.status}`);
  return data;
}

function setMessage(text, isError = false) {
  const box = $("message");
  box.textContent = text || "";
  box.classList.toggle("hidden", !text);
  box.classList.toggle("error", Boolean(isError));
}

function renderStatus(payload) {
  state.report = payload.report;
  state.config = payload.live_config || payload.config;
  state.settings = payload.settings || {};
  state.liveState = payload.live_state || {};
  state.brokerOrders = payload.broker_orders || [];
  $("dataProvider").value = state.settings.data_provider || "auto";
  renderConfig(state.config || {});
  renderReport(state.report);
  renderIcici(payload.icici || {});
  renderBrokerOrders();
  renderLedger();
}

function renderConfig(config) {
  $("initialCapital").value = config.initial_capital ?? "";
  $("maxPositions").value = config.max_positions ?? "";
  $("symbolsText").value = (config.symbols || []).join(", ");
}

function renderIcici(credentials) {
  if (credentials.api_key && !$("iciciApiKey").value) $("iciciApiKey").value = credentials.api_key;
  if (credentials.api_secret && !$("iciciSecret").value) $("iciciSecret").value = credentials.api_secret;
  if (credentials.session_token && !$("iciciSession").value) $("iciciSession").value = credentials.session_token;
  $("iciciResult").textContent = credentials.configured
    ? `Configured: ${credentials.masked_api_key || "yes"}\nSecret: ${credentials.masked_api_secret || "saved"}\nSession: ${credentials.masked_session_token || "saved"}\n${credentials.path || ""}`
    : "Not configured";
}

function renderReport(report) {
  $("kpiEquity").textContent = money(report?.equity);
  $("kpiCash").textContent = money(report?.cash ?? state.liveState?.cash);
  $("kpiHoldings").textContent = report?.holdings?.length ?? Object.keys(state.liveState?.holdings || {}).length || "-";
  $("kpiRun").textContent = report?.data_as_of ? `${report.run_date || "-"} / data ${report.data_as_of}` : (report?.run_date || "-");
  renderActions(report?.actions || []);
  renderHoldings(report?.holdings || []);
  renderSignals(report?.signal_rows || []);
}

function renderActions(actions) {
  const target = $("actionsList");
  if (!actions.length) {
    target.innerHTML = `<div class="notice">Run signals to generate buy/sell actions.</div>`;
    return;
  }
  const rowsBySymbol = new Map((state.report?.signal_rows || []).map((row) => [row.symbol, row]));
  target.innerHTML = actions.map((action) => {
    const product = action.funding_mode === "mtf" ? "mtf" : "cash";
    return `
      <article class="action-card trade-action" data-action-id="${escapeAttr(action.id || "")}">
        <div>
          <strong class="${action.side === "BUY" ? "side-buy" : "side-sell"}">${escapeHtml(action.side)} ${escapeHtml(action.symbol)}</strong>
          <span>${escapeHtml(action.reason || "")}${sourceSummary(rowsBySymbol.get(action.symbol))}</span>
        </div>
        <div class="action-controls">
          <label>Qty<input class="action-qty" inputmode="numeric" value="${escapeAttr(action.shares || 0)}"></label>
          <label>Limit<input class="action-price" inputmode="decimal" value="${escapeAttr(Number(action.price || 0).toFixed(2))}"></label>
          <label>Product
            <select class="action-product">
              <option value="cash" ${product === "cash" ? "selected" : ""}>Cash</option>
              <option value="mtf" ${product === "mtf" ? "selected" : ""}>MTF</option>
            </select>
          </label>
          <label class="check-label mini-check"><input class="action-book" type="checkbox" checked>Book</label>
        </div>
        <div class="action-buttons">
          <button type="button" data-preview-order>Preview</button>
          <button class="primary" type="button" data-place-order>Place</button>
          <button type="button" data-book-ledger>Book Ledger</button>
        </div>
        <strong class="value">${money(action.value)}</strong>
      </article>
    `;
  }).join("");
}

function renderBrokerOrders() {
  const rows = state.brokerOrders || [];
  $("brokerOrdersBody").innerHTML = rows.length ? rows.slice().reverse().map((row) => `
    <tr>
      <td>${escapeHtml(row.created_at || "")}</td>
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.side || "")}</td>
      <td>${escapeHtml(row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td><span class="status-pill ${row.ok ? "ok" : "bad"}">${row.dry_run ? "Preview" : (row.ok ? "Success" : "Failed")}</span></td>
      <td>${escapeHtml(row.broker_order_id || "")}</td>
      <td>${escapeHtml(row.message || "")}</td>
    </tr>
  `).join("") : `<tr><td colspan="9">No broker orders recorded.</td></tr>`;
}

function renderHoldings(reportHoldings) {
  const reportBySymbol = new Map((reportHoldings || []).map((row) => [row.symbol, row]));
  const holdings = Object.values(state.liveState?.holdings || {});
  $("holdingsBody").innerHTML = holdings.length ? holdings.map((holding) => holdingRow(holding, reportBySymbol.get(holding.symbol))).join("") : `<tr><td colspan="9">No strategy holdings.</td></tr>`;
}

function holdingRow(holding = {}, report = {}) {
  const mode = holding.funding_mode || report.funding_mode || "delivery";
  return `
    <tr class="holding-row">
      <td><input class="holding-symbol" value="${escapeAttr(holding.symbol || "")}"></td>
      <td><input class="holding-shares" inputmode="numeric" value="${escapeAttr(holding.shares || "")}"></td>
      <td><input class="holding-entry" inputmode="decimal" value="${escapeAttr(holding.entry_price || "")}"></td>
      <td><input class="holding-date" value="${escapeAttr(holding.entry_date || "")}"></td>
      <td>
        <select class="holding-mode">
          <option value="delivery" ${mode !== "mtf" ? "selected" : ""}>Delivery</option>
          <option value="mtf" ${mode === "mtf" ? "selected" : ""}>MTF</option>
        </select>
      </td>
      <td><input class="holding-loan" inputmode="decimal" value="${escapeAttr(holding.mtf_loan || 0)}"></td>
      <td>${money(report.last_price)}</td>
      <td>${money(report.unrealized_profit)}</td>
      <td><button type="button" data-remove-row>Remove</button></td>
    </tr>
  `;
}

function renderLedger() {
  const trades = state.liveState?.trades || [];
  $("ledgerBody").innerHTML = trades.length ? trades.map((trade) => ledgerRow(trade)).join("") : `<tr><td colspan="9">No booked orders.</td></tr>`;
}

function ledgerRow(trade = {}) {
  const side = String(trade.side || "BUY").toUpperCase();
  const mode = trade.funding_mode || "delivery";
  return `
    <tr class="ledger-row" data-trade-id="${escapeAttr(trade.id || "")}">
      <td><input class="ledger-date" value="${escapeAttr(trade.signal_date || trade.date || "")}"></td>
      <td>
        <select class="ledger-side">
          <option value="BUY" ${side === "BUY" ? "selected" : ""}>BUY</option>
          <option value="SELL" ${side === "SELL" ? "selected" : ""}>SELL</option>
        </select>
      </td>
      <td><input class="ledger-symbol" value="${escapeAttr(trade.symbol || "")}"></td>
      <td><input class="ledger-shares" inputmode="numeric" value="${escapeAttr(trade.shares || "")}"></td>
      <td><input class="ledger-price" inputmode="decimal" value="${escapeAttr(trade.price || "")}"></td>
      <td>
        <select class="ledger-mode">
          <option value="delivery" ${mode !== "mtf" ? "selected" : ""}>Delivery</option>
          <option value="mtf" ${mode === "mtf" ? "selected" : ""}>MTF</option>
        </select>
      </td>
      <td><input class="ledger-broker-id" value="${escapeAttr(trade.broker_order_id || "")}"></td>
      <td><input class="ledger-reason" value="${escapeAttr(trade.reason || "manual")}"></td>
      <td><button type="button" data-remove-row>Remove</button></td>
    </tr>
  `;
}

function renderSignals(rows) {
  $("signalsBody").innerHTML = rows.length ? rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.symbol)}</td>
      <td>${escapeHtml(row.signal_source || "")}</td>
      <td>${escapeHtml(row.signal_label || "")}</td>
      <td>${escapeHtml(row.source_date || "")} ${money(row.source_price)} / ${money(row.source_ema)}</td>
      <td>${money(row.price)}</td>
      <td>${escapeHtml(row.last_signal || "")} ${escapeHtml(row.last_signal_date || "")}</td>
      <td>${pct(row.ath_distance_pct)}</td>
      <td>${row.is_held ? "Yes" : ""}</td>
    </tr>
  `).join("") : `<tr><td colspan="8">Run signals to populate this table.</td></tr>`;
}

function sourceSummary(row) {
  if (!row) return "";
  const source = row.signal_source ? ` | source ${row.signal_source}` : "";
  const sourceDate = row.source_date ? ` ${row.source_date}` : "";
  const sourceValues = row.source_price && row.source_ema ? ` ${money(row.source_price)}/${money(row.source_ema)}` : "";
  return `${source}${sourceDate}${sourceValues}`;
}

function actionPayload(card, dryRun) {
  return {
    action_id: card.dataset.actionId,
    quantity: card.querySelector(".action-qty").value,
    price: card.querySelector(".action-price").value,
    product: card.querySelector(".action-product").value,
    dry_run: dryRun,
    book_on_success: card.querySelector(".action-book").checked,
  };
}

async function placeActionOrder(card, dryRun) {
  if (!dryRun && !confirm("Place this ICICI order?")) return;
  $("orderResult").textContent = dryRun ? "Preparing preview..." : "Placing broker order...";
  const payload = await api("/api/icici/action-order", {
    method: "POST",
    body: JSON.stringify(actionPayload(card, dryRun)),
  });
  $("orderResult").textContent = JSON.stringify(payload.order, null, 2);
  state.brokerOrders = payload.broker_orders || state.brokerOrders;
  if (payload.state) state.liveState = payload.state;
  renderBrokerOrders();
  renderHoldings(state.report?.holdings || []);
  renderLedger();
  setMessage(dryRun ? "Order preview ready." : "Broker order request completed.");
}

async function bookAction(card) {
  const payload = actionPayload(card, true);
  const response = await api("/api/live/book-action", {
    method: "POST",
    body: JSON.stringify({
      action_id: payload.action_id,
      quantity: payload.quantity,
      price: payload.price,
      product: payload.product,
    }),
  });
  state.liveState = response.state;
  renderHoldings(state.report?.holdings || []);
  renderLedger();
  setMessage("Action booked in the strategy ledger.");
}

function serializeHoldings() {
  const rows = [...document.querySelectorAll(".holding-row")];
  return rows.map((row) => ({
    symbol: row.querySelector(".holding-symbol").value,
    shares: row.querySelector(".holding-shares").value,
    entry_price: row.querySelector(".holding-entry").value,
    entry_date: row.querySelector(".holding-date").value,
    funding_mode: row.querySelector(".holding-mode").value,
    mtf_loan: row.querySelector(".holding-loan").value,
  })).filter((row) => row.symbol.trim());
}

function serializeLedger() {
  const rows = [...document.querySelectorAll(".ledger-row")];
  return rows.map((row) => ({
    id: row.dataset.tradeId,
    date: row.querySelector(".ledger-date").value,
    signal_date: row.querySelector(".ledger-date").value,
    side: row.querySelector(".ledger-side").value,
    symbol: row.querySelector(".ledger-symbol").value,
    shares: row.querySelector(".ledger-shares").value,
    price: row.querySelector(".ledger-price").value,
    funding_mode: row.querySelector(".ledger-mode").value,
    broker_order_id: row.querySelector(".ledger-broker-id").value,
    reason: row.querySelector(".ledger-reason").value,
  })).filter((row) => row.symbol.trim());
}

async function saveLiveState({ holdings, trades } = {}) {
  const payload = {
    cash: state.liveState?.cash ?? state.report?.cash ?? 0,
    holdings: holdings ?? serializeHoldings(),
    trades: trades ?? serializeLedger(),
  };
  const response = await api("/api/live/state", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.liveState = response.state;
  renderHoldings(state.report?.holdings || []);
  renderLedger();
  setMessage("Strategy ledger saved.");
}

async function refreshBrokerOrderBook() {
  $("orderBookStatus").textContent = "Loading...";
  const payload = await api("/api/icici/order/book");
  state.iciciOrderBook = payload.orders;
  $("orderResult").textContent = JSON.stringify(payload.orders, null, 2);
  $("orderBookStatus").textContent = "Broker book loaded";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

async function load() {
  const payload = await api("/api/status");
  renderStatus(payload);
}

$("runSignals").addEventListener("click", async () => {
  setMessage("Running live signals...");
  try {
    const payload = await api("/api/live/run", {
      method: "POST",
      body: JSON.stringify({
        data_provider: $("dataProvider").value,
        price_mode: $("priceMode").value,
      }),
    });
    state.report = payload.report;
    renderReport(payload.report);
    setMessage("Live signal run completed.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("refreshOrderBook").addEventListener("click", () => {
  refreshBrokerOrderBook().catch((error) => setMessage(error.message, true));
});

$("clearLedger").addEventListener("click", async () => {
  if (!confirm("Clear the local strategy ledger?")) return;
  try {
    const payload = await api("/api/live/clear", { method: "POST", body: JSON.stringify({}) });
    state.liveState = payload.state;
    renderReport(null);
    renderLedger();
    setMessage("Ledger cleared.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("configForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Saving configuration...");
  try {
    const payload = await api("/api/live/config", {
      method: "POST",
      body: JSON.stringify({
        initial_capital: $("initialCapital").value,
        max_positions: $("maxPositions").value,
        symbols: $("symbolsText").value,
        data_provider: $("dataProvider").value,
      }),
    });
    state.config = payload.config;
    state.settings = payload.settings;
    renderConfig(payload.config);
    setMessage("Configuration saved.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("openIciciLogin").addEventListener("click", async () => {
  try {
    const payload = await api("/api/icici/login-url", {
      method: "POST",
      body: JSON.stringify({ api_key: $("iciciApiKey").value }),
    });
    window.open(payload.url, "_blank", "noopener");
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("iciciForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("iciciResult").textContent = "Testing...";
  try {
    const payload = await api("/api/icici/session", {
      method: "POST",
      body: JSON.stringify({
        api_key: $("iciciApiKey").value,
        api_secret: $("iciciSecret").value,
        session_token: $("iciciSession").value,
        stock_code: $("iciciStock").value,
      }),
    });
    $("iciciResult").textContent = JSON.stringify(payload.test, null, 2);
  } catch (error) {
    $("iciciResult").textContent = error.message;
  }
});

$("testIciciQuote").addEventListener("click", async () => {
  $("iciciResult").textContent = "Testing...";
  try {
    const payload = await api("/api/icici/test", {
      method: "POST",
      body: JSON.stringify({ stock_code: $("iciciStock").value }),
    });
    $("iciciResult").textContent = JSON.stringify(payload.test, null, 2);
  } catch (error) {
    $("iciciResult").textContent = error.message;
  }
});

$("actionsList").addEventListener("click", (event) => {
  const card = event.target.closest(".trade-action");
  if (!card) return;
  if (event.target.matches("[data-preview-order]")) {
    placeActionOrder(card, true).catch((error) => setMessage(error.message, true));
  }
  if (event.target.matches("[data-place-order]")) {
    placeActionOrder(card, false).catch((error) => setMessage(error.message, true));
  }
  if (event.target.matches("[data-book-ledger]")) {
    bookAction(card).catch((error) => setMessage(error.message, true));
  }
});

document.body.addEventListener("click", (event) => {
  if (event.target.matches("[data-remove-row]")) {
    event.target.closest("tr")?.remove();
  }
});

$("addHolding").addEventListener("click", () => {
  $("holdingsBody").insertAdjacentHTML("beforeend", holdingRow({ entry_date: new Date().toISOString().slice(0, 10), funding_mode: "delivery" }, {}));
});

$("saveHoldings").addEventListener("click", () => {
  saveLiveState({ holdings: serializeHoldings() }).catch((error) => setMessage(error.message, true));
});

$("addLedgerTrade").addEventListener("click", () => {
  $("ledgerBody").insertAdjacentHTML("beforeend", ledgerRow({ date: new Date().toISOString().slice(0, 10), side: "BUY", funding_mode: "delivery", reason: "manual" }));
});

$("saveLedger").addEventListener("click", () => {
  saveLiveState({ trades: serializeLedger() }).catch((error) => setMessage(error.message, true));
});

load().catch((error) => setMessage(error.message, true));
