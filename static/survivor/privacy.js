/* Clear Sky: Survivor privacy toggles & case access trail (Stage 4).
   Immediate read-time enforcement; zero hardcoded tokens in markup. */
(function () {
  "use strict";

  var DEVICE_TOKEN = "demo-device";
  var banner = document.getElementById("status-banner");
  var accessList = document.getElementById("access-list");
  var quickExitBtn = document.getElementById("quick-exit");

  var consentItems = [
    "location_sharing",
    "shelter_referral_sharing",
    "diary_sharing"
  ];

  function showBanner(message, isError) {
    if (!banner) return;
    banner.textContent = message;
    banner.style.color = isError ? "#b91c1c" : "var(--amber)";
    banner.style.background = isError ? "#fee2e2" : "var(--amber-bg)";
    banner.hidden = false;
  }

  function hideBanner() {
    if (banner) banner.hidden = true;
  }

  function escapeHtml(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return "";
    try {
      var d = new Date(isoStr);
      return d.toLocaleDateString("en-ZA", { month: "short", day: "numeric" }) +
        " · " + d.toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit" });
    } catch (_e) {
      return isoStr;
    }
  }

  // ---------------------------------------------------------------- Consents

  function loadConsents() {
    fetch("/api/consents", {
      headers: { "X-Device-Token": DEVICE_TOKEN },
      cache: "no-store",
      credentials: "same-origin"
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        hideBanner();
        var consentsArray = Array.isArray(data.consents) 
          ? data.consents 
          : Object.values(data.consents || {});

        consentsArray.forEach(function(c) {
          var input = document.getElementById("consent-" + c.item);
          var titleEl = document.getElementById("title-" + c.item);
          var descEl = document.getElementById("desc-" + c.item);
          
          if (input) {
            input.checked = c.active !== false;
            input.disabled = false;
          }
          if (titleEl && c.label) {
            titleEl.textContent = c.label;
          }
          if (descEl && c.granted_to) {
            descEl.textContent = "Shared with: " + c.granted_to;
          }
        });
      })
      .catch(function () {
        showBanner("Offline — viewing saved privacy settings.", false);
      });
  }

  function updateConsent(itemKey, isActive, inputEl) {
    inputEl.disabled = true;
    fetch("/api/consents", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Device-Token": DEVICE_TOKEN
      },
      body: JSON.stringify({ item: itemKey, active: isActive })
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function () {
        hideBanner();
        inputEl.disabled = false;
      })
      .catch(function () {
        // Rollback switch on failure to avoid giving a false safety assurance
        inputEl.checked = !isActive;
        inputEl.disabled = false;
        showBanner("Couldn't save change. Please check your connection.", true);
      });
  }

  consentItems.forEach(function (key) {
    var input = document.getElementById("consent-" + key);
    if (input) {
      input.addEventListener("change", function () {
        updateConsent(key, input.checked, input);
      });
    }
  });

  // ---------------------------------------------------------------- Access Trail

  function loadAccessTrail() {
    fetch("/api/my-access", {
      headers: { "X-Device-Token": DEVICE_TOKEN },
      cache: "no-store",
      credentials: "same-origin"
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var entries = data.events || data.access_log || [];
        if (!entries.length) {
          accessList.innerHTML =
            '<div class="access-row"><span style="color: var(--dusty-blue);">No activity recorded yet on your case.</span></div>';
          return;
        }
        accessList.innerHTML = "";
        entries.forEach(function (entry) {
          var row = document.createElement("div");
          row.className = "access-row";
          var actor = escapeHtml(entry.actor_name || entry.actor || "Authorized responder");
          var action = escapeHtml(entry.action || entry.description || "Viewed case record");
          var time = formatTimestamp(entry.viewed_at || entry.created_at);

          row.innerHTML =
            '<div>' +
              '<div class="access-actor">' + actor + '</div>' +
              '<div class="access-action">' + action + '</div>' +
            '</div>' +
            '<div class="access-time">' + time + '</div>';
          accessList.appendChild(row);
        });
      })
      .catch(function () {
        accessList.innerHTML =
          '<div class="access-row"><span style="color: var(--dusty-blue);">Activity history is currently unavailable offline.</span></div>';
      });
  }

  // ---------------------------------------------------------------- Quick Exit & Revalidation

  function quickExit(event) {
    if (event) event.preventDefault();
    location.replace("/survivor/cover.html");
  }

  if (quickExitBtn) quickExitBtn.addEventListener("click", quickExit);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") quickExit(e);
  });

  window.addEventListener("pageshow", function(event) {
      if (event.persisted) {
          loadConsents();
          loadAccessTrail();
      }
  });

  // Init
  loadConsents();
  loadAccessTrail();
})();