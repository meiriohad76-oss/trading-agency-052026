(function () {
  const SUBMIT_PHRASE = "submit paper orders";
  const DEFAULT_PREFERENCES = JSON.parse('{"colorPreset":"amber","theme":"accent","density":"full"}');
  const shell = document.querySelector("[data-cockpit-cycle]");
  if (!shell) {
    return;
  }

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
    const updateSubmitGate = () => {
      button.disabled = submitGateInvalidated || !(ack.checked && phrase.value.trim() === SUBMIT_PHRASE);
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
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        const payload = await response.json();
        renderSubmitResult(payload);
        if (stateOutput) {
          stateOutput.textContent = payload.detail || payload.state || "Submit response received.";
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

  setupPolicyPanel();

  if (Object.keys(state.decisions).length || Object.keys(state.exits).length) {
    const restore = window.confirm("Restore staged cockpit decisions for this cycle?");
    if (!restore) {
      state.decisions = {};
      state.exits = {};
      state.phase = "candidates";
      saveState();
    }
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
      title.textContent = `${signal.lane || "Signal"} / ${signal.direction || "NEUTRAL"}`;
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
        if (!changes.length) {
          diffTarget.innerHTML = "<h3>Policy diff</h3><p>No staged changes.</p>";
        } else {
          diffTarget.innerHTML = `<h3>Policy diff</h3><ul>${changes
            .map((row) => `<li><strong>${row.key}</strong>: deployed ${row.deployed}, staged ${row.staged}</li>`)
            .join("")}</ul>`;
        }
      }
      applyButton.disabled = !(confirm.checked && changes.length);
      return changes;
    };
    fields.forEach((field) => {
      field.addEventListener("input", () => {
        refreshPolicyDiff();
        invalidateSubmitGate();
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
    target.innerHTML = "";
    [...accepted, ...rejected].forEach((row) => {
      const article = document.createElement("article");
      article.className = "cockpit-manifest-row";
      const status = accepted.includes(row) ? "accepted" : "rejected";
      article.innerHTML = `<strong>${row.ticker || "Order"}</strong><span>${status}</span><span>${row.broker_order_id || row.detail || ""}</span>`;
      target.appendChild(article);
    });
  }
})();
