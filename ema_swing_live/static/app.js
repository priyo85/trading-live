const state = {
  report: null,
  config: null,
  settings: null,
  liveState: null,
  brokerOrders: [],
  iciciOrderBook: null,
  iciciPortfolioRows: [],
  iciciTradeRows: [],
  dhanPortfolioRows: [],
  dhanTradeRows: [],
  dhanOrderRows: [],
  logSettings: {},
  sync: {},
};

const $ = (id) => document.getElementById(id);

function on(id, eventName, handler) {
  const node = $(id);
  if (node) node.addEventListener(eventName, handler);
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function optionalPct(value) {
  const text = pct(value);
  return text || "-";
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
  state.logSettings = payload.log_settings || {};
  state.sync = payload.sync || {};
  $("dataProvider").value = state.settings.data_provider || "auto";
  renderConfig(state.config || {});
  renderReport(state.report);
  renderIcici(payload.icici || {});
  renderDhan(payload.dhan || {});
  renderBrokerOrders();
  renderLedger();
  renderLogSettings();
  renderSyncStatus();
  checkIciciConnection();
  defaultDates();
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
    : "Not configured. Enter API key/secret, use Open Login to generate a session token, then Save & Test.";
}

function renderDhan(credentials) {
  if (credentials.client_id && !$("dhanClientId").value) $("dhanClientId").value = credentials.client_id;
  if (credentials.access_token && !$("dhanAccessToken").value) $("dhanAccessToken").value = credentials.access_token;
  const badge = $("dhanConnection");
  if (!badge) return;
  badge.classList.toggle("ok", Boolean(credentials.configured));
  badge.classList.toggle("bad", !credentials.configured);
  badge.textContent = credentials.configured ? "Configured" : "Not configured";
  badge.title = credentials.path || "";
}

function renderSyncStatus() {
  const status = $("syncStatus");
  if (!status) return;
  if ($("syncRemoteUrl") && state.sync.remote_url && !$("syncRemoteUrl").value) {
    $("syncRemoteUrl").value = state.sync.remote_url;
  }
  status.textContent = state.sync.remote_configured
    ? `Configured: ${state.sync.remote_url || "remote"}`
    : "Optional local to EC2 pull";
}

function defaultDates() {
  const today = new Date().toISOString().slice(0, 10);
  const start = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  ["iciciFromDate", "dhanFromDate"].forEach((id) => { if ($(id) && !$(id).value) $(id).value = start; });
  ["iciciToDate", "dhanToDate"].forEach((id) => { if ($(id) && !$(id).value) $(id).value = today; });
}

function setIciciConnection(connected, detail = "") {
  const badge = $("iciciConnection");
  if (!badge) return;
  badge.classList.toggle("ok", Boolean(connected));
  badge.classList.toggle("bad", !connected);
  badge.textContent = connected ? "Connected" : "Session needed";
  badge.title = detail || badge.textContent;
}

async function checkIciciConnection() {
  const badge = $("iciciConnection");
  if (!badge) return;
  badge.textContent = "Checking...";
  try {
    const payload = await api(`/api/icici/connection?stock_code=${encodeURIComponent($("iciciStock")?.value || "GOLDEX")}`);
    setIciciConnection(payload.connected, payload.error || payload.test?.time || "");
    if (!payload.connected && payload.error) {
      $("iciciResult").textContent = `Session needed: ${payload.error}\nUse Open Login to generate a new Breeze session token.`;
    }
  } catch (error) {
    setIciciConnection(false, error.message);
  }
}

function renderReport(report) {
  const stateHoldings = state.liveState?.holdings || {};
  const stateHoldingCount = Object.keys(stateHoldings).length;
  const reportHoldingsBySymbol = marketRowsBySymbol(report);
  const ledgerCash = Number(state.liveState?.cash);
  const displayCash = Number.isFinite(ledgerCash) ? ledgerCash : Number(report?.cash ?? state.config?.initial_capital ?? 0);
  const holdingsNetValue = Object.values(stateHoldings).reduce((total, holding) => {
    const reportHolding = reportHoldingsBySymbol.get(holding.symbol) || {};
    const price = Number(reportHolding.last_price ?? holding.entry_price ?? 0);
    const shares = Number(holding.shares || 0);
    const mtfLoan = Number(holding.mtf_loan || 0);
    return total + (shares * price) - mtfLoan;
  }, 0);
  const displayEquity = displayCash + holdingsNetValue;
  $("kpiEquity").textContent = money(displayEquity);
  $("kpiCash").textContent = money(displayCash);
  const holdingsCount = stateHoldingCount;
  $("kpiHoldings").textContent = holdingsCount || "-";
  $("kpiRun").textContent = report?.data_as_of ? `${report.run_date || "-"} / data ${report.data_as_of}` : (report?.run_date || "-");
  renderTimings(report?.timings || {});
  renderActions(report?.actions || []);
  renderHoldings(report?.holdings || []);
  renderSignals(report?.signal_rows || []);
}

function renderTimings(timings) {
  const target = $("runTimings");
  if (!target) return;
  const entries = Object.entries(timings || {}).filter(([, value]) => Number.isFinite(Number(value)));
  if (!entries.length) {
    target.classList.add("hidden");
    target.innerHTML = "";
    return;
  }
  const labels = {
    load_config_state: "Load state",
    history_fetch: "History",
    intraday_overlay: "Intraday",
    current_price_overlay: "CMP",
    signal_generation: "Signals",
    ath_history: "ATH",
    action_report_build: "Report",
    apply_actions: "Apply",
    total_before_save: "Total",
  };
  target.innerHTML = entries.map(([key, value]) => (
    `<span><strong>${labels[key] || key}</strong> ${Number(value).toFixed(2)}s</span>`
  )).join("");
  target.classList.remove("hidden");
}

function currentLedgerCash() {
  const input = $("ledgerCash");
  if (input && input.value !== "") return Number(input.value);
  return Number(state.liveState?.cash ?? state.report?.cash ?? state.config?.initial_capital ?? 0);
}

function renderLedgerCash() {
  const input = $("ledgerCash");
  if (!input) return;
  const cash = state.liveState?.cash ?? state.report?.cash ?? state.config?.initial_capital ?? "";
  input.value = cash === "" ? "" : Number(cash).toFixed(2);
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
    const fundedMultiple = Number(state.config?.mtf_funded_multiple || 3);
    const mtfAvailable = Number(state.report?.mtf?.available || 0);
    const mtfBudget = action.side === "BUY"
      ? Math.max(action.value * fundedMultiple, action.value)
      : action.value;
    const cappedMtfBudget = mtfAvailable > 0 ? Math.min(mtfBudget, mtfAvailable) : mtfBudget;
    const mtfQty = action.price > 0 ? Math.max(Math.floor(cappedMtfBudget / action.price), 1) : action.shares;
    return `
      <article class="action-card trade-action" data-action-id="${escapeAttr(action.id || "")}" data-cash-qty="${escapeAttr(action.shares || 0)}" data-mtf-qty="${escapeAttr(mtfQty || action.shares || 0)}">
        <div class="action-summary">
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
          <label class="check-label mini-check" title="After a successful broker order, also update the strategy ledger.">
            <input class="action-book" type="checkbox" checked>
            <span>Book after place</span>
          </label>
        </div>
        <div class="action-buttons">
          <button type="button" data-preview-order>Preview Only</button>
          <button class="primary" type="button" data-place-order>Place Order</button>
          <button type="button" data-book-ledger>Book Only</button>
        </div>
        <div class="action-value">
          <span>Order value</span>
          <strong class="value">${money(action.value)}</strong>
        </div>
      </article>
    `;
  }).join("");
}

function renderBrokerOrders() {
  const rows = state.brokerOrders || [];
  $("brokerOrdersBody").innerHTML = rows.length ? rows.slice().reverse().map((row) => `
    <tr data-order-log-id="${escapeAttr(row.id || "")}" data-broker-order-id="${escapeAttr(row.broker_order_id || "")}">
      <td>${escapeHtml(row.created_at || "")}</td>
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.side || "")}</td>
      <td>${escapeHtml(row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td><span class="status-pill ${row.ok ? "ok" : "bad"}">${row.dry_run ? "Preview" : (row.ok ? "Success" : "Failed")}</span></td>
      <td>${escapeHtml(row.broker_order_id || "")}</td>
      <td>${escapeHtml(row.message || "")}</td>
      <td class="row-actions">
        ${row.broker_order_id ? `<button type="button" data-cancel-order>Cancel</button>` : ""}
        <button type="button" data-remove-order>Remove</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="10">No broker orders recorded.</td></tr>`;
}

function renderIciciPortfolioRows(rows) {
  const body = $("iciciPortfolioBody");
  if (!body) return;
  body.innerHTML = rows.length ? rows.map((row, index) => `
    <tr data-icici-portfolio-index="${index}">
      <td>${escapeHtml(row.source || "Portfolio")}</td>
      <td>${escapeHtml(portfolioBuyDate(row) || "")}</td>
      <td>${escapeHtml(row.symbol || row.stock_code || "")}</td>
      <td>${escapeHtml(row.funding_mode || row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td>${money(row.value)}</td>
      <td>${money(row.margin_amount)}</td>
      <td>${money(row.mtf_loan)}</td>
      <td><button type="button" data-import-icici-holding>Import Holding</button></td>
    </tr>
  `).join("") : `<tr><td colspan="10">No portfolio rows returned.</td></tr>`;
}

function renderTradeRows(bodyId, rows, datasetName, buttonAttr) {
  const body = $(bodyId);
  if (!body) return;
  body.innerHTML = rows.length ? rows.map((row, index) => `
    <tr data-${datasetName}-index="${index}">
      <td>${escapeHtml(row.date || "")}</td>
      <td>${escapeHtml(row.symbol || row.stock_code || "")}</td>
      <td>${escapeHtml(row.side || "")}</td>
      <td>${escapeHtml(row.funding_mode || row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td>${money(row.value)}</td>
      <td>${money(row.margin_amount)}</td>
      <td>${money(row.mtf_loan)}</td>
      <td>${escapeHtml(row.order_id || "")}</td>
      <td><button type="button" ${buttonAttr}>Import Trade</button></td>
    </tr>
  `).join("") : `<tr><td colspan="11">No trade rows returned.</td></tr>`;
}

function renderIciciTradeRows(rows) {
  renderTradeRows("iciciTradesBody", rows, "icici-trade", "data-import-icici-trade");
}

function renderDhanTradeRows(rows) {
  renderTradeRows("dhanTradesBody", rows, "dhan-trade", "data-import-dhan-trade");
}

function renderDhanOrderRows(rows) {
  const body = $("dhanOrdersBody");
  if (!body) return;
  body.innerHTML = rows.length ? rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.date || "")}</td>
      <td>${escapeHtml(row.symbol || row.stock_code || "")}</td>
      <td>${escapeHtml(row.side || "")}</td>
      <td>${escapeHtml(row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td><span class="status-pill">${escapeHtml(row.status || "")}</span></td>
      <td>${escapeHtml(row.order_id || "")}</td>
      <td>${escapeHtml(row.message || "")}</td>
    </tr>
  `).join("") : `<tr><td colspan="9">No Dhan broker orders returned.</td></tr>`;
}

function renderDhanPortfolioRows(rows) {
  const body = $("dhanPortfolioBody");
  if (!body) return;
  body.innerHTML = rows.length ? rows.map((row, index) => `
    <tr data-dhan-portfolio-index="${index}">
      <td>${escapeHtml(row.source || "Dhan")}</td>
      <td>${escapeHtml(row.symbol || row.stock_code || "")}</td>
      <td>${escapeHtml(row.funding_mode || row.product || "")}</td>
      <td>${money(row.quantity)}</td>
      <td>${money(row.price)}</td>
      <td>${money(row.value)}</td>
      <td>${money(row.margin_amount)}</td>
      <td>${money(row.mtf_loan)}</td>
      <td><button type="button" data-import-dhan-holding>Import Holding</button></td>
    </tr>
  `).join("") : `<tr><td colspan="9">No Dhan rows returned.</td></tr>`;
}

function renderHoldings(reportHoldings) {
  renderLedgerCash();
  const reportBySymbol = marketRowsBySymbol(state.report, reportHoldings);
  const holdings = Object.values(state.liveState?.holdings || {});
  $("holdingsBody").innerHTML = holdings.length ? holdings.map((holding) => holdingRow(holding, reportBySymbol.get(holding.symbol))).join("") : `<tr><td colspan="16">No strategy holdings.</td></tr>`;
}

function holdingRow(holding = {}, report = {}) {
  const mode = holding.funding_mode || report.funding_mode || "delivery";
  const shares = Number(holding.shares || 0);
  const entry = Number(holding.entry_price || 0);
  const invested = Number(holding.cost_basis || shares * entry);
  const cmp = Number(report.last_price ?? report.price ?? entry);
  const mtfLoan = Number(holding.mtf_loan || 0);
  const gain = (shares * cmp) - invested;
  const gainPct = invested > 0 ? gain / invested : 0;
  return `
    <tr class="holding-row">
      <td><input class="holding-date" value="${escapeAttr(holding.entry_date || "")}"></td>
      <td><input class="holding-symbol" value="${escapeAttr(holding.symbol || "")}"></td>
      <td>${escapeHtml(descriptionFor(holding.symbol, holding.broker))}</td>
      <td><input class="holding-shares" inputmode="numeric" value="${escapeAttr(holding.shares || "")}"></td>
      <td><input class="holding-entry" inputmode="decimal" value="${escapeAttr(holding.entry_price || "")}"></td>
      <td>${money(invested)}</td>
      <td>${money(cmp)}</td>
      <td><input class="holding-ema" inputmode="decimal" value="${escapeAttr(holding.entry_ema || "")}"></td>
      <td><input class="holding-low" inputmode="decimal" value="${escapeAttr(holding.entry_low || "")}"></td>
      <td>${money(gain)}</td>
      <td>${pct(gainPct)}</td>
      <td><input class="holding-margin" inputmode="decimal" value="${escapeAttr(holding.margin_used || 0)}"></td>
      <td><input class="holding-loan" inputmode="decimal" value="${escapeAttr(mtfLoan)}"></td>
      <td>
        <select class="holding-mode">
          <option value="delivery" ${mode !== "mtf" ? "selected" : ""}>Delivery</option>
          <option value="mtf" ${mode === "mtf" ? "selected" : ""}>MTF</option>
        </select>
      </td>
      <td><input class="holding-broker" value="${escapeAttr(holding.broker || "")}"></td>
      <td><button type="button" data-remove-row>Remove</button></td>
    </tr>
  `;
}

function marketRowsBySymbol(report, reportHoldings = null) {
  const rows = new Map();
  (report?.signal_rows || []).forEach((row) => {
    if (!row.symbol) return;
    rows.set(row.symbol, { ...row, last_price: row.price });
  });
  (reportHoldings || report?.holdings || []).forEach((row) => {
    if (!row.symbol) return;
    rows.set(row.symbol, { ...(rows.get(row.symbol) || {}), ...row });
  });
  return rows;
}

function renderLedger() {
  const trades = state.liveState?.trades || [];
  $("ledgerBody").innerHTML = trades.length ? trades.map((trade) => ledgerRow(trade)).join("") : `<tr><td colspan="9">No booked orders.</td></tr>`;
  renderCompletedLedger(trades);
}

function renderCompletedLedger(trades) {
  const completed = completedTrades(trades || []);
  const body = $("completedLedgerBody");
  if (body) {
    body.innerHTML = completed.length ? completed.map((trade) => `
      <tr>
        <td>${escapeHtml(trade.buyDate)}</td>
        <td>${escapeHtml(trade.symbol)}</td>
        <td>${escapeHtml(descriptionFor(trade.symbol, trade.broker))}</td>
        <td>${money(trade.buyPrice)}</td>
        <td>${money(trade.shares)}</td>
        <td>${money(trade.buyValue)}</td>
        <td>${money(trade.sellPrice)}</td>
        <td>${escapeHtml(trade.sellDate)}</td>
        <td>${money(trade.holdingDays)}</td>
        <td>${money(trade.profit)}</td>
        <td>${pct(trade.profitPct)}</td>
      </tr>
    `).join("") : `<tr><td colspan="11">No completed sells yet.</td></tr>`;
  }
  renderLedgerSummary(completed);
}

function completedTrades(trades) {
  const openBuys = new Map();
  const completed = [];
  trades.forEach((trade) => {
    const symbol = trade.symbol;
    const side = String(trade.side || "").toUpperCase();
    if (!symbol) return;
    if (side === "BUY") {
      if (!openBuys.has(symbol)) openBuys.set(symbol, []);
      openBuys.get(symbol).push(trade);
      return;
    }
    if (side !== "SELL" || !openBuys.get(symbol)?.length) return;
    const buy = openBuys.get(symbol).shift();
    const buyValue = Number(buy.value || Number(buy.shares || 0) * Number(buy.price || 0));
    const sellValue = Number(trade.value || Number(trade.shares || 0) * Number(trade.price || 0));
    const profit = Number(trade.profit ?? sellValue - buyValue);
    const buyDate = buy.signal_date || buy.date || "";
    const sellDate = trade.signal_date || trade.date || "";
    completed.push({
      symbol,
      broker: trade.broker || buy.broker || "",
      buyDate,
      sellDate,
      buyPrice: Number(buy.price || 0),
      sellPrice: Number(trade.price || 0),
      shares: Number(trade.shares || buy.shares || 0),
      buyValue,
      sellValue,
      profit,
      profitPct: buyValue > 0 ? profit / buyValue : 0,
      holdingDays: daysBetween(buyDate, sellDate),
    });
  });
  return completed;
}

function renderLedgerSummary(completed) {
  const target = $("ledgerSummary");
  if (!target) return;
  const totalProfit = completed.reduce((sum, row) => sum + row.profit, 0);
  const totalInvested = completed.reduce((sum, row) => sum + row.buyValue, 0);
  const monthly = groupSum(completed, (row) => String(row.sellDate || "").slice(0, 7), "profit");
  const yearly = groupSum(completed, (row) => String(row.sellDate || "").slice(0, 4), "profit");
  const maxMonthlyInvested = Math.max(0, ...Object.values(groupSum(completed, (row) => String(row.buyDate || "").slice(0, 7), "buyValue")));
  target.innerHTML = [
    summaryCard("Total Profit", money(totalProfit)),
    summaryCard("Total % Profit", pct(totalInvested > 0 ? totalProfit / totalInvested : 0)),
    summaryCard("Monthly Profit", summaryPairs(monthly)),
    summaryCard("Max Invested/Month", money(maxMonthlyInvested)),
    summaryCard("Yearly Profit", summaryPairs(yearly)),
    summaryCard("XIRR / CAGR", `${optionalPct(state.report?.xirr)} / ${optionalPct(liveCagr())}`),
  ].join("");
}

function renderBrokerCards(targetId, response) {
  const target = $(targetId);
  if (!target) return;
  const available = brokerMetric(response, [
    /cash.*avail/i,
    /avail.*cash/i,
    /available.*balance/i,
    /availabel.*balance/i,
    /withdraw.*balance/i,
    /clear.*balance/i,
    /bank.*balance/i,
    /^balance$/i,
  ]);
  const totalLimit = brokerMetric(response, [
    /total.*limit/i,
    /sod.*limit/i,
    /gross.*limit/i,
    /cash.*limit/i,
    /allocated.*equity/i,
    /allocated.*amount/i,
    /collateral.*amount/i,
    /total.*margin/i,
  ]);
  const used = brokerMetric(response, [
    /used.*margin/i,
    /margin.*used/i,
    /utili[sz]ed/i,
    /utilized.*amount/i,
    /block.*trade/i,
    /amount.*block/i,
    /blocked/i,
  ]);
  const explicitMarginAvailable = brokerMetric(response, [
    /margin.*avail/i,
    /available.*margin/i,
    /limit.*avail/i,
    /available.*limit/i,
    /net.*available/i,
  ]);
  const derivedMarginAvailable = totalLimit !== null && used !== null ? Math.max(totalLimit - used, 0) : null;
  const cards = [
    ["Cash Available", available],
    ["Margin Available", explicitMarginAvailable ?? derivedMarginAvailable],
    ["Total Limit", totalLimit],
    ["Used Margin", used],
  ];
  target.innerHTML = `
    ${cards.map(([label, value]) => summaryCard(label, money(value))).join("")}
    ${brokerMoneyTable(response)}
  `;
}

function brokerMetric(value, patterns) {
  const exact = findNumberDeep(value, patterns);
  if (exact !== null) return exact;
  const fields = collectMoneyFields(value);
  const row = fields.find((item) => patterns.some((pattern) => pattern.test(item.key) || pattern.test(item.path)));
  return row ? row.value : null;
}

function findNumberDeep(value, patterns) {
  const seen = new Set();
  function walk(node) {
    if (node === null || node === undefined || seen.has(node)) return null;
    if (typeof node === "object") seen.add(node);
    if (Array.isArray(node)) {
      for (const item of node) {
        const found = walk(item);
        if (found !== null) return found;
      }
      return null;
    }
    if (typeof node !== "object") return null;
    for (const [key, raw] of Object.entries(node)) {
      if (patterns.some((pattern) => pattern.test(key))) {
        const parsed = parseBrokerNumber(raw);
        if (parsed !== null) return parsed;
      }
    }
    for (const raw of Object.values(node)) {
      const found = walk(raw);
      if (found !== null) return found;
    }
    return null;
  }
  return walk(value);
}

function brokerMoneyTable(response) {
  const rows = collectMoneyFields(response)
    .filter((row) => !/id$|token|time|date|code|status|count|segment/i.test(row.key))
    .slice(0, 18);
  if (!rows.length) return `<article class="broker-fields"><span>Detected money fields</span><strong>-</strong></article>`;
  return `
    <article class="broker-fields">
      <span>Detected money fields</span>
      <table>
        <tbody>
          ${rows.map((row) => `<tr><td>${escapeHtml(prettyBrokerKey(row.key))}</td><td>${money(row.value)}</td></tr>`).join("")}
        </tbody>
      </table>
    </article>
  `;
}

function collectMoneyFields(value) {
  const rows = [];
  const seen = new Set();
  function walk(node, path = "") {
    if (node === null || node === undefined || seen.has(node)) return;
    if (typeof node === "object") seen.add(node);
    if (Array.isArray(node)) {
      node.forEach((item, index) => walk(item, `${path}[${index}]`));
      return;
    }
    if (typeof node !== "object") return;
    Object.entries(node).forEach(([key, raw]) => {
      const nextPath = path ? `${path}.${key}` : key;
      const parsed = parseBrokerNumber(raw);
      if (parsed !== null && Math.abs(parsed) >= 0.001) rows.push({ key, path: nextPath, value: parsed });
      walk(raw, nextPath);
    });
  }
  walk(value);
  const unique = new Map();
  rows.forEach((row) => {
    if (!unique.has(row.path)) unique.set(row.path, row);
  });
  return [...unique.values()].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

function prettyBrokerKey(key) {
  return String(key || "")
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function parseBrokerNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/,/g, "").replace(/[^\d.-]/g, "").trim();
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function liveCagr() {
  const start = Date.parse(state.liveState?.created_at || "");
  const end = Date.parse(state.report?.run_date || state.report?.run_time || "");
  const capital = Number(state.config?.initial_capital || 0);
  const equity = Number(state.report?.equity || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || capital <= 0 || equity <= 0) return null;
  const years = (end - start) / (365.25 * 24 * 60 * 60 * 1000);
  if (years <= 0) return null;
  return Math.pow(equity / capital, 1 / years) - 1;
}

function summaryCard(label, value) {
  return `<article><span>${escapeHtml(label)}</span><strong>${value || "-"}</strong></article>`;
}

function summaryPairs(values) {
  const entries = Object.entries(values).filter(([key]) => key).slice(-4);
  return entries.length ? entries.map(([key, value]) => `${key}: ${money(value)}`).join("<br>") : "-";
}

function groupSum(rows, keyFn, field) {
  return rows.reduce((acc, row) => {
    const key = keyFn(row);
    if (!key) return acc;
    acc[key] = (acc[key] || 0) + Number(row[field] || 0);
    return acc;
  }, {});
}

function daysBetween(start, end) {
  const from = Date.parse(start);
  const to = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return "";
  return Math.max(Math.round((to - from) / 86400000), 0);
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
  const sourceLabel = state.report?.signal_time === "CMP" ? "Live Px/EMA" : "Source Px/EMA";
  $("signalsBody").innerHTML = rows.length ? rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.symbol)}</td>
      <td>${escapeHtml(row.signal_source || "")}</td>
      <td>${escapeHtml(row.signal_label || "")}</td>
      <td><span class="cell-label">${sourceLabel}</span>${escapeHtml(row.source_date || "")} ${money(row.source_price)} / ${money(row.source_ema)}</td>
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
  const basis = state.report?.signal_time === "CMP" ? " live" : "";
  return `${source}${sourceDate}${sourceValues}${basis}`;
}

function portfolioBuyDate(row) {
  if (row?.date) return String(row.date).slice(0, 10);
  const match = matchingBuyTrade(row);
  return match?.date ? String(match.date).slice(0, 10) : "";
}

function matchingBuyTrade(row) {
  const symbol = row?.symbol || "";
  const stockCode = row?.stock_code || "";
  const qty = Number(row?.quantity || 0);
  const price = Number(row?.price || 0);
  const buys = (state.iciciTradeRows || [])
    .filter((trade) => String(trade.side || "").toUpperCase() === "BUY")
    .filter((trade) => trade.symbol === symbol || trade.stock_code === stockCode)
    .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  if (!buys.length) return null;
  const exact = buys.find((trade) =>
    Math.abs(Number(trade.quantity || 0) - qty) < 0.001 &&
    Math.abs(Number(trade.price || 0) - price) < Math.max(0.05, price * 0.002)
  );
  return exact || buys[0];
}

function descriptionFor(symbol, broker = "") {
  const codes = window.BROKER_CODES?.[symbol] || {};
  const icici = codes.icici || symbol?.split(":").pop() || "";
  const dhan = codes.dhan || symbol?.split(":").pop() || "";
  if (String(broker || "").toLowerCase() === "dhan") return `Dhan ${dhan}`;
  if (String(broker || "").toLowerCase() === "icici") return `ICICI ${icici}`;
  return `ICICI ${icici} / Dhan ${dhan}`;
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
  renderReport(state.report);
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
  renderReport(state.report);
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
    margin_used: row.querySelector(".holding-margin").value,
    broker: row.querySelector(".holding-broker").value,
    entry_ema: row.querySelector(".holding-ema").value,
    entry_low: row.querySelector(".holding-low").value,
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
    holdings: holdings ?? serializeHoldings(),
    trades: trades ?? serializeLedger(),
  };
  const cashInput = $("ledgerCash");
  if (cashInput && cashInput.value !== "") payload.cash = Number(cashInput.value);
  const response = await api("/api/live/state", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.liveState = response.state;
  renderReport(state.report);
  renderHoldings(state.report?.holdings || []);
  renderLedger();
  setMessage("Strategy ledger saved.");
}

async function resetLedgerCashToInitialCapital() {
  const response = await api("/api/live/state", {
    method: "PUT",
    body: JSON.stringify({ holdings: serializeHoldings(), trades: serializeLedger() }),
  });
  state.liveState = response.state;
  renderReport(state.report);
  renderLedger();
  setMessage("Strategy cash reconciled from initial capital and completed trades.");
}

async function refreshBrokerOrderBook() {
  $("orderBookStatus").textContent = "Loading...";
  const payload = await api("/api/icici/order/book");
  state.iciciOrderBook = payload.orders;
  $("orderResult").textContent = JSON.stringify(payload.orders, null, 2);
  $("orderBookStatus").textContent = "Broker book loaded";
}

async function loadIciciPortfolio() {
  $("iciciPortfolioStatus").textContent = "Loading...";
  const query = dateQuery("iciciFromDate", "iciciToDate");
  const payload = await api(`/api/icici/portfolio${query}`);
  const holdingRows = payload.portfolio_holdings?.rows || [];
  const positionRows = payload.positions?.rows || [];
  state.iciciPortfolioRows = [
    ...holdingRows.map((row) => ({ ...row, source: "Holdings" })),
    ...positionRows.map((row) => ({ ...row, source: "Positions" })),
  ].filter((row) => row.symbol && Number(row.quantity || 0) > 0);
  renderIciciPortfolioRows(state.iciciPortfolioRows);
  renderBrokerCards("iciciBrokerCards", payload.funds?.response || payload.funds || {});
  $("iciciBrokerSummary").textContent = JSON.stringify({ funds: payload.funds?.response, demat: payload.demat_holdings?.response }, null, 2);
  $("iciciResult").textContent = JSON.stringify(payload.funds?.response || payload, null, 2);
  $("iciciPortfolioStatus").textContent = `${state.iciciPortfolioRows.length} rows`;
}

async function loadIciciTrades() {
  $("iciciTradesStatus").textContent = "Loading...";
  const payload = await api(`/api/icici/trades${dateQuery("iciciFromDate", "iciciToDate")}`);
  state.iciciTradeRows = (payload.trades?.rows || []).filter((row) => row.symbol && Number(row.quantity || 0) > 0);
  renderIciciTradeRows(state.iciciTradeRows);
  renderIciciPortfolioRows(state.iciciPortfolioRows);
  $("iciciResult").textContent = JSON.stringify(payload.trades?.response || payload, null, 2);
  $("iciciTradesStatus").textContent = `${state.iciciTradeRows.length} rows`;
}

async function loadDhanSummary() {
  $("dhanResult").textContent = "Loading...";
  const payload = await api("/api/dhan/summary");
  const holdingRows = payload.holdings?.rows || [];
  const positionRows = payload.positions?.rows || [];
  state.dhanPortfolioRows = [
    ...holdingRows.map((row) => ({ ...row, source: "Holdings" })),
    ...positionRows.map((row) => ({ ...row, source: "Positions" })),
  ].filter((row) => row.symbol && Number(row.quantity || 0) > 0);
  state.dhanOrderRows = payload.orders?.rows || [];
  renderDhanPortfolioRows(state.dhanPortfolioRows);
  renderDhanOrderRows(state.dhanOrderRows);
  renderBrokerCards("dhanBrokerCards", payload.funds?.response || payload.funds || {});
  $("dhanResult").textContent = JSON.stringify({ profile: payload.profile?.response, funds: payload.funds?.response, orders: payload.orders?.response }, null, 2);
  renderDhan(payload.credentials || {});
}

async function loadDhanTrades() {
  $("dhanResult").textContent = "Loading trades...";
  const payload = await api(`/api/dhan/trades${dateQuery("dhanFromDate", "dhanToDate")}`);
  state.dhanTradeRows = (payload.trades?.rows || []).filter((row) => row.symbol && Number(row.quantity || 0) > 0);
  renderDhanTradeRows(state.dhanTradeRows);
  $("dhanResult").textContent = JSON.stringify(payload.trades?.response || payload, null, 2);
}

function dateQuery(fromId, toId) {
  const params = new URLSearchParams();
  if ($(fromId)?.value) params.set("from_date", $(fromId).value);
  if ($(toId)?.value) params.set("to_date", $(toId).value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function importIciciHolding(index) {
  const row = state.iciciPortfolioRows[index];
  if (!row) return;
  const buyDate = portfolioBuyDate(row);
  const payload = await api("/api/icici/import/holding", {
    method: "POST",
    body: JSON.stringify({ row: { ...row, date: buyDate || row.date, broker: "icici" } }),
  });
  state.liveState = payload.state;
  renderReport(state.report);
  renderLedger();
  setMessage(`Imported ${row.symbol} into strategy holdings.`);
}

async function importIciciTrade(index) {
  const row = state.iciciTradeRows[index];
  if (!row) return;
  const payload = await api("/api/icici/import/trade", {
    method: "POST",
    body: JSON.stringify({ row: { ...row, broker: "icici" } }),
  });
  state.liveState = payload.state;
  renderReport(state.report);
  renderLedger();
  setMessage(`Imported ${row.symbol} trade into strategy ledger.`);
}

async function importDhanHolding(index) {
  const row = state.dhanPortfolioRows[index];
  if (!row) return;
  const payload = await api("/api/dhan/import/holding", {
    method: "POST",
    body: JSON.stringify({ row: { ...row, broker: "dhan" } }),
  });
  state.liveState = payload.state;
  renderReport(state.report);
  renderLedger();
  setMessage(`Imported ${row.symbol} into strategy holdings.`);
}

async function importDhanTrade(index) {
  const row = state.dhanTradeRows[index];
  if (!row) return;
  const payload = await api("/api/dhan/import/trade", {
    method: "POST",
    body: JSON.stringify({ row: { ...row, broker: "dhan" } }),
  });
  state.liveState = payload.state;
  renderReport(state.report);
  renderLedger();
  setMessage(`Imported ${row.symbol} trade into strategy ledger.`);
}

function syncActionProductQty(select) {
  const card = select.closest(".trade-action");
  if (!card) return;
  const qty = select.value === "mtf" ? card.dataset.mtfQty : card.dataset.cashQty;
  const qtyInput = card.querySelector(".action-qty");
  if (qtyInput && qty) qtyInput.value = qty;
  updateActionCardValue(card);
}

function updateActionCardValue(card) {
  const qty = Number(card.querySelector(".action-qty")?.value || 0);
  const price = Number(card.querySelector(".action-price")?.value || 0);
  const value = card.querySelector(".value");
  if (value) value.textContent = money(qty * price);
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

async function pullSync(event) {
  event.preventDefault();
  setMessage("Pulling EC2 data...");
  $("syncResult").textContent = "Sync in progress...";
  const payload = await api("/api/sync/pull", {
    method: "POST",
    body: JSON.stringify({
      remote_url: $("syncRemoteUrl")?.value || "",
      token: $("syncToken")?.value || "",
    }),
  });
  state.settings = payload.settings || state.settings;
  state.config = payload.live_config || state.config;
  state.liveState = payload.live_state || state.liveState;
  state.report = payload.report || state.report;
  state.brokerOrders = payload.broker_orders || state.brokerOrders;
  state.sync = payload.status || state.sync;
  renderConfig(state.config || {});
  renderReport(state.report);
  renderBrokerOrders();
  renderLedger();
  renderSyncStatus();
  $("syncResult").textContent = JSON.stringify({ applied: payload.applied, exported_at: payload.exported_at }, null, 2);
  setMessage("EC2 data pulled into this local instance.");
}

on("runSignals", "click", async () => {
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
    if (payload.live_state) state.liveState = payload.live_state;
    renderReport(payload.report);
    setMessage("Live signal run completed.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

on("refreshOrderBook", "click", () => {
  refreshBrokerOrderBook().catch((error) => setMessage(error.message, true));
});

on("loadIciciPortfolio", "click", () => {
  loadIciciPortfolio().catch((error) => setMessage(error.message, true));
});

on("loadIciciTrades", "click", () => {
  loadIciciTrades().catch((error) => setMessage(error.message, true));
});

on("loadDhanSummary", "click", () => {
  loadDhanSummary().catch((error) => setMessage(error.message, true));
});

on("loadDhanTrades", "click", () => {
  loadDhanTrades().catch((error) => setMessage(error.message, true));
});

on("clearLedger", "click", async () => {
  if (!confirm("Clear the local strategy ledger?")) return;
  try {
    const payload = await api("/api/live/clear", { method: "POST", body: JSON.stringify({}) });
    state.liveState = payload.state;
    state.report = null;
    renderReport(null);
    renderLedger();
    setMessage("Ledger cleared.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

on("configForm", "submit", async (event) => {
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
    if (payload.live_state) state.liveState = payload.live_state;
    renderConfig(payload.config);
    renderReport(state.report);
    setMessage("Configuration saved. Ledger cash adjusted by the capital change.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

on("openIciciLogin", "click", async () => {
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

on("iciciForm", "submit", async (event) => {
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
    setIciciConnection(Boolean(payload.test?.ok), payload.test?.time || "");
  } catch (error) {
    $("iciciResult").textContent = error.message;
    setIciciConnection(false, error.message);
  }
});

on("dhanForm", "submit", async (event) => {
  event.preventDefault();
  $("dhanResult").textContent = "Testing...";
  try {
    const payload = await api("/api/dhan/session", {
      method: "POST",
      body: JSON.stringify({
        client_id: $("dhanClientId").value,
        access_token: $("dhanAccessToken").value,
      }),
    });
    renderDhan(payload.credentials || {});
    $("dhanResult").textContent = JSON.stringify(payload.profile, null, 2);
    setMessage("Dhan credentials saved.");
  } catch (error) {
    $("dhanResult").textContent = error.message;
    setMessage(error.message, true);
  }
});

on("testIciciQuote", "click", async () => {
  $("iciciResult").textContent = "Testing...";
  try {
    const payload = await api("/api/icici/test", {
      method: "POST",
      body: JSON.stringify({ stock_code: $("iciciStock").value }),
    });
    $("iciciResult").textContent = JSON.stringify(payload.test, null, 2);
    setIciciConnection(Boolean(payload.test?.ok), payload.test?.time || "");
  } catch (error) {
    $("iciciResult").textContent = error.message;
    setIciciConnection(false, error.message);
  }
});

on("actionsList", "change", (event) => {
  if (event.target.matches(".action-product")) syncActionProductQty(event.target);
});

on("actionsList", "input", (event) => {
  if (event.target.matches(".action-qty, .action-price")) {
    const card = event.target.closest(".trade-action");
    if (card) updateActionCardValue(card);
  }
});

on("actionsList", "click", (event) => {
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

on("brokerOrdersBody", "click", async (event) => {
  const row = event.target.closest("tr");
  if (!row) return;
  if (event.target.matches("[data-remove-order]")) {
    const payload = await api(`/api/broker/orders/${row.dataset.orderLogId}`, { method: "DELETE" });
    state.brokerOrders = payload.broker_orders || [];
    renderBrokerOrders();
    $("orderResult").textContent = "";
    setMessage("Preview removed.");
  }
  if (event.target.matches("[data-cancel-order]")) {
    const orderId = row.dataset.brokerOrderId;
    if (!orderId || !confirm(`Cancel broker order ${orderId}?`)) return;
    const payload = await api("/api/icici/order/cancel", {
      method: "POST",
      body: JSON.stringify({ order_id: orderId, exchange_code: "NSE" }),
    });
    state.brokerOrders = payload.broker_orders || state.brokerOrders;
    renderBrokerOrders();
    $("orderResult").textContent = JSON.stringify(payload.cancel, null, 2);
    setMessage("Cancel request sent.");
  }
});

on("iciciPortfolioBody", "click", (event) => {
  const row = event.target.closest("tr");
  if (!row || !event.target.matches("[data-import-icici-holding]")) return;
  importIciciHolding(Number(row.dataset.iciciPortfolioIndex)).catch((error) => setMessage(error.message, true));
});

on("iciciTradesBody", "click", (event) => {
  const row = event.target.closest("tr");
  if (!row || !event.target.matches("[data-import-icici-trade]")) return;
  importIciciTrade(Number(row.dataset.iciciTradeIndex)).catch((error) => setMessage(error.message, true));
});

on("dhanPortfolioBody", "click", (event) => {
  const row = event.target.closest("tr");
  if (!row || !event.target.matches("[data-import-dhan-holding]")) return;
  importDhanHolding(Number(row.dataset.dhanPortfolioIndex)).catch((error) => setMessage(error.message, true));
});

on("dhanTradesBody", "click", (event) => {
  const row = event.target.closest("tr");
  if (!row || !event.target.matches("[data-import-dhan-trade]")) return;
  importDhanTrade(Number(row.dataset.dhanTradeIndex)).catch((error) => setMessage(error.message, true));
});

document.body.addEventListener("click", (event) => {
  if (event.target.matches("[data-remove-row]")) {
    event.target.closest("tr")?.remove();
  }
});

on("addHolding", "click", () => {
  $("holdingsBody").insertAdjacentHTML("beforeend", holdingRow({ entry_date: new Date().toISOString().slice(0, 10), funding_mode: "delivery" }, {}));
});

on("saveHoldings", "click", () => {
  saveLiveState({ holdings: serializeHoldings() }).catch((error) => setMessage(error.message, true));
});

on("addLedgerTrade", "click", () => {
  $("ledgerBody").insertAdjacentHTML("beforeend", ledgerRow({ date: new Date().toISOString().slice(0, 10), side: "BUY", funding_mode: "delivery", reason: "manual" }));
});

on("saveLedger", "click", () => {
  saveLiveState({ trades: serializeLedger() }).catch((error) => setMessage(error.message, true));
});

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === button.dataset.tab));
  });
});

document.body.addEventListener("click", (event) => {
  const th = event.target.closest("th");
  const table = th?.closest(".sortable-table");
  if (!th || !table) return;
  const ascending = th.dataset.sortDir !== "asc";
  sortTable(table, th.cellIndex, ascending);
  [...th.parentElement.children].forEach((cell) => delete cell.dataset.sortDir);
  th.dataset.sortDir = ascending ? "asc" : "desc";
});

function sortTable(table, columnIndex, ascending) {
  const tbody = table.tBodies[0];
  if (!tbody) return;
  const rows = [...tbody.rows];
  rows.sort((a, b) => compareCell(a.cells[columnIndex], b.cells[columnIndex], ascending));
  rows.forEach((row) => tbody.appendChild(row));
}

function compareCell(aCell, bCell, ascending) {
  const a = cellValue(aCell);
  const b = cellValue(bCell);
  const aNum = Number(String(a).replace(/,/g, ""));
  const bNum = Number(String(b).replace(/,/g, ""));
  const result = Number.isFinite(aNum) && Number.isFinite(bNum)
    ? aNum - bNum
    : String(a).localeCompare(String(b));
  return ascending ? result : -result;
}

function cellValue(cell) {
  const input = cell?.querySelector("input, select");
  return input ? input.value : (cell?.textContent || "").trim();
}

function renderLogSettings() {
  if ($("logsEnabled")) $("logsEnabled").checked = Boolean(state.logSettings.enabled ?? true);
  if ($("logLevel")) $("logLevel").value = state.logSettings.level || "INFO";
}

async function refreshLogs() {
  const payload = await api("/api/logs");
  state.logSettings = payload.settings || {};
  renderLogSettings();
  $("logsOutput").textContent = (payload.lines || []).join("");
}

on("refreshLogs", "click", () => {
  refreshLogs().catch((error) => setMessage(error.message, true));
});

on("logsForm", "submit", async (event) => {
  event.preventDefault();
  const payload = await api("/api/logs/settings", {
    method: "POST",
    body: JSON.stringify({ enabled: $("logsEnabled").checked, level: $("logLevel").value }),
  });
  state.logSettings = payload.settings || {};
  renderLogSettings();
  await refreshLogs();
  setMessage("Log settings saved.");
});

on("syncForm", "submit", (event) => {
  pullSync(event).catch((error) => {
    $("syncResult").textContent = error.message;
    setMessage(error.message, true);
  });
});

setMessage("Dashboard ready.");
load().catch((error) => setMessage(error.message, true));
