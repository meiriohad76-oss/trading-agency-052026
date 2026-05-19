(() => {
  function signalPairs(table) {
    const body = table.querySelector("tbody");
    if (!body) {
      return [];
    }
    const detailByKey = new Map(
      Array.from(body.querySelectorAll("tr.signal-detail-row")).map((row) => [
        row.dataset.detailFor || "",
        row,
      ]),
    );
    return Array.from(body.querySelectorAll("tr.signal-summary-row")).map((summary) => ({
      summary,
      detail: detailByKey.get(summary.dataset.signalKey || "") || null,
    }));
  }

  function sortValue(row, key, type) {
    const value = row.dataset[`sort${key.charAt(0).toUpperCase()}${key.slice(1)}`] || "";
    if (type === "number") {
      const parsed = Number.parseFloat(value);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
    return value.toLocaleLowerCase();
  }

  function sortTable(table, button) {
    const body = table.querySelector("tbody");
    if (!body) {
      return;
    }
    const key = button.dataset.sortKey || "ticker";
    const type = button.dataset.sortType || "text";
    const previous = button.dataset.sortActive;
    const direction = previous ? (previous === "asc" ? "desc" : "asc") : (
      type === "number" ? "desc" : "asc"
    );
    table.querySelectorAll(".table-sort-button").forEach((item) => {
      delete item.dataset.sortActive;
    });
    button.dataset.sortActive = direction;
    const pairs = signalPairs(table).sort((left, right) => {
      const leftValue = sortValue(left.summary, key, type);
      const rightValue = sortValue(right.summary, key, type);
      if (leftValue < rightValue) {
        return direction === "asc" ? -1 : 1;
      }
      if (leftValue > rightValue) {
        return direction === "asc" ? 1 : -1;
      }
      return String(left.summary.dataset.sortTicker || "").localeCompare(
        String(right.summary.dataset.sortTicker || ""),
      );
    });
    pairs.forEach((pair) => {
      body.appendChild(pair.summary);
      if (pair.detail) {
        body.appendChild(pair.detail);
      }
    });
    if (window.applyResponsiveTableLabels) {
      window.applyResponsiveTableLabels();
    }
  }

  function toggleInspector(button) {
    const targetId = button.dataset.inspectTarget;
    if (!targetId) {
      return;
    }
    const details = document.getElementById(targetId);
    if (!(details instanceof HTMLDetailsElement)) {
      return;
    }
    details.open = !details.open;
    const row = button.closest("tr.signal-summary-row");
    if (row) {
      row.classList.toggle("signal-row-open", details.open);
    }
    if (details.open) {
      const tableWrap = button.closest(".table-wrap");
      if (tableWrap) {
        tableWrap.scrollLeft = 0;
      }
      details.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function bindSignalsTable() {
    document.querySelectorAll("table[data-sortable-signals='true']").forEach((table) => {
      table.querySelectorAll(".table-sort-button").forEach((button) => {
        button.addEventListener("click", () => sortTable(table, button));
      });
    });
    document.querySelectorAll(".inspect-signal-button").forEach((button) => {
      button.addEventListener("click", () => toggleInspector(button));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindSignalsTable);
  } else {
    bindSignalsTable();
  }
})();
