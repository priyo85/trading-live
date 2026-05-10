const state = {
  report: null,
  config: null,
  settings: null,
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
  $("dataProvider").value = state.settings.data_provider || "auto";
  renderConfig(state.config || {});
  renderReport(state.report);
  renderIcici(payload.icici || {});
}

function renderConfig(config) {
  $("initialCapital").value = config.initial_capital ?? "";
  $("maxPositions").value = config.max_positions ?? "";
  $("symbolsText").value = (config.symbols || []).join(", ");
}

function renderIcici(credentials) {
  if (credentials.api_key && !$("iciciApiKey").value) {
    $("iciciApiKey").value = credentials.api_key;
  }
  if (credentials.api_secret && !$("iciciSecret").value) {
    $("iciciSecret").value = credentials.api_secret;
  }
  if (credentials.session_token && !$("iciciSession").value) {
    $("iciciSession").value = credentials.session_token;
  }
  const summary = credentials.configured
    ? `Configured: ${credentials.masked_api_key || "yes"}\nSecret: ${credentials.masked_api_secret || "saved"}\nSession: ${credentials.masked_session_token || "saved"}\n${credentials.path || ""}`
    : "Not configured";
  $("iciciResult").textContent = summary;
}

function renderReport(report) {
  $("kpiEquity").textContent = money(report?.equity);
  $("kpiCash").textContent = money(report?.cash);
  $("kpiHoldings").textContent = report?.holdings?.length ?? "-";
  $("kpiRun").textContent = report?.data_as_of ? `${report.run_date || "-"} / data ${report.data_as_of}` : (report?.run_date || "-");
  renderActions(report?.actions || []);
  renderHoldings(report?.holdings || []);
  renderSignals(report?.signal_rows || []);
}

function renderActions(actions) {
  const target = $("actionsList");
  if (!actions.length) {
    target.innerHTML = `<div class="notice">No buy/sell action.</div>`;
    return;
  }
  const rowsBySymbol = new Map((state.report?.signal_rows || []).map((row) => [row.symbol, row]));
  target.innerHTML = actions.map((action) => `
    <label class="action-card">
      <input type="checkbox" class="action-check" value="${escapeAttr(action.id || "")}" checked>
      <span>
        <strong class="${action.side === "BUY" ? "side-buy" : "side-sell"}">${action.side} ${action.symbol}</strong>
        <span>${action.shares || 0} qty at ${money(action.price)} | ${action.reason || ""}${sourceSummary(rowsBySymbol.get(action.symbol))}</span>
      </span>
      <strong class="value">${money(action.value)}</strong>
    </label>
  `).join("");
}

function renderHoldings(rows) {
  $("holdingsBody").innerHTML = rows.length ? rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.symbol)}</td>
      <td>${money(row.shares)}</td>
      <td>${money(row.entry_price)}</td>
      <td>${money(row.last_price)}</td>
      <td>${money(row.unrealized_profit)}</td>
    </tr>
  `).join("") : `<tr><td colspan="5">No open holdings.</td></tr>`;
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

function selectedActionIds() {
  return [...document.querySelectorAll(".action-check:checked")].map((input) => input.value);
}

function selectedActionObjects() {
  const selected = new Set(selectedActionIds());
  return (state.report?.actions || []).filter((action) => selected.has(action.id));
}

function firstSelectedAction() {
  return selectedActionObjects()[0] || null;
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

$("applySelected").addEventListener("click", async () => {
  setMessage("Booking selected actions in the ledger...");
  try {
    const payload = await api("/api/live/run", {
      method: "POST",
      body: JSON.stringify({
        data_provider: $("dataProvider").value,
        price_mode: $("priceMode").value,
        apply_actions: true,
        selected_action_ids: selectedActionIds(),
      }),
    });
    renderReport(payload.report);
    setMessage("Selected actions booked in the local ledger.");
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("clearLedger").addEventListener("click", async () => {
  if (!confirm("Clear the local live ledger?")) return;
  try {
    await api("/api/live/clear", { method: "POST", body: JSON.stringify({}) });
    renderReport(null);
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

$("fillGttFromSelected").addEventListener("click", () => {
  const action = firstSelectedAction();
  if (!action) {
    setMessage("Select one action first.", true);
    return;
  }
  $("gttSymbol").value = action.symbol || "";
  $("gttSide").value = action.side || "BUY";
  $("gttQuantity").value = action.shares || 1;
  $("gttTriggerPrice").value = action.price ? Number(action.price).toFixed(2) : "";
  $("gttLimitPrice").value = action.price ? Number(action.price).toFixed(2) : "";
  setMessage("Selected action copied into the GTT order form.");
});

$("gttForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const dryRun = $("gttDryRun").checked;
  if (!dryRun && !confirm("Place this ICICI GTT order?")) return;

  $("gttResult").textContent = dryRun ? "Preparing preview..." : "Placing GTT order...";
  try {
    const payload = await api("/api/icici/gtt/single", {
      method: "POST",
      body: JSON.stringify({
        symbol: $("gttSymbol").value,
        side: $("gttSide").value,
        quantity: $("gttQuantity").value,
        trigger_price: $("gttTriggerPrice").value,
        limit_price: $("gttLimitPrice").value,
        dry_run: dryRun,
      }),
    });
    $("gttResult").textContent = JSON.stringify(payload.order, null, 2);
    setMessage(dryRun ? "GTT preview ready." : "GTT order request sent to ICICI.");
  } catch (error) {
    $("gttResult").textContent = error.message;
    setMessage(error.message, true);
  }
});

$("refreshGttBook").addEventListener("click", async () => {
  $("gttResult").textContent = "Loading GTT book...";
  try {
    const payload = await api("/api/icici/gtt/book");
    $("gttResult").textContent = JSON.stringify(payload.orders, null, 2);
    setMessage("GTT book loaded.");
  } catch (error) {
    $("gttResult").textContent = error.message;
    setMessage(error.message, true);
  }
});

$("fillLimitFromSelected").addEventListener("click", () => {
  const action = firstSelectedAction();
  if (!action) {
    setMessage("Select one action first.", true);
    return;
  }
  $("limitSymbol").value = action.symbol || "";
  $("limitSide").value = action.side || "BUY";
  $("limitQuantity").value = action.shares || 1;
  $("limitPrice").value = action.price ? Number(action.price).toFixed(2) : "";
  setMessage("Selected action copied into the limit order form.");
});

$("limitOrderForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const dryRun = $("limitDryRun").checked;
  if (!dryRun && !confirm("Place this ICICI limit order?")) return;

  $("limitOrderResult").textContent = dryRun ? "Preparing preview..." : "Placing limit order...";
  try {
    const payload = await api("/api/icici/order/limit", {
      method: "POST",
      body: JSON.stringify({
        symbol: $("limitSymbol").value,
        side: $("limitSide").value,
        quantity: $("limitQuantity").value,
        limit_price: $("limitPrice").value,
        product: $("limitProduct").value,
        validity: $("limitValidity").value,
        dry_run: dryRun,
        user_remark: "emaswing",
      }),
    });
    $("limitOrderResult").textContent = JSON.stringify(payload.order, null, 2);
    setMessage(dryRun ? "Limit order preview ready." : "Limit order request sent to ICICI.");
  } catch (error) {
    $("limitOrderResult").textContent = error.message;
    setMessage(error.message, true);
  }
});

$("refreshOrderBook").addEventListener("click", async () => {
  $("limitOrderResult").textContent = "Loading order book...";
  try {
    const payload = await api("/api/icici/order/book");
    $("limitOrderResult").textContent = JSON.stringify(payload.orders, null, 2);
    setMessage("Order book loaded.");
  } catch (error) {
    $("limitOrderResult").textContent = error.message;
    setMessage(error.message, true);
  }
});

load().catch((error) => setMessage(error.message, true));
