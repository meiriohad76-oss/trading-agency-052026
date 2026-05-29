(function () {
  const SUBMIT_PHRASE = "submit paper orders";
  const DEFAULT_PREFERENCES = JSON.parse('{"colorPreset":"amber","theme":"accent","density":"full"}');
  const shell = document.querySelector("[data-cockpit-cycle]");
  if (!shell) {
    return;
  }
  document.querySelector(".topbar")?.setAttribute("hidden", "");
  document.querySelector(".v3-phase-rail")?.setAttribute("hidden", "");

  const cycleId = shell.getAttribute("data-cockpit-cycle") || "current";
  const storageKey = `cockpit:v3:${cycleId}:staging`;
  const preferenceStorageKey = "cockpit:v3:preferences";
  const state = loadState();
  const preferences = loadPreferences();
  let submitGateInvalidated = false;
  state.decisions = state.decisions || {};
  state.exits = state.exits || {};

  applyPreferences(preferences);
  restorePreferenceControls(preferences);
  setupTouchTooltips();
  setupPanelFilters("data-signal-filter", ".cockpit-signal-item", "signal");
  setupPanelFilters("data-monitor-filter", ".cockpit-monitor-item", "monitor");

  const preferencesOpen = document.querySelector("[data-cockpit-preferences-open]");
  const preferencesPanel = document.querySelector("[data-cockpit-preferences]");
  if (preferencesOpen && preferencesPanel) {
    preferencesOpen.addEventListener("click", () => {
      preferencesPanel.hidden = false;
      const firstInput = preferencesPanel.querySelector("input");
      if (firstInput) {
        firstInput.focus();
      }
    });
  }

  document.querySelectorAll("[data-cockpit-preferences-close]").forEach((button) => {
    button.addEventListener("click", () => {
      if (preferencesPanel) {
        preferencesPanel.hidden = true;
      }
    });
  });

  document.querySelectorAll("[name='cockpit-color-preset'], [name='cockpit-theme'], [name='cockpit-density']").forEach((input) => {
    input.addEventListener("change", () => {
      const nextPreferences = readPreferenceControls();
      Object.assign(preferences, nextPreferences);
      applyPreferences(preferences);
      savePreferences(preferences);
    });
  });

  document.querySelectorAll("[data-cockpit-row-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = button.closest("[data-cockpit-candidate]");
      const detail = row ? row.querySelector(".cockpit-row-detail") : null;
      if (!detail) {
        return;
      }
      const open = detail.hasAttribute("hidden");
      detail.toggleAttribute("hidden", !open);
      button.setAttribute("aria-expanded", String(open));
    });
  });

  document.querySelectorAll("[data-cockpit-decision]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const ticker = button.getAttribute("data-cockpit-ticker") || "";
      const decision = button.getAttribute("data-cockpit-decision") || "";
      if (!ticker || !decision) {
        return;
      }
      if (isServerDecisionButton(button)) {
        markServerDecisionPending(button, decision);
        return;
      }
      state.decisions[ticker] = decision;
      saveState();
      markSelected(button.parentElement, decision);
      updateCapacity();
    });
  });

  document.querySelectorAll("[data-cockpit-exit]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const ticker = button.getAttribute("data-cockpit-ticker") || "";
      const decision = button.getAttribute("data-cockpit-exit") || "";
      if (!ticker || !decision) {
        return;
      }
      state.exits[ticker] = decision;
      saveState();
      markSelected(button.parentElement, decision);
    });
  });

  document.querySelectorAll("[data-cockpit-phase-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const phase = button.getAttribute("data-cockpit-phase-target") || "candidates";
      showPhase(phase);
      state.phase = phase;
      saveState();
    });
  });

  document.querySelectorAll("[data-cockpit-panel-target]").forEach((button) => {
    button.addEventListener("click", () => {
      openPanel(button.getAttribute("data-cockpit-panel-target") || "", button);
    });
  });

  document.querySelectorAll("[data-cockpit-panel-close]").forEach((button) => {
    button.addEventListener("click", () => closePanel());
  });

  document.querySelectorAll("[data-cockpit-ticker-detail]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const raw = button.getAttribute("data-cockpit-ticker-payload") || "{}";
      let candidate = {};
      try {
        candidate = JSON.parse(raw);
      } catch (_error) {
        candidate = {};
      }
      populateTickerPanel(candidate, { loading: true });
      openPanel("ticker-detail", button);
      await loadTickerPanelDetails(candidate);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePanel();
    }
  });

  const form = document.querySelector("[data-cockpit-clearance-form]");
  if (form) {
    const ack = form.querySelector("[data-cockpit-submit-ack]");
    const phrase = form.querySelector("[data-cockpit-submit-text]");
    const button = form.querySelector("[data-cockpit-submit-button]");
    const stateOutput = form.querySelector("[data-cockpit-submit-state]");
    const feedback = form.querySelector("[data-cockpit-submit-feedback]");
    const updateSubmitGate = () => {
      const phraseMatches = phrase.value.trim() === SUBMIT_PHRASE;
      const acknowledged = ack.checked;
      button.disabled = submitGateInvalidated || !(acknowledged && phraseMatches);
      if (feedback) {
        if (submitGateInvalidated) {
          feedback.textContent = "Submit gate reset after the last attempt. Review the manifest again.";
        } else if (!acknowledged && !phraseMatches) {
          feedback.textContent = "Type the exact phrase and acknowledge paper-only submit.";
        } else if (!acknowledged) {
          feedback.textContent = "Phrase matches. Acknowledge paper-only submit to continue.";
        } else if (!phraseMatches) {
          feedback.textContent = "Type the exact phrase: submit paper orders.";
        } else {
          feedback.textContent = "Phrase matches. Paper submit button is unlocked.";
        }
      }
    };
    ack.addEventListener("change", updateSubmitGate);
    phrase.addEventListener("input", updateSubmitGate);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      updateSubmitGate();
      if (button.disabled) {
        return;
      }
      button.disabled = true;
      if (stateOutput) {
        stateOutput.textContent = "Submitting paper manifest after server revalidation...";
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: JSON.stringify(buildSubmitPayload()),
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
        });
        const payload = await response.json().catch(() =>
          response.ok
            ? { detail: `Non-JSON submit response received with HTTP ${response.status}.` }
            : { detail: `Submit failed with HTTP ${response.status}.` }
        );
        renderSubmitResult(payload);
        if (stateOutput) {
          stateOutput.textContent = payload.detail || payload.state || "Submit response received.";
        }
        if (!response.ok) {
          return;
        }
        showPhase("cleared");
      } catch (error) {
        if (stateOutput) {
          stateOutput.textContent = `Submit failed before broker call: ${error}`;
        }
      } finally {
        phrase.value = "";
        ack.checked = false;
        updateSubmitGate();
      }
    });
    updateSubmitGate();
  }

  function buildSubmitPayload() {
    const values = (name) =>
      Array.from(form.querySelectorAll(`[name="${name}"]`)).map((input) => input.value || "");
    const tickers = values("ticker");
    const cycles = values("cycle_id");
    const asOfValues = values("as_of");
    const hashes = values("order_intent_hash");
    const notionals = values("notional_hint");
    const sides = values("side_hint");
    return {
      submit_ack: Boolean(ack.checked),
      submit_phrase: phrase.value || "",
      orders: tickers.map((ticker, index) => ({
        cycle_id: cycles[index] || "",
        ticker,
        as_of: asOfValues[index] || "",
        order_intent_hash: hashes[index] || "",
        notional_hint: notionals[index] || "",
        side_hint: sides[index] || "",
      })),
    };
  }

  setupPolicyPanel();
  discardLegacyServerDecisionMarkers();

  if (Object.keys(state.decisions).length || Object.keys(state.exits).length) {
    const pendingRestore = {
      decisions: { ...state.decisions },
      exits: { ...state.exits },
      phase: state.phase || "candidates",
    };
    state.decisions = {};
    state.exits = {};
    state.phase = "candidates";
    saveState();
    showRestoreNotice(
      () => {
        state.decisions = pendingRestore.decisions;
        state.exits = pendingRestore.exits;
        state.phase = pendingRestore.phase;
        saveState();
        restoreMarks();
        updateCapacity();
        showPhase(state.phase || "candidates");
      },
      () => {
        saveState();
      }
    );
  }
  const scenarioState = shell.getAttribute("data-cockpit-scenario") || "normal";
  const defaultPhase = scenarioState === "submitted" ? "cleared" : "candidates";
  const forcedScenarioPhase = scenarioState === "submitted" ? "cleared" : (
    scenarioState === "outage" || scenarioState === "no-actionable" ? "candidates" : ""
  );
  showPhase(forcedScenarioPhase || state.phase || defaultPhase);
  restoreMarks();
  updateCapacity();
  shell.dataset.cockpitReady = "true";

  function loadState() {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch (_error) {
      return {};
    }
  }

  function saveState() {
    const payload = {
      phase: state.phase || "candidates",
      decisions: state.decisions || {},
      exits: state.exits || {},
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  }

  function loadPreferences() {
    try {
      return { ...DEFAULT_PREFERENCES, ...JSON.parse(localStorage.getItem(preferenceStorageKey) || "{}") };
    } catch (_error) {
      return { ...DEFAULT_PREFERENCES };
    }
  }

  function savePreferences(nextPreferences) {
    const payload = {
      colorPreset: nextPreferences.colorPreset || DEFAULT_PREFERENCES.colorPreset,
      theme: nextPreferences.theme || DEFAULT_PREFERENCES.theme,
      density: nextPreferences.density || DEFAULT_PREFERENCES.density,
    };
    localStorage.setItem(preferenceStorageKey, JSON.stringify(payload));
  }

  function applyPreferences(nextPreferences) {
    shell.setAttribute("data-cockpit-color-preset", nextPreferences.colorPreset || DEFAULT_PREFERENCES.colorPreset);
    shell.setAttribute("data-cockpit-theme", nextPreferences.theme || DEFAULT_PREFERENCES.theme);
    shell.setAttribute("data-cockpit-density", nextPreferences.density || DEFAULT_PREFERENCES.density);
  }

  function restorePreferenceControls(nextPreferences) {
    setPreferenceControl("cockpit-color-preset", nextPreferences.colorPreset);
    setPreferenceControl("cockpit-theme", nextPreferences.theme);
    setPreferenceControl("cockpit-density", nextPreferences.density);
  }

  function setupTouchTooltips() {
    document.querySelectorAll(".info-tip[title]").forEach((tip) => {
      if (tip.tabIndex < 0) {
        tip.tabIndex = 0;
      }
      tip.setAttribute("role", "button");
      tip.addEventListener("click", (event) => {
        event.stopPropagation();
        const isOpen = tip.getAttribute("data-tooltip-open") === "true";
        closeTouchTooltips();
        if (!isOpen) {
          tip.setAttribute("data-tooltip-open", "true");
        }
      });
      tip.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          tip.click();
        }
      });
      tip.addEventListener("blur", () => {
        tip.removeAttribute("data-tooltip-open");
      });
    });
    document.addEventListener("click", closeTouchTooltips);
  }

  function closeTouchTooltips() {
    document.querySelectorAll('[data-tooltip-open="true"]').forEach((tip) => {
      tip.removeAttribute("data-tooltip-open");
    });
  }

  function setupPanelFilters(attribute, itemSelector, prefix) {
    const buttons = Array.from(document.querySelectorAll(`[${attribute}]`));
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const value = button.getAttribute(attribute) || "all";
        buttons.forEach((item) => {
          item.classList.toggle("active", item === button);
        });
        document.querySelectorAll(itemSelector).forEach((item) => {
          const visible = value === "all" || item.classList.contains(`${prefix}-${value}`);
          item.toggleAttribute("hidden", !visible);
        });
      });
    });
  }

  function showRestoreNotice(onRestore, onDiscard) {
    const notice = document.createElement("div");
    notice.className = "cockpit-restore-notice";
    notice.setAttribute("role", "alert");
    const text = document.createElement("p");
    text.textContent = "Restore local planning markers from your last session? These are not server approvals.";
    const restore = document.createElement("button");
    restore.className = "button button-secondary";
    restore.type = "button";
    restore.textContent = "Restore";
    restore.addEventListener("click", () => {
      onRestore();
      notice.remove();
    });
    const discard = document.createElement("button");
    discard.className = "button button-secondary";
    discard.type = "button";
    discard.textContent = "Discard";
    discard.addEventListener("click", () => {
      onDiscard();
      notice.remove();
    });
    notice.append(text, restore, discard);
    const rail = document.querySelector(".cockpit-phase-rail");
    if (rail) {
      rail.insertAdjacentElement("afterend", notice);
    } else {
      document.body.prepend(notice);
    }
  }

  function setPreferenceControl(name, value) {
    const input = document.querySelector(`[name="${name}"][value="${value}"]`);
    if (input) {
      input.checked = true;
    }
  }

  function readPreferenceControls() {
    return {
      colorPreset: checkedValue("cockpit-color-preset", DEFAULT_PREFERENCES.colorPreset),
      theme: checkedValue("cockpit-theme", DEFAULT_PREFERENCES.theme),
      density: checkedValue("cockpit-density", DEFAULT_PREFERENCES.density),
    };
  }

  function checkedValue(name, fallback) {
    const input = document.querySelector(`[name="${name}"]:checked`);
    return input ? input.value : fallback;
  }

  function markSelected(container, decision) {
    if (!container) {
      return;
    }
    container.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("selected", button.textContent.trim().toLowerCase() === decision);
    });
  }

  function isServerDecisionButton(button) {
    return button.type === "submit" || Boolean(button.closest("form"));
  }

  function markServerDecisionPending(button, decision) {
    const row = button.closest("[data-cockpit-candidate]");
    if (row) {
      row.setAttribute("data-cockpit-server-decision-pending", decision);
    }
    button.setAttribute(
      "title",
      "Sending to server; this is not a server approval until the page reloads with a recorded review."
    );
  }

  function discardLegacyServerDecisionMarkers() {
    state.decisions = state.decisions || {};
    let changed = false;
    Object.entries(state.decisions).forEach(([ticker, decision]) => {
      const button = document.querySelector(`[data-cockpit-decision="${decision}"][data-cockpit-ticker="${ticker}"]`);
      if (button && isServerDecisionButton(button)) {
        delete state.decisions[ticker];
        changed = true;
      }
    });
    if (changed) {
      saveState();
    }
  }

  function restoreMarks() {
    state.decisions = state.decisions || {};
    state.exits = state.exits || {};
    Object.entries(state.decisions).forEach(([ticker, decision]) => {
      const button = document.querySelector(`[data-cockpit-decision="${decision}"][data-cockpit-ticker="${ticker}"]`);
      if (button) {
        markSelected(button.parentElement, decision);
      }
    });
    Object.entries(state.exits).forEach(([ticker, decision]) => {
      const button = document.querySelector(`[data-cockpit-exit="${decision}"][data-cockpit-ticker="${ticker}"]`);
      if (button) {
        markSelected(button.parentElement, decision);
      }
    });
  }

  function updateCapacity() {
    state.decisions = state.decisions || {};
    let staged = 0;
    document.querySelectorAll("[data-cockpit-candidate]").forEach((row) => {
      const ticker = row.getAttribute("data-cockpit-ticker") || "";
      if (state.decisions[ticker] === "approve") {
        staged += Number(row.getAttribute("data-cockpit-notional") || "0");
      }
    });
    document.querySelectorAll("[data-capacity-gross-post]").forEach((target) => {
      target.setAttribute("data-staged-notional", String(staged));
    });
  }

  function showPhase(phase) {
    document.querySelectorAll("[data-cockpit-phase]").forEach((section) => {
      section.toggleAttribute("hidden", section.getAttribute("data-cockpit-phase") !== phase);
    });
    document.querySelectorAll("[data-cockpit-phase-target]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-cockpit-phase-target") === phase);
    });
  }

  let activeTrigger = null;

  function openPanel(name, trigger) {
    const panel = document.querySelector(`#cockpit-panel-${name}`);
    if (!panel) {
      return;
    }
    closePanel();
    activeTrigger = trigger || null;
    panel.hidden = false;
    const close = panel.querySelector("button[data-cockpit-panel-close]");
    if (close) {
      close.focus();
    }
  }

  function closePanel() {
    document.querySelectorAll(".cockpit-panel").forEach((panel) => {
      panel.hidden = true;
    });
    if (activeTrigger) {
      activeTrigger.focus();
    }
    activeTrigger = null;
  }

  async function loadTickerPanelDetails(candidate) {
    const ticker = candidate.ticker || "";
    if (!ticker) {
      return;
    }
    try {
      const response = await fetch(`/api/cockpit/ticker/${encodeURIComponent(ticker)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`detail API returned HTTP ${response.status}`);
      }
      const payload = await response.json();
      populateTickerPanel({ ...candidate, ...payload }, { loading: false });
    } catch (error) {
      populateTickerPanel({
        ...candidate,
        detail_load_error: `Could not load full candidate brief: ${error}`,
      }, { loading: false });
    }
  }

  function populateTickerPanel(candidate, options = {}) {
    const panel = document.querySelector("#cockpit-panel-ticker-detail");
    if (!panel) {
      return;
    }
    const title = panel.querySelector("[data-ticker-title]");
    const summary = panel.querySelector("[data-ticker-summary]");
    const headline = panel.querySelector("[data-ticker-headline]");
    const order = panel.querySelector("[data-ticker-order-preview]");
    const conviction = panel.querySelector("[data-ticker-conviction]");
    const status = panel.querySelector("[data-ticker-status]");
    const dataHealth = panel.querySelector("[data-ticker-data-health]");
    const sources = panel.querySelector("[data-ticker-sources]");
    const review = panel.querySelector("[data-ticker-review]");
    const nextStep = panel.querySelector("[data-ticker-next-step]");
    const llm = panel.querySelector("[data-ticker-llm-rationale]");
    const gates = panel.querySelector("[data-ticker-gates]");
    const evidence = panel.querySelector("[data-ticker-evidence]");
    const support = panel.querySelector("[data-ticker-support]");
    const caution = panel.querySelector("[data-ticker-caution]");
    const signals = panel.querySelector("[data-ticker-signals]");
    const detailLink = panel.querySelector("[data-ticker-detail-link]");
    const richLlm = candidate.llm || {};
    const health = candidate.data_health || {};
    const reviewState = candidate.review || {};
    if (title) title.textContent = `${candidate.ticker || "Ticker"} Detail`;
    if (summary) summary.textContent = candidate.summary || `${candidate.name || ""} ${candidate.sector || ""}`.trim();
    if (headline) headline.textContent = candidate.headline || "Candidate brief is loading.";
    if (order) order.textContent = candidate.order_preview || "No paper order yet";
    if (conviction) conviction.textContent = candidate.conviction_pct ? `${candidate.conviction_pct}%` : candidate.score_display || "--";
    if (status) status.textContent = candidate.status_label || "--";
    if (dataHealth) dataHealth.textContent = health.status_label || (options.loading ? "Loading..." : "--");
    if (sources) {
      const sourceCount = candidate.source_count || 0;
      const confirmedCount = candidate.confirmed_signal_count || 0;
      sources.textContent = sourceCount || confirmedCount ? `${sourceCount} sources / ${confirmedCount} confirmed` : "--";
    }
    if (review) review.textContent = reviewState.decision || candidate.human_review_decision || "Pending";
    if (nextStep) nextStep.textContent = candidate.next_step || health.recommended_action || "Review the full candidate brief before acting.";
    if (llm) {
      const llmStatus = richLlm.status_label || candidate.llm_label || "LLM not run";
      const llmAction = richLlm.action ? ` ${richLlm.action}.` : "";
      const llmConfidence = richLlm.confidence_pct ? ` Confidence ${richLlm.confidence_pct}%.` : "";
      const rationale = richLlm.rationale || candidate.llm_rationale || candidate.llm_label || "LLM not run for this ticker";
      llm.textContent = `${llmStatus}.${llmAction}${llmConfidence} ${rationale}`.trim();
    }
    if (gates) gates.textContent = candidate.risk_line || "No gate detail available.";
    renderCards(support, candidate.support_cards || [], "No constructive driver is active in the loaded brief.");
    renderCards(caution, candidate.caution_cards || [], "No caution driver is active in the loaded brief.");
    renderSignals(signals, candidate.signals || [], options.loading);
    if (detailLink) {
      detailLink.href = candidate.detail_url || (candidate.ticker ? `/candidates/${candidate.ticker}` : "#");
    }
    if (evidence) {
      evidence.innerHTML = "";
      if (candidate.detail_load_error) {
        const li = document.createElement("li");
        li.textContent = candidate.detail_load_error;
        evidence.appendChild(li);
      }
      (candidate.decision_points || candidate.evidence || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.label || item.tier || "evidence"}: ${item.detail || item.text || ""}`;
        evidence.appendChild(li);
      });
    }
  }

  function renderCards(target, cards, emptyText) {
    if (!target) {
      return;
    }
    target.innerHTML = "";
    if (!cards.length) {
      const item = document.createElement("article");
      item.textContent = emptyText;
      target.appendChild(item);
      return;
    }
    cards.forEach((card) => {
      const item = document.createElement("article");
      const title = document.createElement("strong");
      const detail = document.createElement("p");
      const meta = document.createElement("small");
      title.textContent = card.label || "Evidence";
      detail.textContent = card.detail || "Detail unavailable.";
      meta.textContent = card.meta || "";
      item.append(title, detail, meta);
      target.appendChild(item);
    });
  }

  function renderSignals(target, signals, loading) {
    if (!target) {
      return;
    }
    target.innerHTML = "";
    if (loading) {
      const item = document.createElement("article");
      item.textContent = "Loading detailed signal evidence...";
      target.appendChild(item);
      return;
    }
    if (!signals.length) {
      const item = document.createElement("article");
      item.textContent = "No primary signal evidence was returned for this ticker.";
      target.appendChild(item);
      return;
    }
    signals.forEach((signal) => {
      const item = document.createElement("article");
      const title = document.createElement("strong");
      const summary = document.createElement("p");
      const hardEvidence = document.createElement("p");
      const meta = document.createElement("small");
      const signalName = signal.display_name || signal.label || "Signal process";
      title.textContent = `${signalName} / ${signal.direction || "NEUTRAL"}`;
      summary.textContent = signal.summary || "Signal summary unavailable.";
      hardEvidence.textContent = signal.hard_evidence ? `Hard evidence: ${signal.hard_evidence}` : signal.detail || "";
      meta.textContent = [
        signal.actionability,
        signal.freshness,
        signal.verification,
        signal.source,
        signal.timestamp,
      ].filter(Boolean).join(" / ");
      item.append(title, summary, hardEvidence, meta);
      target.appendChild(item);
    });
  }

  function setupPolicyPanel() {
    const form = document.querySelector("[data-policy-form]");
    if (!form) {
      return;
    }
    const fields = Array.from(form.querySelectorAll("[data-policy-field]"));
    const confirm = form.querySelector("[data-policy-confirm-apply]");
    const applyButton = form.querySelector("[data-policy-apply-button]");
    const output = form.querySelector("[data-policy-apply-state]");
    const diffTarget = form.querySelector("[data-policy-diff]");
    const refreshPolicyDiff = () => {
      const changes = fields
        .map((field) => ({
          key: field.getAttribute("data-policy-field"),
          deployed: field.getAttribute("data-policy-deployed") || "",
          staged: field.value,
        }))
        .filter((row) => row.deployed !== row.staged);
      if (diffTarget) {
        const title = document.createElement("h3");
        title.textContent = "Policy diff";
        if (!changes.length) {
          const empty = document.createElement("p");
          empty.textContent = "No staged changes.";
          diffTarget.replaceChildren(title, empty);
        } else {
          const list = document.createElement("ul");
          changes.forEach((row) => {
            const item = document.createElement("li");
            const key = document.createElement("strong");
            key.textContent = row.key || "policy";
            const detail = document.createElement("span");
            detail.textContent = `: deployed ${row.deployed}, staged ${row.staged}`;
            item.append(key, detail);
            list.appendChild(item);
          });
          diffTarget.replaceChildren(title, list);
        }
      }
      applyButton.disabled = !(confirm.checked && changes.length);
      return changes;
    };
    fields.forEach((field) => {
      field.addEventListener("input", () => {
        refreshPolicyDiff();
      });
    });
    confirm.addEventListener("change", refreshPolicyDiff);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const changes = refreshPolicyDiff();
      if (!changes.length || !confirm.checked) {
        return;
      }
      const body = {};
      fields.forEach((field) => {
        body[field.getAttribute("data-policy-field")] = Number(field.value);
      });
      applyButton.disabled = true;
      if (output) {
        output.textContent = "Applying policy to the next cycle...";
      }
      try {
        const response = await fetch("/api/policy", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          throw new Error(`policy update failed with HTTP ${response.status}`);
        }
        if (output) {
          output.textContent = "Policy saved for the next cycle. Refresh cockpit before submitting paper orders.";
        }
        invalidateSubmitGate();
      } catch (error) {
        if (output) {
          output.textContent = `Policy update failed: ${error}`;
        }
      } finally {
        refreshPolicyDiff();
      }
    });
    refreshPolicyDiff();
  }

  function invalidateSubmitGate() {
    submitGateInvalidated = true;
    const submitButton = document.querySelector("[data-cockpit-submit-button]");
    const stateOutput = document.querySelector("[data-cockpit-submit-state]");
    if (submitButton) {
      submitButton.disabled = true;
    }
    if (stateOutput) {
      stateOutput.textContent = "Refresh cockpit after policy apply before submitting paper orders.";
    }
  }

  function renderSubmitResult(payload) {
    const target = document.querySelector("[data-cockpit-submit-results]");
    if (!target) {
      return;
    }
    const accepted = payload.accepted || [];
    const rejected = payload.rejected || [];
    target.replaceChildren();
    const appendRow = (row, status) => {
      const article = document.createElement("article");
      article.className = "cockpit-manifest-row";
      const ticker = document.createElement("strong");
      const statusText = document.createElement("span");
      const detail = document.createElement("span");
      ticker.textContent = row.ticker || "Order";
      statusText.textContent = status;
      detail.textContent = row.broker_order_id || row.detail || "";
      article.append(ticker, statusText, detail);
      target.appendChild(article);
    };
    accepted.forEach((row) => appendRow(row, "accepted"));
    rejected.forEach((row) => appendRow(row, "rejected"));
  }
})();
