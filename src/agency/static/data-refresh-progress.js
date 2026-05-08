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
      element.textContent = String(value);
    }
  };

  const render = (payload) => {
    const percent = Math.max(0, Math.min(Number(payload.percent_complete || 0), 100));
    panel.dataset.loadingState = String(payload.state || "idle");
    const status = panel.querySelector("[data-progress-status]");
    if (status) {
      status.className = `tag tag-${payload.status_class || "neutral"}`;
      status.textContent = String(payload.status_label || "Idle");
    }
    const track = panel.querySelector("[data-progress-track]");
    if (track) {
      track.setAttribute("aria-valuenow", String(percent));
    }
    const fill = panel.querySelector("[data-progress-fill]");
    if (fill) {
      fill.style.width = `${percent}%`;
    }
    setText("[data-progress-percent]", `${percent}%`);
    setText("[data-progress-current]", payload.current_dataset || "None");
    setText("[data-progress-jobs]", `${payload.completed_jobs || 0}/${payload.total_jobs || 0}`);
    setText("[data-progress-eta]", payload.eta_label || "not available");
    setText("[data-progress-detail]", payload.detail || "No data refresh is running.");
    setText("[data-progress-updated]", payload.updated_at || "Not recorded");
  };

  const poll = async () => {
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (response.ok) {
        render(await response.json());
      }
    } catch (_error) {
      panel.dataset.loadingState = "unavailable";
    }
  };

  window.setInterval(poll, 5000);
  poll();
})();
