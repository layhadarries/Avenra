/* Scoped audit browser. No private records are stored locally. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-audit-view]");
    const portal = window.Portal;
    if (!root || !portal) return;

    const form = document.getElementById("audit-filters");
    const caseInput = document.getElementById("audit-case");
    const categoryInput = document.getElementById("audit-category");
    const rows = document.getElementById("audit-rows");
    const status = document.getElementById("audit-status");
    const pageLabel = document.getElementById("audit-page");
    const previous = document.getElementById("audit-previous");
    const next = document.getElementById("audit-next");
    const refresh = document.getElementById("audit-refresh");

    let generation = 0;
    let pageNumber = 1;
    let filters = { case_code: "", category: "" };
    let timer;

    function clearResults() {
      rows.replaceChildren();
      pageLabel.textContent = "";
      previous.disabled = true;
      next.disabled = true;
    }

    function appendCell(row, value) {
      const cell = document.createElement("td");
      cell.textContent = value == null ? "—" : String(value);
      row.append(cell);
    }

    function displayTime(value) {
      if (typeof value !== "string" || !value) {
        return "Time unavailable";
      }

      const date = new Date(value);
      return Number.isFinite(date.getTime())
        ? date.toLocaleString("en-ZA")
        : "Time unavailable";
    }

    async function load(requestedPage) {
      const current = ++generation;
      clearResults();

      if (portal.stopped) return;

      status.textContent = "Loading audit activity…";
      rows.setAttribute("aria-busy", "true");

      const params = new URLSearchParams({
        page: String(requestedPage),
        limit: "25"
      });

      if (filters.case_code) {
        params.set("case_code", filters.case_code);
      }
      if (filters.category) {
        params.set("category", filters.category);
      }

      try {
        const response = await portal.request(
          "/api/audit-log?" + params.toString()
        );
        if (current !== generation || portal.stopped) return;

        if (response.status === 403 || response.status === 404) {
          portal.clear();
          window.location.reload();
          return;
        }

        const body = await response.json();
        if (current !== generation || portal.stopped) return;

        if (!response.ok) {
          throw new Error("Audit request rejected");
        }

        if (
          !Array.isArray(body.events) ||
          !Number.isSafeInteger(body.page) ||
          body.page !== requestedPage ||
          !Number.isSafeInteger(body.total) ||
          body.total < 0 ||
          typeof body.has_next !== "boolean"
        ) {
          throw new Error("Invalid audit response");
        }

        const fragment = document.createDocumentFragment();

        for (const event of body.events) {
          const row = document.createElement("tr");
          appendCell(row, displayTime(event.ts));
          appendCell(row, event.actor);
          appendCell(row, event.action);
          appendCell(row, event.case_code);
          appendCell(row, event.detail);
          fragment.append(row);
        }

        rows.replaceChildren(fragment);
        pageNumber = body.page;
        pageLabel.textContent = "Page " + pageNumber;
        previous.disabled = pageNumber <= 1;
        next.disabled = !body.has_next;

        status.textContent = body.events.length
          ? body.total + " matching recorded event(s)."
          : "No recorded events match these filters.";
      } catch (_) {
        if (current !== generation || portal.stopped) return;
        clearResults();
        status.textContent =
          "Audit activity could not be loaded. " +
          "Check your connection and refresh.";
      } finally {
        if (current === generation && !portal.stopped) {
          rows.removeAttribute("aria-busy");
        }
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!form.reportValidity()) return;

      filters = {
        case_code: caseInput.value.trim().toUpperCase(),
        category: categoryInput.value
      };
      load(1);
    });

    refresh.addEventListener("click", function () {
      load(pageNumber);
    });

    previous.addEventListener("click", function () {
      if (!previous.disabled) load(pageNumber - 1);
    });

    next.addEventListener("click", function () {
      if (!next.disabled) load(pageNumber + 1);
    });

    portal.onClear(function () {
      generation += 1;
      clearInterval(timer);
      clearResults();
      status.textContent = "";
    });

    timer = setInterval(function () {
      if (!document.hidden && !portal.stopped) load(pageNumber);
    }, 15000);

    load(1);
  });
})();