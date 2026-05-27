const operatorDataHealthText = (value) =>
  String(value ?? "")
    .replace(/\bcheck[- ]stale\b/gi, "health proof needs refresh")
    .replace(/\bhealth check stale\b/gi, "health proof needs refresh")
    .replace(/\bhealth monitor stale\b/gi, "health proof needs refresh")
    .replace(/\bcritical stale source\b/gi, "critical source needs refresh")
    .replace(/\bare stale\b/gi, "need refresh")
    .replace(/\bis stale\b/gi, "needs refresh")
    .replace(/\bstale source\b/gi, "source needing refresh")
    .replace(/\bstale data\b/gi, "data needing refresh")
    .replace(/\bdata stale\b/gi, "data needs refresh")
    .replace(/\bstale\b/gi, "needs refresh");

const meter = (percent) => {
  const wrapper = document.createElement("div");
  const safePercent = Math.max(0, Math.min(Number(percent || 0), 100));
  wrapper.className = "mini-meter";
  wrapper.setAttribute("aria-label", `${safePercent}% coverage`);
  const fill = document.createElement("span");
  fill.style.width = `${safePercent}%`;
  wrapper.appendChild(fill);
  return wrapper;
};

const fetchJsonWithTimeout = async (endpoint, timeoutMs = 4500) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(endpoint, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`poll failed: ${response.status}`);
    }
    return await response.json();
  } finally {
    window.clearTimeout(timer);
  }
};

const guardedPoller = (callback) => {
  let inFlight = false;
  return async () => {
    if (inFlight) {
      return;
    }
    inFlight = true;
    try {
      await callback();
    } finally {
      inFlight = false;
    }
  };
};

(() => {
  const panel = document.querySelector("[data-full-live-panel]");
  if (!panel) {
    return;
  }

  const endpoint = panel.dataset.fullLiveEndpoint;
  if (!endpoint) {
    return;
  }

  const setText = (selector, value) => {
    const element = panel.querySelector(selector);
    if (element) {
      element.textContent = operatorDataHealthText(value);
    }
  };

  const label = (value) =>
    operatorDataHealthText(
      String(value || "unknown")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (match) => match.toUpperCase())
    );

  const setCard = (name, statusClass) => {
    const card = panel.querySelector(`[data-command-card="${name}"]`);
    if (card) {
      card.className = `command-status-card command-status-${statusClass || "neutral"}`;
    }
  };

  const render = (payload) => {
    const coverage = payload.coverage || {};
    const refresh = payload.active_refresh || {};
    const percent = Math.max(0, Math.min(Number(coverage.overall_percent || 0), 100));
    const status = panel.querySelector("[data-full-live-status]");
    if (status) {
      status.className = `tag tag-${payload.status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(payload.status_label || "Unknown");
    }
    const track = panel.querySelector("[data-full-live-track]");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }
    const fill = panel.querySelector("[data-full-live-fill]");
    if (fill) {
      fill.style.width = `${percent}%`;
    }
    setText("[data-full-live-headline]", payload.headline || "Full-live readiness is unknown.");
    setText("[data-full-live-verdict]", label(payload.verdict));
    setText("[data-full-live-scope]", payload.readiness_scope_label || label(payload.readiness_scope));
    setText("[data-full-live-tradable]", payload.tradable_ready ? "Ready" : "Gated");
    setText("[data-full-live-core]", `${coverage.core_dataset_percent || 0}%`);
    setText("[data-full-live-lanes]", `${coverage.critical_lane_percent || 0}%`);
    setText("[data-full-live-universe]", `${coverage.expected_ticker_count || 0} tickers`);
    setText("[data-full-live-refresh]", refresh.status_label || "Unknown");
    setText("[data-full-live-eta]", refresh.eta_label || "not available");
    setText("[data-full-live-detail]", payload.detail || "No full-live detail is available.");

    const sourceBlocked = Number(coverage.critical_source_blocker_count || 0);
    const sourceWarn = Number(coverage.source_warning_count || 0);
    const agentBlocked = Number(coverage.agent_blocked_count || 0);
    const agentWarn = Number(coverage.agent_warning_count || 0);
    const freshnessClass = sourceBlocked ? "block" : sourceWarn ? "warn" : "pass";
    const agentClass = agentBlocked ? "block" : agentWarn ? "warn" : "pass";
    setCard("system", payload.status_class || "neutral");
    setCard("freshness", freshnessClass);
    setCard("agents", agentClass);
    setCard("loading", refresh.status_class || "neutral");
    setText("[data-full-live-system]", payload.status_label || "Unknown");
    setText("[data-full-live-system-detail]", payload.detail || "No readiness detail available.");
    setText("[data-full-live-freshness]", coverage.source_headline || "Source freshness unknown.");
    setText(
      "[data-full-live-freshness-detail]",
      `${coverage.fresh_source_count || 0}/${coverage.source_count || 0} sources fresh; ${coverage.stale_source_count || 0} need refresh.`
    );
    setText("[data-full-live-agents]", coverage.critical_agent_ready_label || "critical lanes unknown");
    setText(
      "[data-full-live-agents-detail]",
      `${coverage.agent_ready_count || 0}/${coverage.agent_total_count || 0} total lanes ready.`
    );
    setText("[data-full-live-loading]", refresh.status_label || "Unknown");
    setText("[data-full-live-loading-detail]", `ETA ${refresh.eta_label || "not available"}; state ${refresh.state || "unknown"}.`);
  };

  const renderUnavailable = () => {
    const status = panel.querySelector("[data-full-live-status]");
    if (status) {
      status.className = "tag tag-block";
      status.textContent = "Unavailable";
    }
    setCard("system", "block");
    setCard("freshness", "block");
    setCard("agents", "block");
    setCard("loading", "block");
    setText("[data-full-live-headline]", "Full-live readiness polling is unavailable.");
    setText("[data-full-live-verdict]", "Unavailable");
    setText("[data-full-live-detail]", "The latest readiness status could not be refreshed; treat the page as unverified until polling recovers.");
    setText("[data-full-live-system]", "Unavailable");
    setText("[data-full-live-system-detail]", "Status endpoint did not return a usable response.");
  };

  const poll = async () => {
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error("full-live failed");
      }
      render(await response.json());
    } catch (_error) {
      renderUnavailable();
    }
  };

  window.setInterval(poll, 10000);
  poll();
})();

(() => {
  const panel = document.querySelector("[data-progress-panel]");
  if (!panel) {
    return;
  }

  const endpoint = panel.dataset.progressEndpoint;
  if (!endpoint) {
    return;
  }

  const setText = (selector, value) => {
    const element = panel.querySelector(selector);
    if (element) {
      element.textContent = operatorDataHealthText(value);
    }
  };

  const label = (value) =>
    operatorDataHealthText(
      String(value || "unknown")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (match) => match.toUpperCase())
    );

  const list = (value) => (Array.isArray(value) ? value : []);

  const boundedPercent = (value) => Math.max(0, Math.min(Number(value || 0), 100));

  const refreshDatasetIsLiveCritical = (value) => {
    const text = String(value || "").toLowerCase();
    return [
      "prices_daily",
      "stock_trades",
      "massive_daily_bars",
      "massive_live_trade_slices",
      "massive_premarket_trade_slices",
      "massive_block_trade_feed",
    ].includes(text);
  };

  const refreshDatasetIsRepair = (value) => {
    const text = String(value || "").toLowerCase();
    return ["backtest", "repair", "historical", "full_depth", "trade_tape"].some((token) => text.includes(token));
  };

  const refreshDatasetIsSupport = (value) => {
    const text = String(value || "").toLowerCase();
    return ["sec_", "news", "rss", "subscription", "email", "form4", "13f", "company_facts", "reference", "options"].some((token) => text.includes(token));
  };

  const refreshScope = (payload) => {
    const candidates = list(payload.failed_datasets).map(String).filter(Boolean);
    const current = String(payload.current_dataset || "").trim();
    if (current && current.toLowerCase() !== "none") {
      candidates.push(current);
    }
    if (candidates.length === 0) return "none";
    if (candidates.some(refreshDatasetIsLiveCritical)) return "live_critical";
    if (candidates.some(refreshDatasetIsRepair)) return "repair";
    if (candidates.some(refreshDatasetIsSupport)) return "support";
    return "unknown";
  };

  const refreshScopeLabel = (scope) => ({
    live_critical: "Live Critical",
    support: "Support",
    repair: "Repair",
    unknown: "Scope Unknown",
    none: "No Active Scope",
  })[scope] || "Scope Unknown";

  const refreshStatusLabel = (payload, state, scope) => {
    if (payload.display_status_label) return payload.display_status_label;
    if (["failed", "blocked"].includes(state)) {
      return `${state === "blocked" ? "Blocked" : "Failed"} - ${refreshScopeLabel(scope)}`;
    }
    if (state === "stale") return "Refresh monitor needs restart";
    if (state === "running") return "Refreshing";
    return payload.status_label || label(state);
  };

  const refreshStatusClass = (payload, state, scope) => {
    if (payload.display_status_class) return payload.display_status_class;
    if (["failed", "blocked"].includes(state)) {
      return ["support", "repair"].includes(scope) ? "warn" : "block";
    }
    if (state === "stale") return "block";
    return payload.status_class || "neutral";
  };

  const refreshDisplayState = (state, scope) => (
    ["failed", "blocked"].includes(state) && ["support", "repair"].includes(scope)
      ? `${state}_${scope}`
      : state
  );

  const refreshProgressLabel = (payload, state) => {
    if (payload.display_progress_label) return payload.display_progress_label;
    const completed = Number(payload.completed_jobs || 0);
    const total = Number(payload.total_jobs || 0);
    const jobs = total ? `${completed}/${total}` : `${completed}/?`;
    if (state === "failed") return `Failed after ${jobs} jobs`;
    if (state === "blocked") return `Blocked after ${jobs} jobs`;
    if (state === "running") return `${boundedPercent(payload.percent_complete)}% complete`;
    if (state === "complete") return "Complete";
    return `${boundedPercent(payload.percent_complete)}%`;
  };

  const refreshCurrentJobLabel = (payload) => {
    if (payload.current_job_label) return payload.current_job_label;
    const current = String(payload.current_dataset || "None");
    if (current.toLowerCase() !== "none") return current;
    return list(payload.failed_datasets)[0] || "None";
  };

  const refreshImpact = (payload, scope, state) => {
    if (payload.refresh_impact) return payload.refresh_impact;
    if (["idle", "complete", "planned"].includes(state)) {
      return {
        label: "No active load blocker",
        status_class: state === "complete" ? "pass" : "neutral",
        detail: "No active refresh failure is recorded for the latest status snapshot.",
      };
    }
    if (state === "running") {
      if (scope === "live_critical") {
        return {
          label: "Live-critical refresh running",
          status_class: "warn",
          detail: "A live-critical lane is actively loading. Wait for it to finish before submitting paper orders that depend on fresh market evidence.",
        };
      }
      if (scope === "support") {
        return {
          label: "Support refresh running",
          status_class: "neutral",
          detail: "A support/context source is actively loading. It does not block paper orders by itself, but affected context is still updating.",
        };
      }
      if (scope === "repair") {
        return {
          label: "Repair refresh running",
          status_class: "neutral",
          detail: "Historical repair or backtest coverage is actively loading. Live review can continue unless a downstream agent explicitly requires this lane.",
        };
      }
      return {
        label: "Refresh running",
        status_class: "neutral",
        detail: "A refresh job is actively loading; wait for completion before trusting affected data.",
      };
    }
    if (scope === "live_critical") {
      return {
        label: "Live-critical affected",
        status_class: "block",
        detail: "The affected lane can change review, risk, or paper-order readiness. Fix and rerun it before submitting paper orders that depend on it.",
      };
    }
    if (scope === "support") {
      return {
        label: "Support/context failed",
        status_class: "warn",
        detail: "The affected dataset improves context and source quality. It does not automatically block paper orders, but affected evidence should be treated as incomplete until the refresh succeeds.",
      };
    }
    if (scope === "repair") {
      return {
        label: "Research/repair affected",
        status_class: "warn",
        detail: "The affected work is historical repair or backtest coverage. It should not block live review unless a downstream agent explicitly requires it.",
      };
    }
    return {
      label: "Impact unknown",
      status_class: ["failed", "blocked", "stale"].includes(state) ? "block" : "neutral",
      detail: "The refresh scope is not recognized, so treat the status as blocking until inspected.",
    };
  };

  const refreshNextAction = (payload, scope, state) => {
    if (payload.next_action_label) return payload.next_action_label;
    if (state === "running") return "Wait for the active lane refresh to finish, then re-check data health.";
    if (state === "stale") return "Restart or inspect the refresh monitor before trusting the progress state.";
    if (["failed", "blocked"].includes(state)) {
      if (scope === "live_critical") return "Fix the failed live-critical lane and rerun it before paper-order submission.";
      if (scope === "support") return "Review can continue with current health gates; rerun the support refresh for complete context.";
      if (scope === "repair") return "Keep live work moving; schedule or resume the repair job off-hours.";
      return "Inspect logs and rerun the failed refresh before relying on affected data.";
    }
    if (state === "complete") return "Use the loaded data, subject to each lane's freshness badge.";
    return "No refresh action is required unless a lane or source falls outside policy.";
  };

  const enrichRefreshPayload = (payload) => {
    const state = String(payload.state || "idle").toLowerCase();
    const scope = refreshScope(payload);
    const impact = refreshImpact(payload, scope, state);
    const hasFailure = payload.has_failures === true || ["failed", "blocked"].includes(state);
    const failureLabel = payload.failure_label || (hasFailure ? `${refreshScopeLabel(scope)} dataset failure` : "");
    const failedDatasets = list(payload.failed_datasets).join(", ") || refreshCurrentJobLabel(payload);
    const failureDetail = payload.failure_detail || (hasFailure ? `${failedDatasets} did not complete. ${impact.detail}` : "");
    return {
      ...payload,
      display_state: payload.display_state || refreshDisplayState(state, scope),
      display_status_label: refreshStatusLabel(payload, state, scope),
      display_status_class: refreshStatusClass(payload, state, scope),
      display_percent_complete: payload.display_percent_complete ?? boundedPercent(payload.percent_complete),
      display_progress_label: refreshProgressLabel(payload, state),
      current_job_label: refreshCurrentJobLabel(payload),
      refresh_impact: impact,
      next_action_label: refreshNextAction(payload, scope, state),
      failure_label: failureLabel,
      failure_detail: failureDetail,
    };
  };

  const render = (payload) => {
    const view = enrichRefreshPayload(payload);
    const percent = boundedPercent(view.display_percent_complete);
    panel.dataset.loadingState = String(view.display_state || view.state || "idle");
    const status = panel.querySelector("[data-progress-status]");
    if (status) {
      status.className = `tag tag-${view.display_status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(view.display_status_label || "Idle");
    }
    const track = panel.querySelector("[data-progress-track]");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }
    const fill = panel.querySelector("[data-progress-fill]");
    if (fill) {
      fill.style.width = `${percent}%`;
    }
    setText("[data-progress-percent]", view.display_progress_label || `${percent}%`);
    setText("[data-progress-current]", view.current_job_label || "None");
    setText("[data-progress-jobs]", `${view.completed_jobs || 0}/${view.total_jobs || 0}`);
    setText("[data-progress-eta]", view.eta_label || "not available");
    setText("[data-progress-impact]", view.refresh_impact?.label || "Impact unknown");
    setText("[data-progress-action]", view.next_action_label || "Inspect refresh status.");
    renderFailure(view);
    setText("[data-progress-detail]", view.detail || "No data refresh is running.");
    setText("[data-progress-updated]", view.updated_at || "Not recorded");
    renderTradePull(view.trade_pull || {});
    renderMassiveLaneProgress(view.massive_lanes || []);
  };

  const renderFailure = (view) => {
    const row = panel.querySelector("[data-progress-failure-row]");
    if (!row) {
      return;
    }
    const hasFailure = Boolean(view.failure_label);
    row.hidden = !hasFailure;
    const status = row.querySelector("[data-progress-failure-status]");
    if (status) {
      status.className = `tag tag-${view.refresh_impact?.status_class || view.display_status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(view.display_status_label || "Refresh status");
    }
    setText("[data-progress-failure-label]", view.failure_label || "");
    setText("[data-progress-failure-detail]", view.failure_detail || "");
  };

  const renderTradePull = (tradePull) => {
    const tradePanel = panel.querySelector("[data-trade-pull]");
    if (!tradePanel) {
      return;
    }
    const percent = Math.max(0, Math.min(Number(tradePull.percent_complete || 0), 100));
    tradePanel.dataset.tradeState = String(tradePull.state || "idle");
    const status = tradePanel.querySelector("[data-trade-status]");
    if (status) {
      status.className = `tag tag-${tradePull.status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(tradePull.status_label || "No Pull");
    }
    const track = tradePanel.querySelector("[data-trade-track]");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }
    const fill = tradePanel.querySelector("[data-trade-fill]");
    if (fill) {
      fill.style.width = `${percent}%`;
    }
    setText("[data-trade-headline]", tradePull.status_label || "No Pull");
    setText("[data-trade-percent]", `${percent}%`);
    setText("[data-trade-ticker-days]", tradePull.ticker_progress_label || "not tracked");
    setText("[data-trade-current]", tradePull.current_ticker || "None");
    setText("[data-trade-current-date]", tradePull.current_trade_date || "not active");
    setText("[data-trade-current-rows]", tradePull.current_rows_downloaded || 0);
    setText("[data-trade-current-pages]", tradePull.current_pages_downloaded || 0);
    setText("[data-trade-rows]", tradePull.row_count_label || "0");
    setText("[data-trade-latest]", tradePull.latest_as_of || "not recorded");
    setText("[data-trade-window]", tradePull.window_label || "not recorded");
    setText("[data-trade-guardrail]", tradePull.guardrail_label || "not configured");
    setText("[data-trade-detail]", tradePull.detail || "No Massive stock-trades pull status is available yet.");
    setText("[data-trade-updated]", tradePull.updated_at || "not recorded");
    setText("[data-trade-job]", tradePull.job_position_label || "not in latest batch");
  };

  const appendCell = (row, labelText, value) => {
    const cell = document.createElement("td");
    cell.dataset.label = labelText;
    if (Array.isArray(value)) {
      value.forEach((element) => cell.appendChild(element));
    } else if (value instanceof Node) {
      cell.appendChild(value);
    } else {
      cell.textContent = operatorDataHealthText(value);
    }
    row.appendChild(cell);
  };

  const tag = (value, statusClass) => {
    const element = document.createElement("span");
    element.className = `tag tag-${statusClass || "neutral"}`;
    element.textContent = operatorDataHealthText(value || "UNKNOWN");
    return element;
  };

  const normalized = (value) => String(value || "").toUpperCase();

  const massiveDisplayStatus = (lane) => {
    if (lane.display_status_label) return lane.display_status_label;
    const status = normalized(lane.status);
    const state = String(lane.state || "").toLowerCase();
    const laneId = String(lane.lane_id || lane.name || "");
    const manifest = String(lane.manifest_status || "").toLowerCase();
    const coverage = Number(lane.manifest_coverage_pct || 0);
    if (state === "ready") return "Verified Current";
    if (state === "running") return "Refreshing";
    if (state === "partial_usable") return "Usable With Gaps";
    if (state === "partial" && (laneId.includes("backtest") || laneId.includes("trade_tape"))) return "Research Repair Partial";
    if (state === "partial") return "Partial Coverage";
    if (state === "missing_manifest" && laneId.includes("options")) return "Disabled / Entitlement Not Verified";
    if (state === "missing_manifest" && laneId.includes("reference")) return "Reference Not Loaded";
    if (state === "missing_manifest") return "Not Loaded";
    if (state === "stale") return "Refresh recommended";
    if (state === "failed") return "Failed";
    if (state === "blocked") return "Blocked";
    if (status === "READY_FROM_RAW") return "Ready From Live Slices";
    if (status === "SKIPPED" && (["complete", "partial_usable"].includes(manifest) || coverage > 0)) return "Loaded / No Pull Needed";
    if (status === "DUE_NOW") return "Refresh Due";
    if (status === "RUNNING") return "Refreshing";
    if (status === "DEFERRED") return "Scheduled Later";
    if (status === "WAITING") return "Waiting For Raw Lane";
    if (status === "BLOCKED") return "Blocked";
    if (status === "DISABLED" && laneId.includes("options")) return "Disabled / Entitlement Not Verified";
    if (status === "DISABLED" && laneId.includes("backtest")) return "Disabled / Research Lane";
    if (status === "DISABLED") return "Disabled / Not Enabled";
    return status ? label(status) : "Unknown";
  };

  const massiveDisplayHealth = (lane) => {
    const freshness = normalized(lane.health_freshness);
    const health = normalized(lane.health_status);
    const manifest = String(lane.manifest_status || "").toLowerCase();
    if (freshness === "PARTIAL" && health === "PARTIAL_USABLE") return "Usable With Gaps";
    if (freshness === "PARTIAL") return "Partial Coverage";
    if (freshness === "UNKNOWN" && manifest === "complete") return "Health Check Needed";
    if (freshness === "UNAVAILABLE") return "Not Enabled / Not Entitled";
    if (["FRESH", "COMPLETE"].includes(freshness) || ["FRESH", "COMPLETE"].includes(health)) return "Verified Current";
    if (freshness === "STALE") return "Refresh recommended";
    return freshness ? label(freshness) : "Unverified";
  };

  const massiveDisplayStatusClass = (text) => {
    if (["Blocked", "Failed", "Refresh recommended"].includes(text)) return "block";
    if (["Refresh Due", "Refreshing", "Waiting For Raw Lane", "Usable With Gaps", "Research Repair Partial", "Partial Coverage", "Reference Not Loaded", "Not Loaded"].includes(text)) return "warn";
    if (["Loaded / No Pull Needed", "Ready From Live Slices", "Verified Current"].includes(text)) return "pass";
    return "neutral";
  };

  const massiveDisplayHealthClass = (text) => {
    if (text === "Refresh recommended") return "block";
    if (["Usable With Gaps", "Partial Coverage", "Health Check Needed"].includes(text)) return "warn";
    if (text === "Verified Current") return "pass";
    return "neutral";
  };

  const massiveImpact = (lane) => {
    const laneId = String(lane.lane_id || lane.name || "");
    if (lane.blocks_execution === true || ["massive_daily_bars", "massive_live_trade_slices", "massive_premarket_trade_slices", "massive_block_trade_feed"].includes(laneId)) {
      return {
        label: "Execution-critical",
        detail: "This lane can affect paper-order readiness because live decisions depend on its market data.",
      };
    }
    if (laneId.includes("options")) {
      return {
        label: "Optional / entitlement",
        detail: "This lane is optional until the provider entitlement is verified and enabled.",
      };
    }
    if (laneId.includes("backtest")) {
      return {
        label: "Research/repair",
        detail: "This lane supports research and backtesting. It should not block live review or paper orders.",
      };
    }
    return {
      label: "Support/context",
      detail: "This lane improves context or source hygiene. It does not directly block paper-order submission.",
    };
  };

  const showMassiveLiveTickerProgress = (lane) => {
    const laneId = String(lane.lane_id || lane.name || "");
    const dataset = String(lane.raw_source_dataset || lane.dataset || "");
    return dataset === "stock_trades" && (laneId.includes("live_trade_slices") || laneId.includes("premarket_trade_slices"));
  };

  const massiveCoverageLabel = (lane, showProgress) => {
    const manifest = String(lane.manifest_status || "missing").replaceAll("_", " ");
    if (showProgress) {
      return `${lane.fresh_ticker_count ?? 0} fresh / ${lane.pending_ticker_count ?? 0} pending`;
    }
    if (Number(lane.manifest_coverage_pct || 0)) {
      return `Manifest ${manifest} / ${lane.manifest_coverage_pct || 0}% coverage`;
    }
    if (Number(lane.ticker_count || 0)) {
      return `${lane.ticker_count || 0} planned; manifest ${manifest}`;
    }
    return `Manifest ${manifest}`;
  };

  const boundedWholePercent = (value) => Math.max(0, Math.min(100, Math.round(Number(value || 0))));

  const massiveLaneProgressPercent = (lane, showProgress) => {
    if (lane.progress_percent !== undefined && lane.progress_percent !== null) {
      return boundedWholePercent(lane.progress_percent);
    }
    if (lane.percent_complete !== undefined && lane.percent_complete !== null) {
      return boundedWholePercent(lane.percent_complete);
    }
    if (showProgress) {
      const fresh = Number(lane.fresh_ticker_count || 0);
      const pending = Number(lane.pending_ticker_count || 0);
      const total = fresh + pending;
      if (total > 0) {
        return boundedWholePercent((fresh / total) * 100);
      }
    }
    return boundedWholePercent(lane.manifest_coverage_pct || 0);
  };

  const massiveLaneProgressDetail = (lane, coverage, progressPercent) =>
    `${progressPercent}% loaded. ${coverage}. ETA ${lane.eta_label || "not available"}.`;

  const massiveBucketLabel = (lane, displayStatus) => {
    const laneId = String(lane.lane_id || lane.name || "");
    const status = normalized(lane.status);
    if (lane.blocks_execution !== true && (["DISABLED", "DEFERRED"].includes(status) || laneId.includes("backtest") || laneId.includes("options"))) {
      return "Research / Disabled / Not Entitled";
    }
    if (lane.blocks_execution === true) {
      if (["Blocked", "Refresh Due", "Refreshing", "Waiting For Raw Lane"].includes(displayStatus)) {
        return "Execution-Critical Needs Refresh";
      }
      return "Execution-Critical Ready";
    }
    if (["DUE_NOW", "RUNNING", "WAITING"].includes(status)) {
      return "Support / Context Due";
    }
    return "Research / Disabled / Not Entitled";
  };

  const massiveActionLabel = (displayStatus) => ({
    "Refresh Due": "Run lane refresh",
    "Refreshing": "Wait for refresh",
    "Blocked": "Fix lane blocker",
    "Scheduled Later": "No action now",
    "Disabled / Entitlement Not Verified": "Verify entitlement",
    "Disabled / Research Lane": "Enable only for research",
    "Loaded / No Pull Needed": "No pull needed",
    "Ready From Live Slices": "Derived locally",
    "Waiting For Raw Lane": "Wait for raw lane",
  })[displayStatus] || "Inspect lane detail";

  const enrichMassiveLane = (lane) => {
    const displayStatus = lane.display_status_label || massiveDisplayStatus(lane);
    const displayHealth = lane.display_health_label || massiveDisplayHealth(lane);
    const impact = lane.impact_label && lane.impact_detail
      ? { label: lane.impact_label, detail: lane.impact_detail }
      : massiveImpact(lane);
    const showProgress = lane.show_live_ticker_progress ?? showMassiveLiveTickerProgress(lane);
    const coverage = lane.coverage_label || massiveCoverageLabel(lane, showProgress);
    const progressPercent = massiveLaneProgressPercent(lane, showProgress);
    const bucket = lane.bucket_label || massiveBucketLabel(lane, displayStatus);
    return {
      ...lane,
      display_status_label: displayStatus,
      display_status_class: lane.display_status_class || massiveDisplayStatusClass(displayStatus),
      display_health_label: displayHealth,
      display_health_class: lane.display_health_class || massiveDisplayHealthClass(displayHealth),
      impact_label: impact.label,
      impact_detail: impact.detail,
      coverage_label: coverage,
      progress_percent: progressPercent,
      progress_style: lane.progress_style || `width: ${progressPercent}%`,
      progress_meter_label: lane.progress_meter_label || `${progressPercent}% lane progress`,
      progress_detail_label: lane.progress_detail_label || massiveLaneProgressDetail(lane, coverage, progressPercent),
      bucket_label: bucket,
      action_label: lane.action_label || massiveActionLabel(displayStatus),
      tooltip: lane.tooltip || `${displayStatus}. ${impact.detail} Manifest status: ${lane.manifest_status || "missing"}; coverage: ${lane.manifest_coverage_pct || 0}%; detail: ${lane.detail || "No lane detail recorded."}`,
    };
  };

  const massiveLaneSummary = (lanes, supplied) => supplied || {
    execution_ready_count: lanes.filter((lane) => lane.bucket_label === "Execution-Critical Ready").length,
    execution_needs_refresh_count: lanes.filter((lane) => lane.bucket_label === "Execution-Critical Needs Refresh").length,
    support_due_count: lanes.filter((lane) => lane.bucket_label === "Support / Context Due").length,
    research_disabled_count: lanes.filter((lane) => lane.bucket_label === "Research / Disabled / Not Entitled").length,
  };

  const renderMassiveLaneProgress = (lanes) => {
    const body = panel.querySelector("[data-refresh-massive-lane-body]");
    if (!body) {
      return;
    }
    body.replaceChildren();
    if (!Array.isArray(lanes) || lanes.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 6;
      cell.textContent = "No Massive lane progress rows are available yet.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    lanes.forEach((lane) => {
      const enriched = enrichMassiveLane(lane);
      const row = document.createElement("tr");
      const laneCell = document.createElement("td");
      laneCell.dataset.label = "Lane";
      const strong = document.createElement("strong");
      strong.textContent = operatorDataHealthText(enriched.label || enriched.lane_id || "Unknown lane");
      const sub = document.createElement("span");
      sub.textContent = operatorDataHealthText(enriched.window_label || "window not recorded");
      laneCell.append(strong, sub);
      row.appendChild(laneCell);
      const statusTag = tag(enriched.display_status_label, enriched.display_status_class);
      statusTag.title = enriched.tooltip || enriched.impact_detail || "";
      appendCell(row, "Status", statusTag);
      const progressText = document.createElement("span");
      progressText.textContent = operatorDataHealthText(
        `${enriched.progress_label || "not tracked"} - ETA ${enriched.eta_label || "not available"}`
      );
      appendCell(row, "Progress", [
        meter(enriched.progress_percent),
        progressText,
      ]);
      appendCell(row, "Rows", enriched.row_count_label || "0");
      appendCell(row, "Updated", enriched.updated_at || "not recorded");
      const meaning = document.createElement("div");
      const meaningStrong = document.createElement("strong");
      meaningStrong.textContent = operatorDataHealthText(enriched.impact_label || "Impact unknown");
      const meaningDetail = document.createElement("span");
      meaningDetail.textContent = operatorDataHealthText(enriched.detail || "No lane detail recorded.");
      meaning.append(meaningStrong, meaningDetail);
      appendCell(row, "Meaning", meaning);
      body.appendChild(row);
    });
  };

  const renderUnavailable = () => {
    panel.dataset.loadingState = "unavailable";
    const status = panel.querySelector("[data-progress-status]");
    if (status) {
      status.className = "tag tag-block";
      status.textContent = "Unavailable";
    }
    setText("[data-progress-detail]", "Data-refresh polling is unavailable; the visible progress is unverified.");
    setText("[data-progress-current]", "Unknown");
    setText("[data-progress-eta]", "not available");
    renderMassiveLaneProgress([]);
    renderTradePull({
      state: "unavailable",
      status_class: "block",
      status_label: "Unavailable",
      detail: "Stock-trade pull status could not be refreshed.",
    });
  };

  const poll = guardedPoller(async () => {
    try {
      render(await fetchJsonWithTimeout(endpoint));
    } catch (_error) {
      renderUnavailable();
    }
  });

  window.setInterval(poll, 5000);
  poll();
})();

(() => {
  const heartbeat = document.querySelector("[data-runtime-heartbeat]");
  if (!heartbeat) {
    return;
  }

  const healthEndpoint = heartbeat.dataset.runtimeHealthEndpoint || "/health";
  const brokerEndpoint = heartbeat.dataset.runtimeBrokerEndpoint || "/status/broker";
  const dot = heartbeat.querySelector("[data-runtime-dot]");
  const server = heartbeat.querySelector("[data-runtime-server-status]");
  const broker = heartbeat.querySelector("[data-runtime-broker-status]");
  const updated = heartbeat.querySelector("[data-runtime-updated]");

  const setStatus = (element, label, statusClass) => {
    if (!element) {
      return;
    }
    element.className = `status-pill status-pill-${statusClass}`;
    element.textContent = label;
  };

  const setDot = (statusClass) => {
    if (!dot) {
      return;
    }
    dot.className = `status-dot status-dot-${statusClass}`;
  };

  const stamp = () => {
    if (!updated) {
      return;
    }
    updated.textContent = `Checked ${new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })}`;
  };

  const pollServer = async () => {
    try {
      const response = await fetch(healthEndpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error("health failed");
      }
      const payload = await response.json();
      if (payload.status === "ok") {
        heartbeat.dataset.runtimeState = "online";
        setDot("pass");
        setStatus(server, "Server live", "pass");
      } else {
        heartbeat.dataset.runtimeState = "degraded";
        setDot("warn");
        setStatus(server, "Server degraded", "warn");
      }
    } catch (_error) {
      heartbeat.dataset.runtimeState = "offline";
      setDot("block");
      setStatus(server, "Server offline", "block");
    } finally {
      stamp();
    }
  };

  const pollBroker = async () => {
    try {
      const response = await fetch(brokerEndpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error("broker failed");
      }
      const payload = await response.json();
      if (payload.connected === true) {
        setStatus(
          broker,
          payload.status_label || `${payload.mode ? String(payload.mode).toUpperCase() : "PAPER"} broker connected`,
          payload.status_class || "paper"
        );
      } else {
        setStatus(broker, payload.status_label || "Broker offline", payload.status_class || "warn");
      }
    } catch (_error) {
      setStatus(broker, "Broker check failed", "block");
    }
  };

  const poll = () => {
    pollServer();
    pollBroker();
  };

  window.setInterval(poll, 15000);
  poll();
})();

(() => {
  const panel = document.querySelector("[data-scheduler-panel]");
  if (!panel) {
    return;
  }

  const endpoint = panel.dataset.schedulerEndpoint;
  if (!endpoint) {
    return;
  }

  const setText = (selector, value) => {
    const element = panel.querySelector(selector);
    if (element) {
      element.textContent = operatorDataHealthText(value);
    }
  };

  const label = (value) =>
    operatorDataHealthText(
      String(value || "unknown")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (match) => match.toUpperCase())
    );

  const statusOf = (row) => String((row || {}).status || "").toUpperCase();

  const isLiveCriticalSchedulerRow = (row) => {
    const item = row || {};
    const dataset = String(item.dataset || item.raw_source_dataset || "");
    const signal = String(item.signal_lane || item.name || "");
    return (
      item.blocks_execution === true ||
      ["prices_daily", "stock_trades"].includes(dataset) ||
      [
        "abnormal_volume",
        "block_trade_pressure",
        "buy_sell_pressure",
        "market_flow_trend",
        "pre_market_unusual_activity",
        "sector_momentum",
        "technical_analysis",
        "unusual_trade_activity",
      ].includes(signal)
    );
  };

  const firstEtaLabel = (rows) => {
    const row = rows.find((item) => item && item.eta_label);
    return row ? row.eta_label : "not needed";
  };

  const workloadStatusLabel = (liveCount, supportCount, repairCount, runningCount) => {
    if (liveCount) {
      return `${liveCount} live-critical due`;
    }
    if (supportCount || repairCount) {
      return "Support/repair due";
    }
    if (runningCount) {
      return "Refresh running";
    }
    return "Queue clear";
  };

  const computeSchedulerWorkload = (payload) => {
    if (payload.refresh_workload) {
      return payload.refresh_workload;
    }
    const jobs = payload.jobs || [];
    const massive = payload.massive_orchestrator || {};
    const massiveLanes = massive.lanes || [];
    const repair = payload.repair_plan || {};
    const repairRows = repair.jobs || [];
    const dueRows = [
      ...jobs.filter((row) => statusOf(row) === "DUE_NOW"),
      ...massiveLanes.filter((row) => statusOf(row) === "DUE_NOW"),
    ];
    const liveCritical = dueRows.filter(isLiveCriticalSchedulerRow);
    const support = dueRows.filter((row) => !isLiveCriticalSchedulerRow(row));
    const repairDue = repairRows.filter((row) => statusOf(row) === "DUE_NOW");
    const runningCount = [...jobs, ...massiveLanes, ...repairRows].filter(
      (row) => statusOf(row) === "RUNNING"
    ).length;
    const nextLiveEta = firstEtaLabel(liveCritical);
    let detail = `${liveCritical.length} live-critical due; ${support.length} support due; ${repairDue.length} repair due; ${runningCount} running.`;
    if (nextLiveEta !== "not needed") {
      detail = `${detail} Next live-critical ETA: ${nextLiveEta}.`;
    }
    return {
      status_label: workloadStatusLabel(liveCritical.length, support.length, repairDue.length, runningCount),
      status_class: liveCritical.length ? "warn" : support.length || repairDue.length || runningCount ? "neutral" : "pass",
      detail,
      live_critical_due_count: liveCritical.length,
      support_due_count: support.length,
      repair_due_count: repairDue.length,
      running_count: runningCount,
      next_live_eta_label: nextLiveEta,
    };
  };

  const appendCell = (row, labelText, value) => {
    const cell = document.createElement("td");
    cell.dataset.label = labelText;
    if (Array.isArray(value)) {
      value.forEach((element) => cell.appendChild(element));
    } else if (value instanceof Node) {
      cell.appendChild(value);
    } else {
      cell.textContent = operatorDataHealthText(value);
    }
    row.appendChild(cell);
  };

  const tag = (value, statusClass) => {
    const element = document.createElement("span");
    element.className = `tag tag-${statusClass || "neutral"}`;
    element.textContent = operatorDataHealthText(value || "UNKNOWN");
    return element;
  };

  const laneRefreshControl = (lane) => {
    const container = document.createElement("div");
    container.className = "lane-refresh-control";
    container.title = lane.refresh_tooltip || "";
    if (lane.refresh_enabled && lane.refresh_action_url) {
      const form = document.createElement("form");
      form.className = "inline-actions";
      form.method = "post";
      form.action = lane.refresh_action_url;
      const button = document.createElement("button");
      button.className = "mini-button";
      button.type = "submit";
      button.textContent = lane.refresh_button_label || "Refresh lane";
      button.setAttribute(
        "aria-label",
        `Refresh ${lane.label || lane.lane_id || "Massive"} data lane`
      );
      form.appendChild(button);
      container.appendChild(form);
      const scope = document.createElement("span");
      scope.className = "muted-line";
      scope.textContent = lane.refresh_scope_label || "Lane-level refresh";
      container.appendChild(scope);
      return container;
    }
    const button = document.createElement("button");
    button.className = "disabled-button";
    button.type = "button";
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
    button.textContent = lane.refresh_button_label || "Policy locked";
    container.appendChild(button);
    const reason = document.createElement("span");
    reason.className = "muted-line";
    reason.textContent =
      lane.refresh_disabled_reason || "Current policy does not allow this lane refresh.";
    container.appendChild(reason);
    return container;
  };

  const renderMassiveLanes = (payload) => {
    const massive = payload.massive_orchestrator || {};
    const card = panel.querySelector("[data-massive-orchestrator]");
    if (card) {
      card.dataset.massiveStatus = String(massive.state || "idle");
    }
    const status = panel.querySelector("[data-massive-status-label]");
    if (status) {
      status.className = `tag tag-${massive.status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(massive.status_label || "Unknown");
    }
    setText("[data-massive-headline]", massive.status_label || "Unknown");
    setText("[data-massive-detail]", massive.detail || "Massive lane status is unavailable.");
    setText(
      "[data-massive-lanes]",
      `${massive.due_now_count || 0} due / ${massive.blocked_count || 0} blocked`
    );
    const lanes = Array.isArray(massive.lanes) ? massive.lanes.map(enrichMassiveLane) : [];
    const laneSummary = massiveLaneSummary(lanes, massive.lane_summary);
    setText("[data-massive-critical-ready]", laneSummary.execution_ready_count || 0);
    setText("[data-massive-critical-refresh]", laneSummary.execution_needs_refresh_count || 0);
    setText("[data-massive-support-due]", laneSummary.support_due_count || 0);
    setText("[data-massive-research-disabled]", laneSummary.research_disabled_count || 0);

    const body = panel.querySelector("[data-massive-lane-body]");
    if (!body || !Array.isArray(massive.lanes)) {
      return;
    }
    body.replaceChildren();
    if (lanes.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 8;
      cell.textContent = "No Massive lanes are configured in the current scheduler plan.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    lanes.forEach((lane) => {
      const row = document.createElement("tr");
      row.title = lane.status_tooltip || lane.reason || "";
      const laneCell = document.createElement("td");
      laneCell.dataset.label = "Lane";
      const strong = document.createElement("strong");
      strong.textContent = operatorDataHealthText(lane.label || lane.lane_id || "Unknown lane");
      const sub = document.createElement("span");
      sub.textContent = operatorDataHealthText(`${String(lane.raw_source_dataset || lane.dataset || "unknown").replaceAll("_", " ")} - ${lane.acquisition_mode || lane.endpoint_family || "unknown"} - ${lane.bucket_label}`);
      laneCell.append(strong, sub);
      row.appendChild(laneCell);
      appendCell(row, "Status", [
        tag(lane.display_status_label, lane.display_status_class),
        tag(lane.display_health_label, lane.display_health_class),
      ]);
      const impactCell = document.createElement("div");
      const impactStrong = document.createElement("strong");
      impactStrong.textContent = lane.impact_label || "Unknown impact";
      const impactText = document.createElement("span");
      impactText.textContent = operatorDataHealthText(lane.impact_detail || "No execution-impact detail recorded.");
      impactCell.append(impactStrong, impactText);
      appendCell(row, "Execution Impact", impactCell);
      const batchTickers = lane.batch_ticker_count || lane.command_ticker_count || 0;
      const batchLabel = batchTickers ? `; ${batchTickers} in next safe batch` : "";
      const coverageDetail = document.createElement("span");
      coverageDetail.textContent = operatorDataHealthText(
        `${lane.coverage_label || "Coverage not recorded"}${batchLabel}; ${lane.progress_detail_label || ""}`
      );
      const manifestDetail = document.createElement("span");
      manifestDetail.className = "muted-line";
      manifestDetail.textContent = operatorDataHealthText(
        `Tier ${lane.ticker_tier || "n/a"}; manifest ${lane.manifest_status || "missing"} / ${lane.manifest_coverage_pct || 0}%`
      );
      appendCell(
        row,
        "Coverage",
        [
          meter(lane.progress_percent),
          coverageDetail,
          document.createElement("br"),
          manifestDetail,
        ]
      );
      appendCell(
        row,
        "Cadence / Budget",
        `${lane.cadence_minutes || "window"} - ETA ${lane.eta_label || "n/a"}; ${lane.request_budget_label || "budget not recorded"}`
      );
      appendCell(row, "Next Action", lane.action_label || "Inspect lane detail");
      appendCell(row, "Refresh", laneRefreshControl(lane));
      appendCell(row, "Reason", lane.reason || "No Massive lane rationale recorded.");
      body.appendChild(row);
    });

    const signalBody = panel.querySelector("[data-massive-signal-body]");
    if (!signalBody || !Array.isArray(massive.derived_signal_lanes)) {
      return;
    }
    signalBody.replaceChildren();
    if (massive.derived_signal_lanes.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 5;
      cell.textContent = "No Massive-backed derived signal requirements are active in this plan.";
      row.appendChild(cell);
      signalBody.appendChild(row);
      return;
    }
    massive.derived_signal_lanes.forEach((signal) => {
      const row = document.createElement("tr");
      row.title = signal.tooltip || signal.reason || "";
      appendCell(row, "Derived signal", signal.label || signal.signal_lane || "Unknown signal");
      appendCell(row, "Raw lane requirement", (signal.requires_raw_lanes || []).join(", ") || "n/a");
      appendCell(row, "Status", tag(signal.status, signal.status_class));
      appendCell(row, "Impact", `${signal.impact_label || "Context signal"} - ${signal.requirement_summary || "Requirement unverified."}`);
      appendCell(row, "Meaning", `${signal.impact_detail || ""} ${signal.reason || "No requirement rationale recorded."}`.trim());
      signalBody.appendChild(row);
    });
  };

  const render = (payload) => {
    const summary = payload.summary || {};
    const counts = summary.counts || {};
    const tradability = payload.tradability || {};
    const runtime = payload.scheduler_runtime || {};
    const automation = payload.automation_status || {
      status_label: runtime.status_label || "Unknown",
      status_class: runtime.status_class || "neutral",
      detail: runtime.detail || "Scheduler heartbeat has not been checked.",
    };
    const gate = payload.trading_freshness_gate || {
      status_label: tradability.status_label || "Unknown",
      status_class: tradability.status_class || "neutral",
      detail: tradability.detail || "No scheduler detail available.",
    };
    const workload = computeSchedulerWorkload(payload);
    const status = panel.querySelector("[data-scheduler-status]");
    if (status) {
      status.className = `tag tag-${gate.status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(gate.status_label || "Unknown");
    }
    setText("[data-scheduler-headline]", summary.headline || "Scheduler status is unavailable.");
    setText("[data-scheduler-phase]", label(payload.market_phase));
    setText("[data-scheduler-automation]", automation.status_label || "Unknown");
    setText("[data-scheduler-gate]", gate.status_label || "Unknown");
    setText("[data-scheduler-due]", workload.live_critical_due_count || 0);
    setText("[data-scheduler-support-due]", workload.support_due_count || 0);
    setText("[data-scheduler-repair-due]", workload.repair_due_count || 0);
    setText("[data-scheduler-running]", workload.running_count || counts.running || 0);
    const active = runtime.active_command || {};
    const activeDetail = active.name
      ? ` Active command: ${active.name}${active.ticker_count ? ` (${active.ticker_count} tickers)` : ""}.`
      : "";
    const lastFinished = runtime.last_tick_finished_at
      ? ` Last finished: ${runtime.last_tick_finished_at}.`
      : "";
    const runtimeDetail = runtime.detail
      ? ` Scheduler: ${runtime.detail}${activeDetail}${lastFinished}`
      : activeDetail || lastFinished;
    setText(
      "[data-scheduler-detail]",
      `${gate.detail || "No scheduler detail available."} Automation: ${automation.detail || runtimeDetail} Workload: ${workload.detail || "Refresh workload unavailable."}`
    );
    renderMassiveLanes(payload);
  };

  const renderUnavailable = () => {
    const status = panel.querySelector("[data-scheduler-status]");
    if (status) {
      status.className = "tag tag-block";
      status.textContent = "Unavailable";
    }
    setText("[data-scheduler-headline]", "Scheduler status polling is unavailable.");
    setText("[data-scheduler-phase]", "Unknown");
    setText("[data-scheduler-due]", 0);
    setText("[data-scheduler-support-due]", 0);
    setText("[data-scheduler-repair-due]", 0);
    setText("[data-scheduler-running]", 0);
    setText("[data-scheduler-automation]", "Unknown");
    setText("[data-scheduler-gate]", "Unavailable");
    setText("[data-massive-lanes]", "0 due / 0 blocked");
    setText("[data-massive-headline]", "Unavailable");
    setText("[data-massive-detail]", "Massive lane polling is unavailable.");
    setText("[data-scheduler-detail]", "Scheduler status could not be refreshed; treat tradability as context-only until polling recovers.");
  };

  const poll = async () => {
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error("scheduler failed");
      }
      render(await response.json());
    } catch (_error) {
      renderUnavailable();
    }
  };

  window.setInterval(poll, 15000);
  poll();
})();

(() => {
  const panel = document.querySelector("[data-load-panel]");
  if (!panel) {
    return;
  }

  const endpoint = panel.dataset.loadEndpoint;
  if (!endpoint) {
    return;
  }

  const setText = (selector, value) => {
    const element = panel.querySelector(selector);
    if (element) {
      element.textContent = operatorDataHealthText(value);
    }
  };

  const title = (value) =>
    operatorDataHealthText(
      String(value || "unknown")
        .replaceAll("_", " ")
        .replace(/\b\w/g, (match) => match.toUpperCase())
    );

  const tag = (value, statusClass) => {
    const element = document.createElement("span");
    element.className = `tag tag-${statusClass || "neutral"}`;
    element.textContent = operatorDataHealthText(value || "UNKNOWN");
    return element;
  };

  const appendCell = (row, labelText, value) => {
    const cell = document.createElement("td");
    cell.dataset.label = labelText;
    if (Array.isArray(value)) {
      value.forEach((element) => cell.appendChild(element));
    } else if (value instanceof Node) {
      cell.appendChild(value);
    } else {
      cell.textContent = operatorDataHealthText(value);
    }
    row.appendChild(cell);
  };

  const countLabel = (row) => {
    const hasNumber = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
    if (hasNumber(row.produced_count) && hasNumber(row.expected_count)) {
      return `${row.produced_count}/${row.expected_count} rows`;
    }
    if (hasNumber(row.loaded_ticker_count) && hasNumber(row.expected_ticker_count)) {
      return `${row.loaded_ticker_count}/${row.expected_ticker_count} tickers`;
    }
    if (hasNumber(row.row_count)) {
      return `${Number(row.row_count).toLocaleString()} rows`;
    }
    return "coverage n/a";
  };

  const renderDatasetRows = (rows) => {
    const body = panel.querySelector("[data-load-dataset-body]");
    if (!body) {
      return;
    }
    body.replaceChildren();
    if (!Array.isArray(rows) || rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 5;
      cell.textContent = "No dataset status rows are available.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      const nameCell = document.createElement("td");
      nameCell.dataset.label = "Dataset";
      const strong = document.createElement("strong");
      strong.textContent = title(item.label || item.dataset);
      const detail = document.createElement("span");
      detail.textContent = operatorDataHealthText(item.detail || "No dataset detail recorded.");
      nameCell.append(strong, detail);
      row.appendChild(nameCell);
      appendCell(row, "Status", tag(item.status_label || item.status, item.status_class));
      const coverageCell = document.createElement("td");
      coverageCell.dataset.label = "Coverage";
      coverageCell.appendChild(meter(item.coverage_pct));
      const coverageText = document.createElement("span");
      coverageText.textContent = `${item.coverage_pct || 0}% - ${countLabel(item)}`;
      coverageCell.appendChild(coverageText);
      row.appendChild(coverageCell);
      appendCell(row, "Freshness", [
        tag(item.source_freshness, item.status_class),
        document.createTextNode(` ${item.source_status || "UNKNOWN"}`),
      ]);
      appendCell(row, "Rows / As-of", `${item.row_count || 0} - ${item.max_as_of || "not loaded"}`);
      body.appendChild(row);
    });
  };

  const renderLaneRows = (rows) => {
    const body = panel.querySelector("[data-load-lane-body]");
    if (!body) {
      return;
    }
    body.replaceChildren();
    if (!Array.isArray(rows) || rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 4;
      cell.textContent = "No lane-state registry rows are available.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      const laneCell = document.createElement("td");
      laneCell.dataset.label = "Lane";
      const strong = document.createElement("strong");
      strong.textContent = title(item.label || item.lane_id || item.lane);
      const group = document.createElement("span");
      const requirements = Array.isArray(item.raw_lanes_required) && item.raw_lanes_required.length
        ? item.raw_lanes_required.join(", ")
        : "Direct source";
      group.textContent = item.lane_kind
        ? `${title(item.lane_kind)} - ${requirements}`
        : title(item.group);
      laneCell.append(strong, group);
      row.appendChild(laneCell);
      appendCell(row, "Status", tag(item.status_label || item.status, item.status_class));
      if (item.lane_kind) {
        const proofText = document.createElement("span");
        proofText.textContent = item.progress_label || "not tracked";
        const checkedText = document.createElement("span");
        checkedText.textContent = `ETA ${item.eta_label || "not available"} - as of ${item.latest_as_of || "not recorded"} - checked ${item.checked_at || "not checked"}`;
        appendCell(row, "Proof", [
          meter(item.progress_percent),
          proofText,
          document.createElement("br"),
          checkedText,
        ]);
        appendCell(row, "Action", [
          document.createTextNode(item.operator_message || "No lane-state explanation recorded."),
          document.createElement("br"),
          document.createTextNode(item.recommended_action || "No lane action recorded."),
        ]);
      } else {
        const coverageCell = document.createElement("td");
        coverageCell.dataset.label = "Coverage";
        coverageCell.appendChild(meter(item.coverage_pct));
        const coverageText = document.createElement("span");
        coverageText.textContent = `${item.coverage_pct || 0}% - ${countLabel(item)}`;
        coverageCell.appendChild(coverageText);
        row.appendChild(coverageCell);
        appendCell(row, "Interpretation", item.detail || "No lane detail recorded.");
      }
      body.appendChild(row);
    });
  };

  const renderFreshnessRows = (rows) => {
    const body = panel.querySelector("[data-load-freshness-body]");
    if (!body) {
      return;
    }
    body.replaceChildren();
    if (!Array.isArray(rows) || rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "empty-row";
      cell.colSpan = 6;
      cell.textContent = "No source freshness rows are available.";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("tr");
      const sourceCell = document.createElement("td");
      sourceCell.dataset.label = "Source";
      const strong = document.createElement("strong");
      strong.textContent = String(item.label || item.source || "Unknown source");
      const critical = document.createElement("span");
      critical.textContent = item.critical === true ? "Critical" : "Supporting";
      sourceCell.append(strong, critical);
      row.appendChild(sourceCell);
      appendCell(row, "Status", tag(item.status, item.status_class));
      appendCell(row, "Freshness", item.freshness || "UNKNOWN");
      appendCell(row, "Last Success", item.last_success_at || "not recorded");
      appendCell(row, "Checked", item.checked_at || "not checked");
      appendCell(row, "Meaning", item.detail || "No freshness detail recorded.");
      body.appendChild(row);
    });
  };

  const renderIssues = (blockers, warnings) => {
    const list = panel.querySelector("[data-load-issue-list]");
    if (!list) {
      return;
    }
    list.replaceChildren();
    const rows = [
      ...(Array.isArray(blockers) ? blockers.map((row) => ({ ...row, status_class: row.status_class || "block" })) : []),
      ...(Array.isArray(warnings) ? warnings.map((row) => ({ ...row, status_class: row.status_class || "warn" })) : []),
    ];
    if (rows.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-block";
      empty.textContent = "No data-load blockers or warnings in the latest cycle.";
      list.appendChild(empty);
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement("div");
      row.className = "ops-check-row";
      row.appendChild(tag(title(item.kind || "issue"), item.status_class));
      const strong = document.createElement("strong");
      strong.textContent = title(item.item || "unknown");
      const reason = document.createElement("span");
      reason.textContent = String(item.reason || "No detail available.");
      row.append(strong, reason);
      list.appendChild(row);
    });
  };

  const render = (payload) => {
    const percent = Math.max(0, Math.min(Number(payload.overall_percent || 0), 100));
    panel.dataset.loadState = String(payload.state || "unknown");
    const status = panel.querySelector("[data-load-status]");
    if (status) {
      status.className = `tag tag-${payload.status_class || "neutral"}`;
      status.textContent = operatorDataHealthText(payload.status_label || "Unknown");
    }
    const track = panel.querySelector("[data-load-track]");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }
    const fill = panel.querySelector("[data-load-fill]");
    if (fill) {
      fill.style.width = `${percent}%`;
    }
    const progress = payload.progress || {};
    const sourceSummary = payload.source_summary || {};
    const datasetSummary = payload.dataset_summary || {};
    const agentSummary = payload.agent_summary || {};
    const marketFlow = payload.market_flow_summary || {};
    const healthMonitor = payload.health_monitor || {};
    setText("[data-load-headline]", payload.headline || "Agency data readiness is unknown.");
    setText("[data-load-overall]", `${percent}%`);
    setText("[data-load-mode]", payload.mode_label || "Unknown");
    setText("[data-load-market-flow]", marketFlow.status_label || "Unknown");
    setText("[data-load-core]", `${payload.core_dataset_percent || 0}%`);
    setText("[data-load-lanes]", `${payload.critical_lane_percent || 0}%`);
    setText("[data-load-universe]", `${payload.expected_ticker_count || 0} tickers`);
    setText("[data-load-cycle]", payload.cycle_id || "None");
    setText("[data-load-signals]", payload.signal_count || 0);
    setText("[data-load-detail]", payload.detail || "No data-load detail is available.");
    setText("[data-load-asof]", payload.as_of || "unknown");
    setText("[data-load-checked]", payload.status_checked_at || payload.generated_at || "unknown");
    setText("[data-load-health-monitor]", healthMonitor.status_label || "not verified");
    setText("[data-load-blockers]", payload.blocker_count || 0);
    setText("[data-load-warnings]", payload.warning_count || 0);
    setText("[data-load-eta]", progress.eta_label || "not available");
    setText("[data-load-source-headline]", sourceSummary.headline || "Source freshness unknown.");
    setText("[data-load-fresh-sources]", sourceSummary.fresh_count || 0);
    setText("[data-load-stale-sources]", sourceSummary.blocked_count || 0);
    setText("[data-load-warning-sources]", sourceSummary.warning_count || 0);
    setText("[data-load-dataset-ready]", datasetSummary.ready_label || "datasets unknown");
    setText("[data-load-dataset-blocked]", datasetSummary.blocked_count || 0);
    setText("[data-load-dataset-warning]", datasetSummary.warning_count || 0);
    setText("[data-load-agent-ready]", agentSummary.critical_ready_label || "critical lanes unknown");
    setText("[data-load-agent-blocked]", agentSummary.blocked_count || 0);
    setText("[data-load-agent-warning]", agentSummary.warning_count || 0);
    renderDatasetRows(payload.datasets || []);
    renderLaneRows(payload.lane_states || payload.lanes || []);
    renderFreshnessRows(payload.freshness_rows || []);
    renderIssues(payload.blockers || [], payload.warnings || []);
  };

  const renderUnavailable = () => {
    panel.dataset.loadState = "unavailable";
    const status = panel.querySelector("[data-load-status]");
    if (status) {
      status.className = "tag tag-block";
      status.textContent = "Unavailable";
    }
    const track = panel.querySelector("[data-load-track]");
    if (track) {
      track.setAttribute("aria-valuenow", "0");
    }
    const fill = panel.querySelector("[data-load-fill]");
    if (fill) {
      fill.style.width = "0%";
    }
    setText("[data-load-headline]", "Agency data readiness polling is unavailable.");
    setText("[data-load-overall]", "0%");
    setText("[data-load-detail]", "The latest data-load status could not be refreshed; treat the dashboard as unverified until polling recovers.");
    setText("[data-load-checked]", "polling failed");
    setText("[data-load-health-monitor]", "polling failed");
    setText("[data-load-blockers]", 1);
    renderDatasetRows([]);
    renderLaneRows([]);
    renderFreshnessRows([]);
    renderIssues(
      [{ kind: "polling", item: "data_load_status", reason: "Data-load polling failed.", status_class: "block" }],
      []
    );
  };

  const poll = guardedPoller(async () => {
    try {
      render(await fetchJsonWithTimeout(endpoint));
    } catch (_error) {
      renderUnavailable();
    }
  });

  window.setInterval(poll, 5000);
  poll();
})();
