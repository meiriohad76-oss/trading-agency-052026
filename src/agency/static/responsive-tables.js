(() => {
  function applyResponsiveTableLabels() {
    document.querySelectorAll(".table-wrap table").forEach((table) => {
      const headers = Array.from(table.querySelectorAll("thead th")).map((header) =>
        (header.textContent || "").trim(),
      );
      table.querySelectorAll("tbody tr").forEach((row) => {
        if (row.dataset.responsiveSkip === "true") {
          return;
        }
        Array.from(row.children).forEach((cell, index) => {
          if (!(cell instanceof HTMLElement) || cell.dataset.label) {
            return;
          }
          const label = headers[index];
          if (label) {
            cell.dataset.label = label;
          }
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyResponsiveTableLabels);
  } else {
    applyResponsiveTableLabels();
  }

  window.applyResponsiveTableLabels = applyResponsiveTableLabels;
})();
