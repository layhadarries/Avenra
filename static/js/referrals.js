/* Staff referral actions use the shared session and CSRF protection. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-referrals-view]");
    const portal = window.Portal;
    const message = document.getElementById("referral-action-status");

    if (!root || !portal || !message) return;

    const busyRows = new Set();

    function renderActions(row) {
      const actions = row.querySelector("[data-referral-actions]");
      actions.replaceChildren();

      if (portal.stopped || busyRows.has(row)) return;

      if (row.dataset.status === "sent") {
        addButton(row, actions, "Accept", "accepted");
      } else if (row.dataset.status === "accepted") {
        addButton(
          row,
          actions,
          "Record confirmed placement",
          "placed"
        );
      }
            if (["sent", "accepted"].includes(row.dataset.status)) {
        const form = document.createElement("form");
        const label = document.createElement("label");
        const reason = document.createElement("textarea");
        const decline = document.createElement("button");

        reason.id = "decline-reason-" + row.dataset.referralId;
        reason.required = true;
        reason.maxLength = 200;
        reason.rows = 2;

        label.htmlFor = reason.id;
        label.textContent = "Reason for declining";

        decline.type = "submit";
        decline.className = "btn btn-outline";
        decline.textContent = "Decline";

        reason.addEventListener("input", function () {
          reason.setCustomValidity("");
        });

        form.addEventListener("submit", function (event) {
          event.preventDefault();

          const cleaned = reason.value.trim();
          reason.setCustomValidity(
            cleaned ? "" : "Enter a reason for declining."
          );
          if (!form.reportValidity()) return;

          changeStatus(row, "declined", cleaned);
        });

        form.append(label, reason, decline);
        actions.append(form);
      }
    }

    function addButton(row, actions, label, nextStatus) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-outline";
      button.textContent = label;
      button.addEventListener("click", function () {
        changeStatus(row, nextStatus);
      });
      actions.append(button);
    }

    async function changeStatus(row, nextStatus, declineReason = null) {
      if (portal.stopped || busyRows.has(row)) return;

      const id = row.dataset.referralId;
      if (!/^[1-9]\d*$/.test(id)) return;

      if (
        nextStatus === "placed" &&
        !window.confirm(
          "Have you confirmed that the person has actually been placed " +
          "with this organisation? This records a completed handover " +
          "and resolves the alert."
        )
      ) return;

      busyRows.add(row);
      row.querySelectorAll("button").forEach(function (button) {
        button.disabled = true;
      });
      message.textContent = "Saving referral status…";

      try {
        const response = await portal.request(
          "/api/referrals/" + encodeURIComponent(id) + "/status",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
              status: nextStatus,
              ...(nextStatus === "declined"
                ? { decline_reason: declineReason }
                : {})
            })
          }
        );

        if (portal.stopped) return;

        if (response.status === 403 || response.status === 404) {
          portal.clear();
          window.location.reload();
          return;
        }

        const body = await response.json();
        if (portal.stopped) return;

        if (!response.ok) {
          message.textContent =
            "The update was not accepted. Reload to check current " +
            "permissions and referral status.";
          return;
        }

        if (
          !body.referral ||
          body.referral.id !== Number(id) ||
          body.referral.status !== nextStatus
        ) {
          throw new Error("Unexpected referral receipt");
        }

                const labels = {
          accepted: "Accepted",
          declined: "Declined",
          placed: "Placed"
        };

        if (
          nextStatus === "declined" &&
          typeof body.referral.decline_reason !== "string"
        ) {
          throw new Error("Missing decline receipt");
        }

        row.dataset.status = body.referral.status;
        row.querySelector("[data-referral-status]").textContent =
          labels[nextStatus];

        row.querySelector("[data-referral-reason]").textContent =
          body.referral.decline_reason || "";

        busyRows.delete(row);
        renderActions(row);

        const messages = {
          accepted:
            "Referral accepted. Placement still requires confirmation.",
          declined:
            "Referral declined. The alert remains open for further support.",
          placed:
            "Confirmed placement recorded."
        };
        message.textContent = messages[nextStatus];

      } catch (_) {
        if (portal.stopped) return;

        message.textContent =
          "The update outcome could not be confirmed. " +
          "Reload to check its status before trying again.";
      } finally {
        busyRows.delete(row);
        // On failure, controls remain disabled until reloading.
      }
    }

    portal.onClear(function () {
      busyRows.clear();
      message.textContent = "";
    });

    root.querySelectorAll("tr[data-referral-id]").forEach(renderActions);
  });
})();