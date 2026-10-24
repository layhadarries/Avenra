/* Case lookup uses the shared staff session and stores no private data. */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-case-view]");
    const alertSelect = document.getElementById("case-alert-select");
    const radiusSelect = document.getElementById("nearby-radius");
    const refresh = document.getElementById("nearby-refresh");
    const results = document.getElementById("nearby-services");
    const status = document.getElementById("nearby-status");
    const portal = window.Portal;

    if (!root || !alertSelect || !radiusSelect || !portal) return;

    let generation = 0;

    const referralStatus = document.getElementById("referral-status");
    let referralSending = false;

    function clearResults() {
      results.replaceChildren();
      results.removeAttribute("aria-busy");
      status.textContent = "";
      referralStatus.textContent = "";
    }

    portal.onClear(function () {
      generation += 1;
      clearResults();
    });

        async function requestReferral(serviceId, alertId, selectionGeneration) {
      if (
        referralSending ||
        portal.stopped ||
        selectionGeneration !== generation
      ) return;

      referralSending = true;
      referralStatus.textContent = "Submitting referral request…";
      results.querySelectorAll("button").forEach(function (button) {
        button.disabled = true;
      });

      try {
        const response = await portal.request("/api/referrals", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            alert_id: Number(alertId),
            shelter_id: serviceId
          })
        });

        if (portal.stopped || selectionGeneration !== generation) return;

        const body = await response.json();
        if (portal.stopped || selectionGeneration !== generation) return;

        if (!response.ok) {
          const messages = {
            referral_consent_required:
              "Referral-sharing consent is required.",
            active_referral:
              "This alert already has an active referral. Review referrals.",
            alert_resolved:
              "This alert has already been resolved."
          };

          if (response.status === 403 || response.status === 404) {
            portal.clear();
            window.location.reload();
            return;
          }

          referralStatus.textContent =
            messages[body.error] ||
            "The request was not accepted. Review referrals before retrying.";
          return;
        }

        if (
          !body.referral ||
          body.referral.alert_id !== Number(alertId) ||
          body.referral.shelter_id !== serviceId
        ) {
          throw new Error("Unexpected referral receipt");
        }

        referralStatus.textContent =
          "Referral requested" +
          (body.already ? " previously" : "") +
          ". This does not confirm a place. Review referrals for its status.";
      } catch (_) {
        if (portal.stopped || selectionGeneration !== generation) return;

        referralStatus.textContent =
          "The request outcome could not be confirmed. " +
          "Review referrals before retrying.";
      } finally {
        referralSending = false;
        if (!portal.stopped) {
          results.querySelectorAll("button").forEach(function (button) {
            button.disabled = false;
          });
        }
      }
    }

    async function loadServices() {
      const current = ++generation;
      clearResults();

      if (portal.stopped) return;

      const alertId = alertSelect.value;
      const radius = radiusSelect.value;
      root.dataset.selectedAlertId = alertId;

      if (!/^[1-9]\d*$/.test(alertId) ||
          !["25", "50"].includes(radius)) {
        status.textContent = "Select a valid alert and radius.";
        return;
      }

      status.textContent = "Checking nearby services…";
      results.setAttribute("aria-busy", "true");

      try {
        const response = await portal.request(
          "/api/alerts/" + encodeURIComponent(alertId) +
          "/nearby-services?radius_km=" + encodeURIComponent(radius)
        );

        if (current !== generation || portal.stopped) return;

        if (response.status === 403 || response.status === 404) {
          // Revalidate the entire workspace before showing anything else.
          portal.clear();
          window.location.reload();
          return;
        }

        const body = await response.json();
        if (current !== generation || portal.stopped) return;

        if (!response.ok) {
          status.textContent =
            body.error === "location_unavailable"
              ? "Nearby lookup is unavailable: no usable, consented location."
              : "Services could not be loaded. Try refreshing.";
          return;
        }

        if (!Array.isArray(body.shelters)) {
          throw new Error("Invalid directory response");
        }

        const fragment = document.createDocumentFragment();

        for (const service of body.shelters) {
          if (
            typeof service.name !== "string" ||
            typeof service.distance_km !== "number" ||
            !Number.isFinite(service.distance_km) ||
            service.distance_km < 0
          ) {
            throw new Error("Invalid service response");
          }

          const item = document.createElement("li");
          const name = document.createElement("strong");
          const details = document.createElement("p");

          name.textContent = service.name;
          details.textContent =
            service.distance_km.toFixed(2) +
            " km straight-line distance · Contact to confirm";

                    if (!Number.isSafeInteger(service.id) || service.id <= 0) {
            throw new Error("Invalid service identifier");
          }

          const requestButton = document.createElement("button");
          requestButton.type = "button";
          requestButton.className = "btn btn-outline";
          requestButton.textContent = "Request referral";
          requestButton.disabled = referralSending;

          requestButton.addEventListener("click", function () {
            requestReferral(service.id, alertId, current);
          });

          item.append(name, details, requestButton);
          fragment.append(item);
        }

        results.replaceChildren(fragment);
        status.textContent = body.shelters.length
          ? body.shelters.length + " service(s) within " + radius + " km."
          : "No services with known coordinates were found within " +
            radius + " km.";
      } catch (_) {
        if (current !== generation || portal.stopped) return;
        results.replaceChildren();
        status.textContent =
          "Services could not be loaded. Check your connection and retry.";
      } finally {
        if (current === generation && !portal.stopped) {
          results.removeAttribute("aria-busy");
        }
      }
    }

    alertSelect.addEventListener("change", loadServices);
    radiusSelect.addEventListener("change", loadServices);
    refresh.addEventListener("click", loadServices);

    loadServices();
  });
})();