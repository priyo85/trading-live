const runButton = document.querySelector("#runBacktest");
const selectAllButton = document.querySelector("#selectAll");
const clearSelectionButton = document.querySelector("#clearSelection");
const filterInput = document.querySelector("#filterEtfs");
const etfList = document.querySelector("#etfList");
const selectedCount = document.querySelector("#selectedCount");
const statusText = document.querySelector("#statusText");
const message = document.querySelector("#message");
const metrics = document.querySelector("#metrics");
const tradesBody = document.querySelector("#tradesBody");
const periodReturnsBody = document.querySelector("#periodReturnsBody");
const periodReportTitle = document.querySelector("#periodReportTitle");
const capitalFlowsBody = document.querySelector("#capitalFlowsBody");
const openPositionsBody = document.querySelector("#openPositionsBody");
const perSymbolBody = document.querySelector("#perSymbolBody");
const savedReportsBody = document.querySelector("#savedReportsBody");
const compareBody = document.querySelector("#compareBody");
const savedStatus = document.querySelector("#savedStatus");
const refreshReportsButton = document.querySelector("#refreshReports");
const compareReportsButton = document.querySelector("#compareReports");
const runLiveSignalsButton = document.querySelector("#runLiveSignals");
const autoRefreshLiveSignals = document.querySelector("#autoRefreshLiveSignals");
const clearLiveLedgerButton = document.querySelector("#clearLiveLedger");
const applyLiveActionsButton = document.querySelector("#applyLiveActions");
const saveLiveLedgerButton = document.querySelector("#saveLiveLedger");
const addLiveHoldingButton = document.querySelector("#addLiveHolding");
const addCompletedTradeButton = document.querySelector("#addCompletedTrade");
const saveCompletedLedgerButton = document.querySelector("#saveCompletedLedger");
const saveLiveConfigButton = document.querySelector("#saveLiveConfig");
const saveDhanCredentialsButton = document.querySelector("#saveDhanCredentials");
const dhanClientId = document.querySelector("#dhanClientId");
const dhanAccessToken = document.querySelector("#dhanAccessToken");
const dhanCredentialStatus = document.querySelector("#dhanCredentialStatus");
const addLiveCapitalButton = document.querySelector("#addLiveCapital");
const saveLiveCapitalLedgerButton = document.querySelector("#saveLiveCapitalLedger");
const addSignalMappingButton = document.querySelector("#addSignalMapping");
const saveSignalMappingsButton = document.querySelector("#saveSignalMappings");
const liveStatus = document.querySelector("#liveStatus");
const liveMetrics = document.querySelector("#liveMetrics");
const liveLedgerMetrics = document.querySelector("#liveLedgerMetrics");
const liveMaxEtfs = document.querySelector("#liveMaxEtfs");
const liveMtfEnabled = document.querySelector("#liveMtfEnabled");
const liveMtfBroker = document.querySelector("#liveMtfBroker");
const liveMtfLiquidcase = document.querySelector("#liveMtfLiquidcase");
const liveMtfCashBufferPct = document.querySelector("#liveMtfCashBufferPct");
const liveMtfFundedMultiple = document.querySelector("#liveMtfFundedMultiple");
const liveMtfHaircutPct = document.querySelector("#liveMtfHaircutPct");
const liveMtfInterestAnnualPct = document.querySelector("#liveMtfInterestAnnualPct");
const liveCapitalBody = document.querySelector("#liveCapitalBody");
const savedSignalMappingBody = document.querySelector("#savedSignalMappingBody");
const liveActionsBody = document.querySelector("#liveActionsBody");
const liveSignalRowsBody = document.querySelector("#liveSignalRowsBody");
const liveHoldingsBody = document.querySelector("#liveHoldingsBody");
const liveBookedTradesBody = document.querySelector("#liveBookedTradesBody");
const priceMode = document.querySelector("#priceMode");
const priceTime = document.querySelector("#priceTime");
const priceTimeField = document.querySelector("#priceTimeField");
const strategyName = document.querySelector("#strategyName");
const emaWindow = document.querySelector("#emaWindow");
const emaWindowField = document.querySelector("#emaWindowField");
const rsiWindow = document.querySelector("#rsiWindow");
const rsiWindowField = document.querySelector("#rsiWindowField");
const atrWindow = document.querySelector("#atrWindow");
const atrWindowField = document.querySelector("#atrWindowField");
const atrMultiplier = document.querySelector("#atrMultiplier");
const atrMultiplierField = document.querySelector("#atrMultiplierField");
const confirmationDays = document.querySelector("#confirmationDays");
const confirmationDaysField = document.querySelector("#confirmationDaysField");
const candidateRanking = document.querySelector("#candidateRanking");
const rotateStrongCandidates = document.querySelector("#rotateStrongCandidates");
const compoundPositions = document.querySelector("#compoundPositions");
const mtfMode = document.querySelector("#mtfMode");
const extraCapitalLimitMultiplier = document.querySelector("#extraCapitalLimitMultiplier");
const maxOverflowPositions = document.querySelector("#maxOverflowPositions");
const extraCapitalInterestDaily = document.querySelector("#extraCapitalInterestDaily");
const monthlyCapitalAddition = document.querySelector("#monthlyCapitalAddition");
const withdrawalTarget = document.querySelector("#withdrawalTarget");
const monthlyWithdrawalAmount = document.querySelector("#monthlyWithdrawalAmount");
const signalSourceMode = document.querySelector("#signalSourceMode");
const globalSignalSource = document.querySelector("#globalSignalSource");
const globalSignalSourceField = document.querySelector("#globalSignalSourceField");
const signalSourceBody = document.querySelector("#signalSourceBody");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");
const backtestSubtabButtons = document.querySelectorAll(".backtest-subtab-button");
const backtestSubtabPanels = document.querySelectorAll(".backtest-subtab-panel");
const liveSubtabButtons = document.querySelectorAll(".live-subtab-button");
const liveSubtabPanels = document.querySelectorAll(".live-subtab-panel");
let SAVED_SIGNAL_SOURCES = window.ETF_BACKTESTER_SIGNAL_SOURCES || {};
const STORAGE_KEY = "etfBacktesterInputs";
let latestLiveReport = null;
let liveSignalRefreshTimer = null;
let liveSignalRefreshRunning = false;

function apiUrl(path) {
  const basePath = (window.BACKTESTER_BASE_PATH || "").replace(/\/$/, "");
  return `${basePath}${path}`;
}

function selectedSymbols() {
  return [...document.querySelectorAll("input[name='symbols']:checked")].map((input) => input.value);
}

function updateSelectedCount() {
  selectedCount.textContent = `${selectedSymbols().length} selected`;
  renderSignalSourceRows();
}

function setBusy(isBusy) {
  runButton.disabled = isBusy;
  runButton.textContent = isBusy ? "Running..." : "Run Backtest";
  if (isBusy) {
    statusText.textContent = "Fetching Yahoo data and simulating trades";
  }
}

function showTab(tabId) {
  tabButtons.forEach((button) => {
    const isActive = button.dataset.tabTarget === tabId;
    button.classList.toggle("is-active", isActive);
  });
  tabPanels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === tabId);
  });
}

function showLiveSubtab(tabId) {
  liveSubtabButtons.forEach((button) => {
    const isActive = button.dataset.liveTabTarget === tabId;
    button.classList.toggle("is-active", isActive);
  });
  liveSubtabPanels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === tabId);
  });
}

function showBacktestSubtab(tabId) {
  backtestSubtabButtons.forEach((button) => {
    const isActive = button.dataset.backtestTabTarget === tabId;
    button.classList.toggle("is-active", isActive);
  });
  backtestSubtabPanels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === tabId);
  });
}

function requestPayload() {
  const useDailyClose = priceMode.value === "daily_close";
  const symbols = selectedSymbols();
  return {
    symbols,
    initial_capital: Number(document.querySelector("#initialCapital").value),
    max_positions: Number(document.querySelector("#maxPositions").value),
    start_date: document.querySelector("#startDate").value,
    end_date: document.querySelector("#endDate").value,
    strategy: strategyName.value,
    ema_window: Number(emaWindow.value),
    atr_window: Number(atrWindow.value),
    atr_multiplier: Number(atrMultiplier.value),
    confirmation_days: Number(confirmationDays.value),
    rsi_window: Number(rsiWindow.value),
    price_time: useDailyClose ? null : priceTime.value,
    candidate_ranking: candidateRanking.value,
    rank_buy_candidates_by_ath: candidateRanking.value === "ath",
    rotate_to_stronger_candidates: rotateStrongCandidates.checked,
    compound_positions: compoundPositions.checked,
    mtf_mode: mtfMode.value,
    buy_all_overflow_signals: mtfMode.value === "overflow",
    extra_capital_limit_multiplier: Number(extraCapitalLimitMultiplier.value || 0),
    max_overflow_positions: Number(maxOverflowPositions.value || 0),
    extra_capital_interest_rate_daily: Number(extraCapitalInterestDaily.value || 0) / 100,
    monthly_capital_addition: Number(monthlyCapitalAddition.value || 0),
    withdrawal_target: Number(withdrawalTarget.value || 0),
    monthly_withdrawal_amount: Number(monthlyWithdrawalAmount.value || 0),
    signal_source_mode: signalSourceMode.value,
    signal_sources: signalSourcesPayload(symbols),
  };
}

function updatePriceMode() {
  const isDailyStrategy = ["ema_trend", "weekly_ema_cross", "rsi_50_cross", "rsi_divergence_staged", "ema_entry_low_sell", "ema_atr_confirmed", "ema_atr_sell_band"].includes(strategyName.value);
  if (isDailyStrategy) {
    priceMode.value = "daily_close";
  }
  const useDailyClose = priceMode.value === "daily_close";
  priceMode.disabled = isDailyStrategy;
  priceTime.disabled = useDailyClose;
  priceTimeField.classList.toggle("is-disabled", useDailyClose);
}

function updateRotationAvailability() {
  const hasRanking = candidateRanking.value !== "none";
  rotateStrongCandidates.disabled = !hasRanking;
  rotateStrongCandidates.closest(".toggle-field").classList.toggle("is-disabled", !hasRanking);
  if (!hasRanking) {
    rotateStrongCandidates.checked = false;
  }
}

function updateStrategyFields(preferMomentumRanking = false) {
  const isRsiStrategy = ["rsi_50_cross", "rsi_divergence_staged"].includes(strategyName.value);
  const isWeeklyEmaStrategy = strategyName.value === "weekly_ema_cross";
  const isAtrConfirmedStrategy = strategyName.value === "ema_atr_confirmed";
  const isAtrSellBandStrategy = strategyName.value === "ema_atr_sell_band";
  const isAtrStrategy = isAtrConfirmedStrategy || isAtrSellBandStrategy;
  emaWindow.disabled = isRsiStrategy;
  atrWindow.disabled = !isAtrStrategy;
  atrMultiplier.disabled = !isAtrStrategy;
  confirmationDays.disabled = !(isAtrConfirmedStrategy || isWeeklyEmaStrategy);
  rsiWindow.disabled = !isRsiStrategy;
  emaWindowField.classList.toggle("is-disabled", isRsiStrategy);
  atrWindowField.classList.toggle("is-disabled", !isAtrStrategy);
  atrMultiplierField.classList.toggle("is-disabled", !isAtrStrategy);
  confirmationDaysField.classList.toggle("is-disabled", !(isAtrConfirmedStrategy || isWeeklyEmaStrategy));
  rsiWindowField.classList.toggle("is-disabled", !isRsiStrategy);
  if (isWeeklyEmaStrategy) {
    confirmationDays.min = "2";
    confirmationDays.max = "3";
    if (!["2", "3"].includes(confirmationDays.value)) {
      confirmationDays.value = "2";
    }
  } else {
    confirmationDays.min = "1";
    confirmationDays.max = "20";
  }
  if (preferMomentumRanking && isAtrConfirmedStrategy) {
    candidateRanking.value = "momentum_20_60";
  }
  updateRotationAvailability();
  updatePriceMode();
}

function updateSignalSourceMode() {
  const isCustom = signalSourceMode.value === "custom";
  const isIndividual = signalSourceMode.value === "individual";
  globalSignalSource.disabled = !isCustom;
  globalSignalSourceField.classList.toggle("is-disabled", !isCustom);
  signalSourceBody.closest(".mapping-table-wrap").classList.toggle("is-disabled", !isIndividual);
  renderSignalSourceRows();
}

function renderSignalSourceRows() {
  if (!signalSourceBody) {
    return;
  }

  const existingValues = currentIndividualSignalSources();
  const isIndividual = signalSourceMode.value === "individual";
  signalSourceBody.innerHTML = selectedSymbols().map((symbol) => {
    const source = signalSourceForMode(symbol, existingValues);
    return `
      <tr>
        <td>${escapeHtml(symbol)}</td>
        <td>
          <input
            class="signal-source-input"
            data-symbol="${escapeHtml(symbol)}"
            type="text"
            value="${escapeHtml(source)}"
            ${isIndividual ? "" : "disabled"}
          >
        </td>
      </tr>
    `;
  }).join("");
}

function signalSourceForMode(symbol, existingValues) {
  if (signalSourceMode.value === "etf") {
    return symbol;
  }

  if (signalSourceMode.value === "saved") {
    return SAVED_SIGNAL_SOURCES[symbol] || symbol;
  }

  if (signalSourceMode.value === "custom") {
    return globalSignalSource.value.trim() || symbol;
  }

  return existingValues[symbol] || SAVED_SIGNAL_SOURCES[symbol] || symbol;
}

function currentIndividualSignalSources() {
  return [...signalSourceBody.querySelectorAll(".signal-source-input")].reduce((values, input) => {
    values[input.dataset.symbol] = input.value.trim();
    return values;
  }, {});
}

function signalSourcesPayload(symbols) {
  if (signalSourceMode.value === "etf") {
    return Object.fromEntries(symbols.map((symbol) => [symbol, symbol]));
  }

  if (signalSourceMode.value === "saved") {
    return Object.fromEntries(symbols.map((symbol) => [symbol, SAVED_SIGNAL_SOURCES[symbol] || symbol]));
  }

  if (signalSourceMode.value === "custom") {
    const source = globalSignalSource.value.trim();
    return Object.fromEntries(symbols.map((symbol) => [symbol, source || symbol]));
  }

  const individualSources = currentIndividualSignalSources();
  return Object.fromEntries(symbols.map((symbol) => [symbol, individualSources[symbol] || symbol]));
}

function saveInputs() {
  const payload = requestPayload();
  payload.price_mode = priceMode.value;
  payload.global_signal_source = globalSignalSource.value;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function restoreInputs() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) {
    return;
  }

  try {
    const payload = JSON.parse(saved);
    document.querySelector("#initialCapital").value = payload.initial_capital ?? document.querySelector("#initialCapital").value;
    document.querySelector("#maxPositions").value = payload.max_positions ?? document.querySelector("#maxPositions").value;
    document.querySelector("#startDate").value = payload.start_date ?? document.querySelector("#startDate").value;
    document.querySelector("#endDate").value = payload.end_date ?? document.querySelector("#endDate").value;
    strategyName.value = payload.strategy || "ema_trend";
    emaWindow.value = payload.ema_window ?? emaWindow.value;
    atrWindow.value = payload.atr_window ?? atrWindow.value;
    atrMultiplier.value = payload.atr_multiplier ?? atrMultiplier.value;
    confirmationDays.value = payload.confirmation_days ?? confirmationDays.value;
    rsiWindow.value = payload.rsi_window ?? rsiWindow.value;
    candidateRanking.value = payload.candidate_ranking || (payload.rank_buy_candidates_by_ath ? "ath" : "none");
    rotateStrongCandidates.checked = Boolean(payload.rotate_to_stronger_candidates);
    compoundPositions.checked = payload.compound_positions ?? true;
    mtfMode.value = payload.mtf_mode || (payload.buy_all_overflow_signals ? "overflow" : "off");
    extraCapitalLimitMultiplier.value = payload.extra_capital_limit_multiplier ?? extraCapitalLimitMultiplier.value;
    maxOverflowPositions.value = payload.max_overflow_positions ?? maxOverflowPositions.value;
    extraCapitalInterestDaily.value = payload.extra_capital_interest_rate_daily === undefined
      ? extraCapitalInterestDaily.value
      : Number(payload.extra_capital_interest_rate_daily) * 100;
    monthlyCapitalAddition.value = payload.monthly_capital_addition ?? monthlyCapitalAddition.value;
    withdrawalTarget.value = payload.withdrawal_target ?? withdrawalTarget.value;
    monthlyWithdrawalAmount.value = payload.monthly_withdrawal_amount ?? monthlyWithdrawalAmount.value;
    priceMode.value = payload.price_mode || (payload.price_time ? "time" : "daily_close");
    if (payload.price_time) {
      priceTime.value = payload.price_time;
    }
    signalSourceMode.value = payload.signal_source_mode || "etf";
    globalSignalSource.value = payload.global_signal_source || "";
    document.querySelectorAll("input[name='symbols']").forEach((input) => {
      input.checked = Array.isArray(payload.symbols) && payload.symbols.includes(input.value);
    });
    updateSelectedCount();
    updateSignalSourceMode();
    if (payload.signal_source_mode === "individual" && payload.signal_sources && typeof payload.signal_sources === "object") {
      signalSourceBody.querySelectorAll(".signal-source-input").forEach((input) => {
        if (Object.prototype.hasOwnProperty.call(payload.signal_sources, input.dataset.symbol)) {
          input.value = payload.signal_sources[input.dataset.symbol];
        }
      });
    }
  } catch {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function renderSummary(summary) {
  const rows = summary.split("\n").map((line) => {
    const separatorIndex = line.indexOf(":");
    if (separatorIndex === -1) {
      return null;
    }
    return {
      label: line.slice(0, separatorIndex),
      value: line.slice(separatorIndex + 1).trim(),
    };
  }).filter(Boolean);

  metrics.innerHTML = rows.map((row) => `
    <div class="metric">
      <span>${escapeHtml(row.label)}</span>
      <strong>${escapeHtml(row.value)}</strong>
    </div>
  `).join("");
}

function renderTrades(trades, tradeLedger = null) {
  const ledgerRows = (tradeLedger || buildBacktestTradeLedger(trades)).slice().reverse();
  tradesBody.innerHTML = ledgerRows.map((trade) => `
    <tr>
      <td>${escapeHtml(trade.status || "")}</td>
      <td>${escapeHtml(trade.symbol || "")}</td>
      <td>${escapeHtml(trade.buy_date || "")}</td>
      <td>${escapeHtml(trade.buy_time || "")}</td>
      <td>${formatMoney(trade.buy_price || 0)}</td>
      <td>${Number(trade.quantity || 0).toFixed(0)}</td>
      <td>${formatMoney(trade.total_invested || 0)}</td>
      <td>${escapeHtml(trade.sell_date || "")}</td>
      <td>${escapeHtml(trade.sell_time || "")}</td>
      <td>${trade.sell_price === null || trade.sell_price === undefined || trade.sell_price === "" ? "" : formatMoney(trade.sell_price)}</td>
      <td>${trade.total_sold === null || trade.total_sold === undefined || trade.total_sold === "" ? "" : formatMoney(trade.total_sold)}</td>
      <td class="${Number(trade.realized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${trade.realized_profit === null || trade.realized_profit === undefined ? "" : formatMoney(trade.realized_profit || 0)}</td>
      <td class="${Number(trade.profit_pct || 0) >= 0 ? "profit-positive" : "profit-negative"}">${trade.profit_pct === null || trade.profit_pct === undefined ? "" : formatPercent(trade.profit_pct || 0)}</td>
      <td>${trade.holding_days === null || trade.holding_days === undefined ? "" : escapeHtml(trade.holding_days)}</td>
      <td>${trade.entry_low === null || trade.entry_low === undefined ? "" : Number(trade.entry_low).toFixed(2)}</td>
      <td>${trade.entry_ema === null || trade.entry_ema === undefined ? "" : Number(trade.entry_ema).toFixed(2)}</td>
      <td>${escapeHtml(trade.reason || "")}</td>
    </tr>
  `).join("");
}

function buildBacktestTradeLedger(trades) {
  const openBuys = {};
  const ledger = [];
  (trades || []).forEach((trade) => {
    const symbol = trade.symbol || "";
    const side = String(trade.side || "").toUpperCase();
    if (side === "BUY") {
      if (!openBuys[symbol]) {
        openBuys[symbol] = [];
      }
      openBuys[symbol].push(trade);
      return;
    }

    if (side !== "SELL" || !openBuys[symbol]?.length) {
      return;
    }

    const buy = openBuys[symbol].shift();
    const quantity = Number(trade.shares || buy.shares || 0);
    const totalInvested = tradeValueOrDefault(buy, quantity);
    const totalSold = tradeValueOrDefault(trade, quantity);
    const realizedProfit = Number(trade.profit ?? (totalSold - totalInvested));
    ledger.push({
      status: "Closed",
      symbol,
      buy_date: buy.date || "",
      buy_time: buy.time || "",
      buy_price: Number(buy.price || 0),
      quantity,
      total_invested: totalInvested,
      sell_date: trade.date || "",
      sell_time: trade.time || "",
      sell_price: Number(trade.price || 0),
      total_sold: totalSold,
      realized_profit: realizedProfit,
      profit_pct: totalInvested > 0 ? realizedProfit / totalInvested : 0,
      holding_days: trade.holding_days ?? "",
      entry_low: trade.entry_low ?? buy.entry_low,
      entry_ema: trade.entry_ema ?? buy.entry_ema,
      reason: trade.reason || "",
    });
  });

  Object.entries(openBuys).forEach(([symbol, buys]) => {
    buys.forEach((buy) => {
      const quantity = Number(buy.shares || 0);
      ledger.push({
        status: "Open",
        symbol,
        buy_date: buy.date || "",
        buy_time: buy.time || "",
        buy_price: Number(buy.price || 0),
        quantity,
        total_invested: tradeValueOrDefault(buy, quantity),
        sell_date: "",
        sell_time: "",
        sell_price: null,
        total_sold: null,
        realized_profit: null,
        profit_pct: null,
        holding_days: "",
        entry_low: buy.entry_low,
        entry_ema: buy.entry_ema,
        reason: "",
      });
    });
  });

  return ledger;
}

function tradeValueOrDefault(trade, quantity) {
  const value = Number(trade.value || 0);
  return value > 0 ? value : quantity * Number(trade.price || 0);
}

function renderOpenPositions(openPositions) {
  openPositionsBody.innerHTML = openPositions.map((position) => `
    <tr>
      <td>${escapeHtml(position.symbol)}</td>
      <td>${escapeHtml(position.entry_date || "")}</td>
      <td>${Number(position.holding_days || 0)}</td>
      <td>${Number(position.shares || 0).toFixed(0)}</td>
      <td>${formatMoney(position.entry_price || 0)}</td>
      <td>${formatMoney(position.last_price || 0)}</td>
      <td>${formatMoney(position.market_value || 0)}</td>
      <td class="${Number(position.unrealized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(position.unrealized_profit || 0)}</td>
    </tr>
  `).join("");
}

function renderPerSymbolReport(rows) {
  perSymbolBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.symbol)}</td>
      <td class="${Number(row.realized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(row.realized_profit || 0)}</td>
      <td class="${Number(row.unrealized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(row.unrealized_profit || 0)}</td>
      <td class="${Number(row.total_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(row.total_profit || 0)}</td>
      <td>${Number(row.closed_trades || 0)}</td>
      <td>${Number(row.open_quantity || 0).toFixed(0)}</td>
      <td>${Number(row.min_holding_days || 0)}</td>
      <td>${Number(row.max_holding_days || 0)}</td>
    </tr>
  `).join("");
}

function renderPeriodReturns(frequency, rows) {
  periodReportTitle.textContent = frequency === "yearly" ? "Yearly Profit" : "Monthly Profit";
  periodReturnsBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.period)}</td>
      <td>${formatMoney(row.start_equity)}</td>
      <td>${formatMoney(row.end_equity)}</td>
      <td class="${Number(row.profit) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(row.profit)}</td>
      <td>${formatPercent(row.return_pct)}</td>
    </tr>
  `).join("");
}

function renderCapitalFlows(rows) {
  const capitalRows = (rows || []).filter((row) => {
    const reason = String(row.reason || "");
    return reason === "initial_capital"
      || reason === "monthly_capital_addition"
      || reason === "monthly_target_withdrawal"
      || reason === "target_withdrawal";
  });

  capitalFlowsBody.innerHTML = capitalRows.map((row) => {
    const amount = Number(row.amount || 0);
    return `
      <tr>
        <td>${escapeHtml(row.date || "")}</td>
        <td>${escapeHtml(capitalFlowLabel(row.reason || ""))}</td>
        <td class="${amount >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(amount)}</td>
      </tr>
    `;
  }).join("");
}

function capitalFlowLabel(reason) {
  if (reason === "initial_capital") {
    return "Initial Capital";
  }
  if (reason === "monthly_capital_addition") {
    return "Capital Addition";
  }
  if (reason === "monthly_target_withdrawal" || reason === "target_withdrawal") {
    return "Withdrawal";
  }
  return reason;
}

function renderSavedReports(reports) {
  savedReportsBody.innerHTML = reports.map((report) => `
    <tr>
      <td><input type="checkbox" class="report-compare" value="${escapeHtml(report.id)}"></td>
      <td>${escapeHtml(report.saved_at || "")}</td>
      <td>${escapeHtml(report.condition_identifier || "")}</td>
      <td>${escapeHtml(report.start_date || "")} to ${escapeHtml(report.end_date || "")}</td>
      <td>${Number(report.symbols_count || 0)}</td>
      <td>${formatMoney(report.ending_equity || 0)}</td>
      <td>${formatPercent(report.cagr || 0)}</td>
      <td>${formatOptionalPercent(report.xirr)}</td>
      <td><button class="ghost-button open-report" type="button" data-report-id="${escapeHtml(report.id)}">Open</button></td>
    </tr>
  `).join("");
  savedStatus.textContent = `${reports.length} saved report${reports.length === 1 ? "" : "s"}`;
}

async function refreshReports() {
  const response = await fetch(apiUrl("/api/reports"));
  const data = await response.json();
  renderSavedReports(data.reports || []);
}

async function openReport(reportId) {
  const response = await fetch(apiUrl(`/api/reports/${encodeURIComponent(reportId)}`));
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not open report.");
  }

  renderSummary(data.summary || "");
  renderPeriodReturns(data.period_report_frequency, data.period_returns || []);
  renderCapitalFlows(data.capital_flows || []);
  renderTrades(data.trades || [], data.trade_ledger || null);
  renderOpenPositions(data.open_positions || []);
  renderPerSymbolReport(data.per_symbol_report || []);
  message.textContent = `Opened saved report: ${reportId}`;
  statusText.textContent = "Saved report loaded";
  showTab("setupTab");
  showBacktestSubtab("resultsTab");
}

async function compareSelectedReports() {
  const selectedIds = [...document.querySelectorAll(".report-compare:checked")].map((input) => input.value);
  if (!selectedIds.length) {
    savedStatus.textContent = "Select reports to compare.";
    return;
  }

  const reports = await Promise.all(selectedIds.map(async (reportId) => {
    const response = await fetch(apiUrl(`/api/reports/${encodeURIComponent(reportId)}`));
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Could not open ${reportId}`);
    }
    return {id: reportId, data};
  }));

  compareBody.innerHTML = reports.map(({id, data}) => {
    const summary = parseSummary(data.summary || "");
    const config = data.config || {};
    const equityCurve = data.equity_curve || [];
    const endEquity = equityCurve.length ? equityCurve[equityCurve.length - 1].equity : 0;
    return `
      <tr>
        <td>${escapeHtml(id)}</td>
        <td>${escapeHtml(data.condition_identifier || "")}</td>
        <td>${escapeHtml(config.start_date || "")} to ${escapeHtml(config.end_date || "")}</td>
        <td>${Array.isArray(config.symbols) ? config.symbols.length : 0}</td>
        <td>${formatMoney(endEquity)}</td>
        <td>${formatMoney(data.realized_profit || 0)}</td>
        <td>${formatMoney(data.unrealized_profit || 0)}</td>
        <td>${formatPercent(data.cagr || 0)}</td>
        <td>${formatOptionalPercent(data.xirr) || escapeHtml(summary["XIRR"] || "")}</td>
        <td>${escapeHtml(summary["Total return"] || "")}</td>
        <td>${Array.isArray(data.trades) ? data.trades.length : 0}</td>
      </tr>
    `;
  }).join("");
  savedStatus.textContent = `Comparing ${reports.length} report${reports.length === 1 ? "" : "s"}`;
}

async function fetchLiveReport() {
  const response = await fetch(apiUrl("/api/live/report"));
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not load live report.");
  }
  renderLiveReport(data.report);
}

async function runLiveSignals(applyActions = false) {
  if (!applyActions && liveSignalRefreshRunning) {
    return;
  }
  liveSignalRefreshRunning = true;
  liveStatus.textContent = applyActions ? "Applying live actions..." : "Generating live signals...";
  try {
    const selectedActionIds = applyActions ? selectedLiveActionIds() : undefined;
    const response = await fetch(apiUrl("/api/live/run"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        apply_actions: applyActions,
        selected_action_ids: selectedActionIds,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Live signal run failed.");
    }

    renderLiveReport(data.report);
    liveStatus.textContent = `${applyActions ? "Applied" : "Generated"} live report: ${data.report_path}`;
  } finally {
    liveSignalRefreshRunning = false;
  }
}

function setLiveSignalAutoRefresh(enabled) {
  if (liveSignalRefreshTimer) {
    window.clearInterval(liveSignalRefreshTimer);
    liveSignalRefreshTimer = null;
  }
  if (!enabled) {
    return;
  }
  liveSignalRefreshTimer = window.setInterval(() => {
    runLiveSignals(false).catch((error) => {
      liveStatus.textContent = `Auto refresh failed: ${error.message}`;
    });
  }, 5 * 60 * 1000);
}

async function clearLiveLedger(statusTarget = liveStatus) {
  if (!window.confirm("Clear all live holdings, cash state, and recorded live trades for a fresh test?")) {
    return;
  }

  statusTarget.textContent = "Clearing live holdings...";
  const response = await fetch(apiUrl("/api/live/clear"), {method: "POST"});
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not clear live holdings.");
  }

  latestLiveReport = null;
  renderLiveReport(null);
  statusTarget.textContent = "Live holdings cleared.";
}

function renderLiveReport(report) {
  latestLiveReport = report;
  if (!report) {
    liveMetrics.innerHTML = "";
    liveActionsBody.innerHTML = "";
    liveSignalRowsBody.innerHTML = "";
    liveHoldingsBody.innerHTML = "";
    liveBookedTradesBody.innerHTML = "";
    liveLedgerMetrics.innerHTML = "";
    liveStatus.textContent = "No live report yet.";
    return;
  }

  renderLiveMetrics(report, liveMetrics);
  renderLiveActions(report, liveActionsBody, true);
  renderLiveSignalRows(report, liveSignalRowsBody);
  renderLiveHoldings(report, liveHoldingsBody, true);
  renderCompletedTrades(report, liveBookedTradesBody, true);
  renderLiveLedgerMetrics(report, liveLedgerMetrics);
  liveStatus.textContent = `Latest live report: ${report.run_date || ""} ${report.signal_time || ""}`;
}

function renderLiveMetrics(report, target) {
  target.innerHTML = [
    {label: "Mode", value: report.mode || ""},
    {label: "Cash", value: formatMoney(report.cash || 0)},
    {label: "Equity", value: formatMoney(report.equity || 0)},
    {label: "XIRR", value: formatOptionalPercent(report.xirr)},
    {label: "Capital Base", value: formatMoney(report.capital_base || report.config?.initial_capital || 0)},
    {label: "Max ETFs", value: Number(report.config?.max_positions || 0)},
    {label: "MTF Loan", value: formatMoney(report.mtf?.loan_balance || 0)},
    {label: "MTF Limit", value: formatMoney(report.mtf?.limit || 0)},
    {label: "MTF Available", value: formatMoney(report.mtf?.available || 0)},
    {label: "Cash Buffer Req.", value: formatMoney(report.mtf?.required_cash_buffer || 0)},
    {label: "Daily Interest", value: formatMoney(report.mtf?.daily_interest || 0)},
    {label: "Completed Trades", value: Number((report.completed_trades || []).length)},
    {label: "Run Date", value: report.run_date || ""},
    {label: "Signal Time", value: report.signal_time || ""},
    {label: "Price Source", value: report.price_note || ""},
    {label: "Strategy", value: report.config?.strategy || ""},
  ].map((row) => `
    <div class="metric">
      <span>${escapeHtml(row.label)}</span>
      <strong>${escapeHtml(row.value)}</strong>
    </div>
  `).join("");

  if (target === liveMetrics) {
    renderCapitalLedger(report.capital_adjustments || []);
    if (liveMaxEtfs && report.config?.max_positions) {
      liveMaxEtfs.value = report.config.max_positions;
    }
    populateLiveMtfConfig(report.config || {});
  }
}

function populateLiveMtfConfig(config) {
  if (liveMtfEnabled) liveMtfEnabled.checked = Boolean(config.mtf_enabled);
  if (liveMtfBroker) liveMtfBroker.value = config.mtf_broker || "ICICI Direct Prime 4999";
  if (liveMtfLiquidcase) liveMtfLiquidcase.value = Number(config.mtf_pledged_liquidcase_value || 0);
  if (liveMtfCashBufferPct) liveMtfCashBufferPct.value = Number(config.mtf_cash_buffer_pct ?? 20);
  if (liveMtfFundedMultiple) liveMtfFundedMultiple.value = Number(config.mtf_funded_multiple ?? 3);
  if (liveMtfHaircutPct) liveMtfHaircutPct.value = Number(config.mtf_collateral_haircut_pct ?? 6);
  if (liveMtfInterestAnnualPct) liveMtfInterestAnnualPct.value = Number(config.mtf_interest_rate_annual_pct ?? 9.65);
}

function renderCapitalLedger(rows) {
  liveCapitalBody.innerHTML = (rows || []).slice().reverse().map((row) => `
    <tr class="capital-adjustment-row">
      <td>${ledgerInput("date", row.date || "", "date")}</td>
      <td>${ledgerInput("amount", Number(row.amount || 0), "number")}</td>
      <td>${ledgerInput("note", row.note || "", "text")}</td>
      <td>${escapeHtml(row.created_at || "")}</td>
      <td><button class="icon-button remove-ledger-row" type="button">x</button></td>
    </tr>
  `).join("");
}

function liveActionSelectionValue(action, index) {
  return action.id || `index:${index}`;
}

function renderLiveActions(report, target, includeApplyColumn, checkboxClass = "live-action-select") {
  target.innerHTML = (report.actions || []).map((action, index) => `
    <tr>
      ${includeApplyColumn ? `<td>
        <input
          class="${checkboxClass}"
          type="checkbox"
          value="${escapeHtml(liveActionSelectionValue(action, index))}"
          data-action-id="${escapeHtml(action.id || "")}"
          data-action-index="${index}"
          ${report.mode === "applied" ? "disabled" : "checked"}
        >
      </td>` : ""}
      <td><span class="side ${String(action.side).toLowerCase()}">${escapeHtml(action.side)}</span></td>
      <td>${escapeHtml(action.symbol)}</td>
      <td>${escapeHtml(action.signal_date || "")}</td>
      <td>${escapeHtml(action.time || "")}</td>
      <td>${formatMoney(action.price || 0)}</td>
      <td>${Number(action.shares || 0).toFixed(0)}</td>
      <td>${formatMoney(action.value || 0)}</td>
      <td>${escapeHtml(action.funding_mode || "delivery")}</td>
      <td>${formatMoney(action.mtf_loan || action.mtf_loan_repayment || 0)}</td>
      <td>${formatMoney(action.cash_required ?? action.cash_delta ?? action.value ?? 0)}</td>
      <td>${formatOptionalPercent(action.ath_distance_pct)}</td>
      <td>${escapeHtml(action.reason || "")}</td>
    </tr>
  `).join("");
}

function renderLiveSignalRows(report, target) {
  target.innerHTML = (report.signal_rows || []).map((row) => `
    <tr>
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.signal_source || "")}</td>
      <td><span class="side ${String(row.signal_label || "hold").toLowerCase()}">${escapeHtml(row.signal_label || "")}</span></td>
      <td>${escapeHtml(row.signal_date || "")}</td>
      <td>${formatOptionalMoney(row.source_price)}</td>
      <td>${formatOptionalMoney(row.source_ema)}</td>
      <td>${escapeHtml(row.time || "")}</td>
      <td>${formatOptionalMoney(row.price)}</td>
      <td>${escapeHtml(row.ath_source || "")}</td>
      <td>${formatOptionalMoney(row.ath_current_price)}</td>
      <td>${formatOptionalMoney(row.ath_price)}</td>
      <td>${formatOptionalPercent(row.ath_distance_pct)}</td>
      <td>${escapeHtml(row.selected_action || "")}</td>
      <td>${row.is_held ? "Yes" : ""}</td>
    </tr>
  `).join("");
}

function renderLiveHoldings(report, target, editable = false) {
  target.innerHTML = (report.holdings || []).map((holding) => `
    <tr class="live-holding-row">
      <td>${editable ? ledgerInput("symbol", holding.symbol || "", "text") : escapeHtml(holding.symbol)}</td>
      <td>${editable ? ledgerInput("entry_date", holding.entry_date || "", "date") : escapeHtml(holding.entry_date || "")}</td>
      <td>${editable ? ledgerInput("shares", Number(holding.shares || 0).toFixed(0), "number") : Number(holding.shares || 0).toFixed(0)}</td>
      <td>${editable ? ledgerInput("entry_price", Number(holding.entry_price || 0).toFixed(2), "number") : formatMoney(holding.entry_price || 0)}</td>
      <td>${editable ? ledgerInput("cost_basis", Number(holding.cost_basis || holding.market_value || 0).toFixed(2), "number") : formatMoney(holding.cost_basis || holding.market_value || 0)}</td>
      <td>${formatMoney(holding.last_price || 0)}</td>
      <td>${formatMoney(holding.market_value || 0)}</td>
      <td class="${Number(holding.unrealized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(holding.unrealized_profit || 0)}</td>
      <td class="${Number(holding.unrealized_profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatPercent(liveHoldingReturn(holding))}</td>
      <td>${editable ? ledgerInput("funding_mode", holding.funding_mode || "delivery", "text") : escapeHtml(holding.funding_mode || "delivery")}</td>
      <td>${editable ? ledgerInput("mtf_loan", Number(holding.mtf_loan || 0).toFixed(2), "number") : formatMoney(holding.mtf_loan || 0)}</td>
      <td>${Number(holding.signal || 0)}</td>
      <td>${editable ? `<button class="icon-button remove-ledger-row" type="button">x</button>` : ""}</td>
    </tr>
  `).join("");
}

function renderCompletedTrades(report, target, editable = false) {
  const trades = (report.completed_trades || []).slice().reverse();
  target.innerHTML = trades.map((trade) => `
    <tr class="completed-trade-row">
      <td>${editable ? ledgerInput("symbol", trade.symbol || "", "text") : escapeHtml(trade.symbol || "")}</td>
      <td>${editable ? ledgerInput("buy_date", trade.buy_date || "", "date") : escapeHtml(trade.buy_date || "")}</td>
      <td>${editable ? ledgerInput("buy_price", Number(trade.buy_price || 0).toFixed(2), "number") : formatMoney(trade.buy_price || 0)}</td>
      <td>${editable ? ledgerInput("sell_date", trade.sell_date || "", "date") : escapeHtml(trade.sell_date || "")}</td>
      <td>${editable ? ledgerInput("sell_price", Number(trade.sell_price || 0).toFixed(2), "number") : formatMoney(trade.sell_price || 0)}</td>
      <td>${editable ? ledgerInput("shares", Number(trade.shares || 0).toFixed(0), "number") : Number(trade.shares || 0).toFixed(0)}</td>
      <td>${editable ? ledgerInput("buy_value", Number(trade.buy_value || 0).toFixed(2), "number") : formatMoney(trade.buy_value || 0)}</td>
      <td>${editable ? ledgerInput("sell_value", Number(trade.sell_value || 0).toFixed(2), "number") : formatMoney(trade.sell_value || 0)}</td>
      <td class="${Number(trade.profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(trade.profit || 0)}</td>
      <td class="${Number(trade.return_pct || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatPercent(trade.return_pct || 0)}</td>
      <td class="${Number(trade.return_pct || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatOptionalPercent(tradeCagr(trade))}</td>
      <td class="${Number(trade.profit || 0) >= 0 ? "profit-positive" : "profit-negative"}">${formatMoney(tradeMonthlyProfit(trade))}</td>
      <td>${trade.holding_days === null || trade.holding_days === undefined ? "" : Number(trade.holding_days)}</td>
      <td>${editable ? ledgerInput("reason", trade.reason || "manual", "text") : escapeHtml(trade.reason || "")}</td>
      ${editable ? `<td><button class="icon-button remove-ledger-row" type="button">x</button></td>` : ""}
    </tr>
  `).join("");
}

function renderLiveLedgerMetrics(report, target) {
  if (!target) {
    return;
  }

  const stats = liveLedgerStats(report);
  target.innerHTML = [
    {label: "Realized Profit", value: formatMoney(stats.realizedProfit)},
    {label: "CAGR", value: formatOptionalPercent(stats.cagr)},
    {label: "Monthly Profit", value: formatMoney(stats.monthlyProfit)},
    {label: "Completed Trades", value: stats.completedTrades},
  ].map((row) => `
    <div class="metric">
      <span>${escapeHtml(row.label)}</span>
      <strong>${escapeHtml(row.value)}</strong>
    </div>
  `).join("");
}

function liveLedgerStats(report) {
  const trades = report.completed_trades || [];
  const realizedProfit = trades.reduce((total, trade) => total + Number(trade.profit || 0), 0);
  const dateValues = trades.flatMap((trade) => [trade.buy_date, trade.sell_date])
    .map((value) => Date.parse(value))
    .filter((value) => Number.isFinite(value));
  const firstDate = dateValues.length ? Math.min(...dateValues) : null;
  const lastDate = dateValues.length ? Math.max(...dateValues) : null;
  const days = firstDate !== null && lastDate !== null ? Math.max((lastDate - firstDate) / 86400000, 1) : 0;
  const capitalBase = Number(report.capital_base || report.config?.initial_capital || 0);
  const totalReturn = capitalBase > 0 ? realizedProfit / capitalBase : null;
  const cagr = days > 0 && totalReturn !== null && 1 + totalReturn > 0 ? Math.pow(1 + totalReturn, 365 / days) - 1 : null;
  const monthlyProfit = days > 0 ? realizedProfit / Math.max(days / 30.4375, 1) : realizedProfit;
  return {
    realizedProfit,
    cagr,
    monthlyProfit,
    completedTrades: trades.length,
  };
}

function liveHoldingReturn(holding) {
  const costBasis = Number(holding.cost_basis || 0);
  return costBasis > 0 ? Number(holding.unrealized_profit || 0) / costBasis : 0;
}

function tradeCagr(trade) {
  const holdingDays = Number(trade.holding_days || 0);
  const returnPct = Number(trade.return_pct || 0);
  if (holdingDays <= 0) {
    return null;
  }
  if (1 + returnPct <= 0) {
    return null;
  }
  return Math.pow(1 + returnPct, 365 / holdingDays) - 1;
}

function tradeMonthlyProfit(trade) {
  const holdingDays = Number(trade.holding_days || 0);
  const months = holdingDays > 0 ? Math.max(holdingDays / 30.4375, 1) : 1;
  return Number(trade.profit || 0) / months;
}

function ledgerInput(field, value, type) {
  return `<input class="ledger-input" data-field="${field}" type="${type}" value="${escapeHtml(String(value ?? ""))}" ${type === "number" ? "step=\"any\"" : ""}>`;
}

function addLiveHoldingRow() {
  liveHoldingsBody.insertAdjacentHTML("afterbegin", `
    <tr class="live-holding-row">
      <td>${ledgerInput("symbol", "", "text")}</td>
      <td>${ledgerInput("entry_date", localDateValue(new Date()), "date")}</td>
      <td>${ledgerInput("shares", "0", "number")}</td>
      <td>${ledgerInput("entry_price", "0", "number")}</td>
      <td>${ledgerInput("cost_basis", "0", "number")}</td>
      <td></td><td></td><td></td><td></td>
      <td>${ledgerInput("funding_mode", "delivery", "text")}</td>
      <td>${ledgerInput("mtf_loan", "0", "number")}</td>
      <td>0</td>
      <td><button class="icon-button remove-ledger-row" type="button">x</button></td>
    </tr>
  `);
}

function addCompletedTradeRow() {
  liveBookedTradesBody.insertAdjacentHTML("afterbegin", `
    <tr class="completed-trade-row">
      <td>${ledgerInput("symbol", "", "text")}</td>
      <td>${ledgerInput("buy_date", localDateValue(new Date()), "date")}</td>
      <td>${ledgerInput("buy_price", "0", "number")}</td>
      <td>${ledgerInput("sell_date", localDateValue(new Date()), "date")}</td>
      <td>${ledgerInput("sell_price", "0", "number")}</td>
      <td>${ledgerInput("shares", "0", "number")}</td>
      <td>${ledgerInput("buy_value", "0", "number")}</td>
      <td>${ledgerInput("sell_value", "0", "number")}</td>
      <td></td><td></td><td></td><td></td><td></td>
      <td>${ledgerInput("reason", "manual", "text")}</td>
      <td><button class="icon-button remove-ledger-row" type="button">x</button></td>
    </tr>
  `);
}

function collectRows(target, rowClass) {
  return [...target.querySelectorAll(`.${rowClass}`)].map((row) => {
    const data = {};
    row.querySelectorAll(".ledger-input").forEach((input) => {
      data[input.dataset.field] = input.value;
    });
    return data;
  }).filter((row) => row.symbol && row.symbol.trim());
}

async function saveLiveLedger() {
  liveStatus.textContent = "Saving live ledger...";
  const response = await fetch(apiUrl("/api/live/ledger"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      holdings: collectRows(liveHoldingsBody, "live-holding-row"),
      completed_trades: collectRows(liveBookedTradesBody, "completed-trade-row"),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not save live ledger.");
  }
  await fetchLiveReport();
  liveStatus.textContent = "Live ledger saved.";
}

async function fetchLiveConfig() {
  const response = await fetch(apiUrl("/api/live/config"));
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not load live config.");
  }
  if (liveMaxEtfs) {
    liveMaxEtfs.value = data.config?.max_positions || "";
  }
  populateLiveMtfConfig(data.config || {});
}

async function fetchDhanCredentials() {
  const response = await fetch(apiUrl("/api/live/dhan-credentials"));
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not load Dhan credentials.");
  }

  const credentials = data.credentials || {};
  if (dhanClientId && credentials.client_id) {
    dhanClientId.value = credentials.client_id;
  }
  if (dhanAccessToken) {
    dhanAccessToken.value = "";
  }
  if (dhanCredentialStatus) {
    dhanCredentialStatus.textContent = credentials.configured
      ? `Dhan credentials saved for client ${credentials.masked_client_id || credentials.client_id}.`
      : "Dhan credentials are not saved yet.";
  }
}

async function saveDhanCredentials() {
  if (!dhanAccessToken.value.trim()) {
    dhanCredentialStatus.textContent = "Paste a Dhan access token first.";
    return;
  }

  dhanCredentialStatus.textContent = "Saving Dhan credentials...";
  const response = await fetch(apiUrl("/api/live/dhan-credentials"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      client_id: dhanClientId.value.trim(),
      access_token: dhanAccessToken.value.trim(),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not save Dhan credentials.");
  }

  dhanAccessToken.value = "";
  const credentials = data.credentials || {};
  if (credentials.client_id) {
    dhanClientId.value = credentials.client_id;
  }
  dhanCredentialStatus.textContent = `Dhan credentials saved for client ${credentials.masked_client_id || credentials.client_id}.`;
}

async function saveLiveConfig() {
  liveStatus.textContent = "Saving live config...";
  const response = await fetch(apiUrl("/api/live/config"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      max_positions: Number(liveMaxEtfs.value),
      mtf_enabled: Boolean(liveMtfEnabled?.checked),
      mtf_broker: liveMtfBroker?.value || "ICICI Direct Prime 4999",
      mtf_pledged_liquidcase_value: Number(liveMtfLiquidcase?.value || 0),
      mtf_cash_buffer_pct: Number(liveMtfCashBufferPct?.value || 0),
      mtf_funded_multiple: Number(liveMtfFundedMultiple?.value || 0),
      mtf_collateral_haircut_pct: Number(liveMtfHaircutPct?.value || 0),
      mtf_interest_rate_annual_pct: Number(liveMtfInterestAnnualPct?.value || 0),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not save live config.");
  }
  liveMaxEtfs.value = data.config.max_positions;
  populateLiveMtfConfig(data.config || {});
  await fetchLiveReport();
  liveStatus.textContent = "Live config saved.";
}

function addLiveCapitalRow() {
  liveCapitalBody.insertAdjacentHTML("afterbegin", `
    <tr class="capital-adjustment-row">
      <td>${ledgerInput("date", localDateValue(new Date()), "date")}</td>
      <td>${ledgerInput("amount", "0", "number")}</td>
      <td>${ledgerInput("note", "", "text")}</td>
      <td></td>
      <td><button class="icon-button remove-ledger-row" type="button">x</button></td>
    </tr>
  `);
}

function collectCapitalRows() {
  return [...liveCapitalBody.querySelectorAll(".capital-adjustment-row")].map((row) => {
    const data = {};
    row.querySelectorAll(".ledger-input").forEach((input) => {
      data[input.dataset.field] = input.value;
    });
    return data;
  }).filter((row) => row.date && Number(row.amount || 0) !== 0);
}

async function saveLiveCapitalLedger() {
  liveStatus.textContent = "Saving capital ledger...";
  const response = await fetch(apiUrl("/api/live/capital-ledger"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({capital_adjustments: collectCapitalRows()}),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not save capital ledger.");
  }
  await fetchLiveReport();
  liveStatus.textContent = "Capital ledger saved.";
}

async function fetchSignalMappings() {
  const response = await fetch(apiUrl("/api/signal-sources"));
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not load signal mappings.");
  }
  SAVED_SIGNAL_SOURCES = data.signal_sources || {};
  renderSavedSignalMappingRows();
  renderSignalSourceRows();
}

function renderSavedSignalMappingRows() {
  const rows = Object.entries(SAVED_SIGNAL_SOURCES).sort(([left], [right]) => left.localeCompare(right));
  savedSignalMappingBody.innerHTML = rows.map(([symbol, source]) => signalMappingRow(symbol, source)).join("");
}

function signalMappingRow(symbol = "", source = "") {
  return `
    <tr class="saved-signal-mapping-row">
      <td>${ledgerInput("symbol", symbol, "text")}</td>
      <td>${ledgerInput("source", source, "text")}</td>
      <td><button class="icon-button remove-ledger-row" type="button">x</button></td>
    </tr>
  `;
}

function addSignalMappingRow() {
  savedSignalMappingBody.insertAdjacentHTML("afterbegin", signalMappingRow());
}

async function saveSignalMappings() {
  liveStatus.textContent = "Saving signal mappings...";
  const mapping = {};
  collectRows(savedSignalMappingBody, "saved-signal-mapping-row").forEach((row) => {
    mapping[row.symbol.trim().toUpperCase()] = row.source.trim().toUpperCase();
  });
  const response = await fetch(apiUrl("/api/signal-sources"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({signal_sources: mapping}),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Could not save signal mappings.");
  }
  SAVED_SIGNAL_SOURCES = data.signal_sources || {};
  renderSavedSignalMappingRows();
  renderSignalSourceRows();
  liveStatus.textContent = "Signal mappings saved.";
}

function selectedLiveActionIds() {
  return [...liveActionsBody.querySelectorAll(".live-action-select")]
    .filter((input) => input.checked)
    .map((input) => input.value || input.dataset.actionId || `index:${input.dataset.actionIndex}`)
    .filter(Boolean);
}

function localDateValue(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initSortableTables() {
  document.querySelectorAll(".table-wrap table").forEach((table) => {
    table.querySelectorAll("thead th").forEach((header, columnIndex) => {
      if (!header.textContent.trim()) {
        return;
      }

      header.classList.add("sortable-header");
      header.tabIndex = 0;
      header.addEventListener("click", () => sortTableByColumn(table, columnIndex, header));
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sortTableByColumn(table, columnIndex, header);
        }
      });
    });
  });
}

function sortTableByColumn(table, columnIndex, activeHeader) {
  const tbody = table.querySelector("tbody");
  if (!tbody) {
    return;
  }

  const direction = activeHeader.dataset.sortDirection === "asc" ? "desc" : "asc";
  const rows = [...tbody.querySelectorAll("tr")];
  rows.sort((leftRow, rightRow) => {
    const leftValue = sortableValue(leftRow.children[columnIndex]?.textContent || "");
    const rightValue = sortableValue(rightRow.children[columnIndex]?.textContent || "");
    const result = compareValues(leftValue, rightValue);
    return direction === "asc" ? result : -result;
  });

  activeHeader.parentElement.querySelectorAll("th").forEach((header) => {
    header.removeAttribute("data-sort-direction");
    header.removeAttribute("aria-sort");
  });
  activeHeader.dataset.sortDirection = direction;
  activeHeader.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
  rows.forEach((row) => tbody.appendChild(row));
}

function sortableValue(value) {
  const trimmed = value.trim();
  const normalizedNumber = trimmed.replaceAll(",", "").replace(/[$%]/g, "").trim();
  const numeric = Number(normalizedNumber);
  if (/^-?\d+(\.\d+)?$/.test(normalizedNumber) && Number.isFinite(numeric)) {
    return {type: "number", value: numeric};
  }

  const dateValue = Date.parse(trimmed);
  if (Number.isFinite(dateValue)) {
    return {type: "number", value: dateValue};
  }

  return {type: "text", value: trimmed.toLowerCase()};
}

function compareValues(left, right) {
  if (left.type === "number" && right.type === "number") {
    return left.value - right.value;
  }

  return String(left.value).localeCompare(String(right.value));
}

function parseSummary(summary) {
  return summary.split("\n").reduce((values, line) => {
    const separatorIndex = line.indexOf(":");
    if (separatorIndex !== -1) {
      values[line.slice(0, separatorIndex)] = line.slice(separatorIndex + 1).trim();
    }
    return values;
  }, {});
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatMoney(value) {
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  });
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatOptionalMoney(value) {
  return value === null || value === undefined || value === "" ? "" : formatMoney(value);
}

function formatOptionalPercent(value) {
  return value === null || value === undefined || value === "" ? "" : formatPercent(value);
}

async function runBacktest() {
  const payload = requestPayload();
  if (!payload.symbols.length) {
    message.textContent = "Select at least one ETF.";
    return;
  }

  setBusy(true);
  message.textContent = "Running backtest...";
  metrics.innerHTML = "";
  tradesBody.innerHTML = "";
  periodReturnsBody.innerHTML = "";
  capitalFlowsBody.innerHTML = "";
  openPositionsBody.innerHTML = "";
  perSymbolBody.innerHTML = "";

  try {
    const response = await fetch(apiUrl("/api/backtest"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Backtest failed.");
    }

    renderSummary(data.summary);
    renderPeriodReturns(data.period_report_frequency, data.period_returns || []);
    renderCapitalFlows(data.capital_flows || []);
    renderTrades(data.trades || [], data.trade_ledger || null);
    renderOpenPositions(data.open_positions || []);
    renderPerSymbolReport(data.per_symbol_report || []);
    saveInputs();
    refreshReports();
    showTab("setupTab");
    showBacktestSubtab("resultsTab");
    const skippedText = data.skipped_symbols?.length ? ` Skipped: ${data.skipped_symbols.join(", ")}.` : "";
    message.textContent = `Backtest complete using ${data.price_time}. Condition: ${data.condition_identifier}. Saved: ${data.saved_report_path}.${skippedText}`;
    statusText.textContent = "Backtest complete";
  } catch (error) {
    message.textContent = error.message;
    statusText.textContent = "Backtest failed";
  } finally {
    setBusy(false);
  }
}

function filterEtfs() {
  const query = filterInput.value.trim().toLowerCase();
  for (const option of etfList.querySelectorAll(".etf-option")) {
    option.hidden = !option.textContent.toLowerCase().includes(query);
  }
}

selectAllButton.addEventListener("click", () => {
  document.querySelectorAll("input[name='symbols']").forEach((input) => {
    input.checked = true;
  });
  updateSelectedCount();
  saveInputs();
});

clearSelectionButton.addEventListener("click", () => {
  document.querySelectorAll("input[name='symbols']").forEach((input) => {
    input.checked = false;
  });
  updateSelectedCount();
  saveInputs();
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showTab(button.dataset.tabTarget);
  });
});
backtestSubtabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showBacktestSubtab(button.dataset.backtestTabTarget);
  });
});
liveSubtabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showLiveSubtab(button.dataset.liveTabTarget);
  });
});
etfList.addEventListener("change", updateSelectedCount);
filterInput.addEventListener("input", filterEtfs);
priceMode.addEventListener("change", updatePriceMode);
strategyName.addEventListener("change", () => updateStrategyFields(true));
candidateRanking.addEventListener("change", updateRotationAvailability);
signalSourceMode.addEventListener("change", updateSignalSourceMode);
globalSignalSource.addEventListener("input", () => {
  renderSignalSourceRows();
  saveInputs();
});
signalSourceBody.addEventListener("input", saveInputs);
runButton.addEventListener("click", runBacktest);
refreshReportsButton.addEventListener("click", refreshReports);
compareReportsButton.addEventListener("click", () => {
  compareSelectedReports().catch((error) => {
    savedStatus.textContent = error.message;
  });
});
runLiveSignalsButton.addEventListener("click", () => {
  runLiveSignals(false).catch((error) => {
    liveStatus.textContent = error.message;
  });
});
autoRefreshLiveSignals.addEventListener("change", () => {
  setLiveSignalAutoRefresh(autoRefreshLiveSignals.checked);
  liveStatus.textContent = autoRefreshLiveSignals.checked
    ? "Auto refresh enabled. Signals will refresh every 5 minutes."
    : "Auto refresh disabled.";
});
applyLiveActionsButton.addEventListener("click", () => {
  const selectedIds = selectedLiveActionIds();
  if (!latestLiveReport || !(latestLiveReport.actions || []).length) {
    liveStatus.textContent = "Generate live signals first.";
    return;
  }
  if (!selectedIds.length) {
    liveStatus.textContent = "Select at least one BUY or SELL action to apply.";
    return;
  }
  if (!window.confirm("Apply only the selected actions to the local ledger? Do this only after you execute those trades.")) {
    return;
  }
  runLiveSignals(true).catch((error) => {
    liveStatus.textContent = error.message;
  });
});
clearLiveLedgerButton.addEventListener("click", () => {
  clearLiveLedger(liveStatus).catch((error) => {
    liveStatus.textContent = error.message;
  });
});
addLiveHoldingButton.addEventListener("click", addLiveHoldingRow);
addCompletedTradeButton.addEventListener("click", addCompletedTradeRow);
saveLiveLedgerButton.addEventListener("click", () => {
  saveLiveLedger().catch((error) => {
    liveStatus.textContent = error.message;
  });
});
saveCompletedLedgerButton.addEventListener("click", () => {
  saveLiveLedger().catch((error) => {
    liveStatus.textContent = error.message;
  });
});
saveLiveConfigButton.addEventListener("click", () => {
  saveLiveConfig().catch((error) => {
    liveStatus.textContent = error.message;
  });
});
saveDhanCredentialsButton.addEventListener("click", () => {
  saveDhanCredentials().catch((error) => {
    dhanCredentialStatus.textContent = error.message;
  });
});
addLiveCapitalButton.addEventListener("click", addLiveCapitalRow);
saveLiveCapitalLedgerButton.addEventListener("click", () => {
  saveLiveCapitalLedger().catch((error) => {
    liveStatus.textContent = error.message;
  });
});
addSignalMappingButton.addEventListener("click", addSignalMappingRow);
saveSignalMappingsButton.addEventListener("click", () => {
  saveSignalMappings().catch((error) => {
    liveStatus.textContent = error.message;
  });
});
liveHoldingsBody.addEventListener("click", (event) => {
  const button = event.target.closest(".remove-ledger-row");
  if (button) {
    button.closest("tr")?.remove();
  }
});
liveBookedTradesBody.addEventListener("click", (event) => {
  const button = event.target.closest(".remove-ledger-row");
  if (button) {
    button.closest("tr")?.remove();
  }
});
savedSignalMappingBody.addEventListener("click", (event) => {
  const button = event.target.closest(".remove-ledger-row");
  if (button) {
    button.closest("tr")?.remove();
  }
});
liveCapitalBody.addEventListener("click", (event) => {
  const button = event.target.closest(".remove-ledger-row");
  if (button) {
    button.closest("tr")?.remove();
  }
});
savedReportsBody.addEventListener("click", (event) => {
  const button = event.target.closest(".open-report");
  if (!button) {
    return;
  }
  openReport(button.dataset.reportId).catch((error) => {
    savedStatus.textContent = error.message;
  });
});
document.querySelectorAll("input, select").forEach((element) => {
  element.addEventListener("change", saveInputs);
});
restoreInputs();
updateSelectedCount();
updateStrategyFields();
updatePriceMode();
updateSignalSourceMode();
updateRotationAvailability();
initSortableTables();
refreshReports();
fetchLiveReport().catch((error) => {
  liveStatus.textContent = error.message;
});
fetchLiveConfig().catch((error) => {
  liveStatus.textContent = error.message;
});
fetchDhanCredentials().catch((error) => {
  dhanCredentialStatus.textContent = error.message;
});
fetchSignalMappings().catch((error) => {
  liveStatus.textContent = error.message;
});

