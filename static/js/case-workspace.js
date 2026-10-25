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
    const referralStatus = document.getElementById("referral-status");
    const diaryRefresh = document.getElementById("diary-refresh");
    const diaryEntries = document.getElementById("case-diary-entries");
    const diaryStatus = document.getElementById("diary-status");
    const portal = window.Portal;

    if (!root || !portal) return;

    let generation = 0;
    let diaryGeneration = 0;
    let referralSending = false;

    function clearResults() {
      if (results) {
        results.replaceChildren();
        results.removeAttribute("aria-busy");
      }
      if (status) status.textContent = "";
      if (referralStatus) referralStatus.textContent = "";
    }

    function clearDiary() {
      if (diaryEntries) {
        diaryEntries.querySelectorAll("img").forEach(function (img) {
          img.removeAttribute("src");
        });
        diaryEntries.replaceChildren();
        diaryEntries.removeAttribute("aria-busy");
      }
      if (diaryStatus) diaryStatus.textContent = "";
    }

    portal.onClear(function () {
      generation += 1;
      diaryGeneration += 1;
      clearResults();
      clearDiary();
    });

    async function loadDiary() {
      if (!diaryEntries || !diaryStatus) return;

      const current = ++diaryGeneration;
      const caseCode = (root.dataset.caseCode || "").trim();
      if (!caseCode || portal.stopped) {
        clearDiary();
        return;
      }

      diaryStatus.textContent = "Checking shared diary entries…";
      diaryEntries.setAttribute("aria-busy", "true");

      try {
        const response = await portal.request(
          "/api/diary?case_code=" + encodeURIComponent(caseCode)
        );

        if (current !== diaryGeneration || portal.stopped) return;

        if (response.status === 403 || response.status === 404) {
          portal.clear();
          window.location.reload();
          return;
        }

        const body = await response.json();
        if (current !== diaryGeneration || portal.stopped) return;

        if (!response.ok) {
          clearDiary();
          diaryStatus.textContent =
            "Diary entries could not be loaded. Try refreshing.";
          return;
        }

        if (body.consent_active === false) {
          clearDiary();
          diaryStatus.textContent = "Diary-sharing consent is not active.";
          return;
        }

        if (!Array.isArray(body.entries)) {
          throw new Error("Invalid diary response");
        }

        clearDiary();
        if (!body.entries.length) {
          diaryStatus.textContent = "No shared diary entries for this case.";
          return;
        }

        const fragment = document.createDocumentFragment();
        for (const entry of body.entries) {
          if (
            !Number.isSafeInteger(entry.id) ||
            entry.id <= 0 ||
            typeof entry.note !== "string"
          ) {
            throw new Error("Invalid diary entry");
          }

          const item = document.createElement("li");
          item.dataset.diaryEntryId = String(entry.id);

          const note = document.createElement("p");
          note.className = "diary-note";
          note.textContent = entry.note;

          const meta = document.createElement("p");
          meta.className = "muted diary-timestamps";
          const capturedText =
            typeof entry.captured_at === "string" && entry.captured_at
              ? entry.captured_at
              : "Not reported by device";
          const receivedText =
            (typeof entry.received_at === "string" && entry.received_at) ||

            "Time unavailable";
          meta.textContent =
            "Device-reported capture time: " +
            capturedText +
            " · Server receipt time: " +
            receivedText +
            " · Shared with assigned case staff";

          item.append(note, meta);

          if (
            entry.has_photo === true &&
            typeof entry.photo_url === "string" &&
            entry.photo_url.startsWith("/cases/diary-photo/")
          ) {
            const img = document.createElement("img");
            img.src = entry.photo_url;
            img.alt = "Shared diary photo for entry #" + entry.id;
            img.loading = "lazy";
            item.append(img);
          }

          fragment.append(item);
        }

        diaryEntries.replaceChildren(fragment);
        diaryStatus.textContent =
          body.entries.length + " shared diary entry(s) shown.";
      } catch (_) {
        if (current !== diaryGeneration || portal.stopped) return;
        clearDiary();
        diaryStatus.textContent =
          "Diary entries could not be loaded. Check your connection and retry.";
      } finally {
        if (current === diaryGeneration && !portal.stopped && diaryEntries) {
          diaryEntries.removeAttribute("aria-busy");
        }
      }
    }

    if (diaryRefresh) {
      diaryRefresh.addEventListener("click", loadDiary);
    }

    if (!alertSelect || !radiusSelect || !results || !status) return;

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
    if (refresh) refresh.addEventListener("click", loadServices);

    loadServices();
  });
})();