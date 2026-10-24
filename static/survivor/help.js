/* SafePath / Cape Weather: Client-side Haversine shelter sorter (Stage 3).
   Privacy guarantee: coordinates remain in local memory and are never uploaded. */
(function () {
  "use strict";

  var DEVICE_TOKEN = "demo-device";
  var listEl = document.getElementById("shelter-list");
  var freshnessTag = document.getElementById("freshness-tag");

  function haversineKm(lat1, lon1, lat2, lon2) {
    var R = 6371; // Earth radius in km
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  function getClientLocation() {
    return new Promise(function (resolve) {
      if (!("geolocation" in navigator)) {
        resolve(null);
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude
          });
        },
        function () {
          resolve(null);
        },
        { enableHighAccuracy: false, timeout: 4000, maximumAge: 600000 }
      );
    });
  }

  function formatTime(isoStr) {
    if (!isoStr) return "recently";
    try {
      var d = new Date(isoStr);
      return d.toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit" });
    } catch (_e) {
      return "recently";
    }
  }

  function renderShelters(shelters, userFix) {
    if (!shelters || !shelters.length) {
      listEl.innerHTML = '<p style="color: var(--dusty-blue); font-size: 0.9rem;">No shelters found in this area.</p>';
      return;
    }

    var processed = shelters.map(function (s) {
      var dist = null;
      if (userFix && s.lat != null && s.lng != null) {
        dist = haversineKm(userFix.lat, userFix.lng, s.lat, s.lng);
      }
      return { data: s, dist: dist };
    });

    if (userFix) {
      processed.sort(function (a, b) {
        if (a.dist == null) return 1;
        if (b.dist == null) return -1;
        return a.dist - b.dist;
      });
    }

    listEl.innerHTML = "";
    var freshest = "";

    processed.forEach(function (item) {
      var s = item.data;
      if (!freshest && s.updated_at) freshest = s.updated_at;

      var card = document.createElement("div");
      card.className = "shelter-card";

      var distHtml = item.dist != null ? item.dist.toFixed(1) + " km away" : "";
      var bedsLabel = s.accepting && s.beds_available > 0
        ? '<span class="badge-beds">' + s.beds_available + ' beds available</span>'
        : '<span class="badge-full">Full</span>';

      var walkInLabel = s.walk_ins ? "Walk-ins accepted" : "Referral only";
      var mapsUrl = "https://maps.google.com/?q=" + encodeURIComponent(s.lat + "," + s.lng);

      card.innerHTML =
        '<div class="shelter-top">' +
          '<div class="shelter-name">' + escapeHtml(s.name) + '</div>' +
          '<div class="shelter-dist">' + distHtml + '</div>' +
        '</div>' +
        '<div class="shelter-badge-row">' +
          (s.verified ? '<span class="badge-verified">&#10003; Verified</span>' : '') +
          bedsLabel +
        '</div>' +
        '<div class="shelter-detail"><strong>Hours:</strong> ' + escapeHtml(s.hours || "24/7") + '</div>' +
        '<div class="shelter-detail"><strong>Languages:</strong> ' + escapeHtml(s.languages || "English") + '</div>' +
        '<div class="shelter-detail"><strong>Access:</strong> ' + walkInLabel + '</div>' +
        '<a href="' + mapsUrl + '" target="_blank" rel="noopener noreferrer" class="directions-btn">Directions</a>';

      listEl.appendChild(card);
    });

    freshnessTag.textContent = freshest ? "Last updated " + formatTime(freshest) : "Live directory";
  }

  function escapeHtml(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function loadDirectory() {
    var locPromise = getClientLocation();
    var fetchPromise = fetch("/api/shelters", {
      headers: { "X-Device-Token": DEVICE_TOKEN }
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });

    Promise.all([fetchPromise, locPromise])
      .then(function (results) {
        var shelters = results[0].shelters || results[0];
        var fix = results[1];
        renderShelters(shelters, fix);
      })
      .catch(function () {
        listEl.innerHTML =
          '<p style="color: var(--amber); font-size: 0.9rem;">Unable to load live shelters. Please try again shortly.</p>';
        freshnessTag.textContent = "Offline";
      });
  }

  loadDirectory();
})();
