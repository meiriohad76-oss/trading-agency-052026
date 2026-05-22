(function () {
  const SUBMIT_PHRASE = "submit paper orders";
  const shell = document.querySelector("[data-cockpit-cycle]");
  if (!shell) {
    return;
  }

  const cycleId = shell.getAttribute("data-cockpit-cycle") || "current";
  const storageKey = `cockpit:v3:${cycleId}:staging`;
  const state = loadState();
  state.decisions = state.decisions || {};
  state.exits = state.exits || {};

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
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const raw = button.getAttribute("data-cockpit-ticker-payload") || "{}";
      try {
        populateTickerPanel(JSON.parse(raw));
      } catch (_error) {
        populateTickerPanel({});
      }
      openPanel("ticker-detail", button);
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
      button.disabled = !(ack.checked && phrase.value.trim() === SUBMIT_PHRASE);
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

  if (Object.keys(state.decisions).length || Object.keys(state.exits).length) {
    const restore = window.confirm("Restore staged cockpit decisions for this cycle?");
    if (!restore) {
      state.decisions = {};
      state.exits = {};
      state.phase = "candidates";
      saveState();
    }
  }
  showPhase(state.phase || "candidates");
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

  function populateTickerPanel(candidate) {
    const title = document.querySelector("[data-ticker-title]");
    const summary = document.querySelector("[data-ticker-summary]");
    const order = document.querySelector("[data-ticker-order-preview]");
    const conviction = document.querySelector("[data-ticker-conviction]");
    const status = document.querySelector("[data-ticker-status]");
    const llm = document.querySelector("[data-ticker-llm-rationale]");
    const gates = document.querySelector("[data-ticker-gates]");
    const evidence = document.querySelector("[data-ticker-evidence]");
    if (title) title.textContent = `${candidate.ticker || "Ticker"} Detail`;
    if (summary) summary.textContent = `${candidate.name || ""} ${candidate.sector || ""}`.trim();
    if (order) order.textContent = candidate.order_preview || "No paper order yet";
    if (conviction) conviction.textContent = candidate.score_display || "--";
    if (status) status.textContent = candidate.status_label || "--";
    if (llm) llm.textContent = candidate.llm_rationale || candidate.llm_label || "LLM not run for this ticker";
    if (gates) gates.textContent = candidate.risk_line || "No gate detail available.";
    if (evidence) {
      evidence.innerHTML = "";
      (candidate.evidence || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.tier || "evidence"}: ${item.text || ""}`;
        evidence.appendChild(li);
      });
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
