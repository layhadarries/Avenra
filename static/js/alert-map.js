/* Reported location snapshots only.
   No private browser storage or device geolocation requests. */
(function () {
  "use strict";

  class AlertMap {
    constructor() {
      this.note = document.getElementById("map-status");
      this.button = document.getElementById("map-background");
      this.features = new Map();
      this.map = null;
      this.tiles = null;
      this.fitted = false;

      if (!window.L) {
        this.note.textContent =
          "Map unavailable. Use the location information in the alert cards.";
        this.button.disabled = true;
        return;
      }

      this.map = L.map("alert-map", {
        scrollWheelZoom: false
      }).setView([-33.9249, 18.4241], 11);

      this.layers = L.layerGroup().addTo(this.map);
      this.button.disabled = true;

      this.button.addEventListener(
        "click",
        () => this.toggleBackground()
      );
    }

    time(value) {
      const date = value ? new Date(value) : null;

      return date && Number.isFinite(date.getTime())
        ? date.toLocaleString("en-ZA")
        : "Unknown";
    }

    usable(alert) {
      return (
        ["new", "acknowledged", "in_progress"].includes(alert.status) &&
        !alert.location_redacted &&
        Number.isFinite(alert.lat) &&
        Number.isFinite(alert.lng) &&
        Math.abs(alert.lat) <= 90 &&
        Math.abs(alert.lng) <= 180
      );
    }

    sync(alerts) {
      if (!this.map) return;

      const visible = alerts.filter(alert => this.usable(alert));

      if (!visible.length) {
        this.clear();
        return;
      }

      const present = new Set(visible.map(alert => alert.id));

      if ([...this.features.keys()].some(id => !present.has(id))) {
        // Clear the old viewport/background as well as removed markers.
        this.clear();
      }

      for (const alert of visible) {
        const point = [alert.lat, alert.lng];
        let feature = this.features.get(alert.id);

        if (!feature) {
          const icon = L.divIcon({
            className: "avenra-map-marker",
            html: '<span aria-hidden="true"></span>',
            iconSize: [22, 22],
            iconAnchor: [11, 11]
          });

          const marker = L.marker(point, {
            icon,
            keyboard: true,
            autoPanOnFocus: false
          }).addTo(this.layers);

          marker.getElement().setAttribute(
            "aria-label",
            "Reported location for alert " + alert.id
          );

          feature = {marker, circle: null};
          this.features.set(alert.id, feature);
        }

        feature.marker.setLatLng(point);

        const description = document.createElement("p");
        description.textContent =
          "Case " + alert.case_code +
          " · Reported location: " +
          alert.lat.toFixed(5) + ", " +
          alert.lng.toFixed(5) +
          " · Device fix time: " +
          this.time(alert.location_recorded_at);

        if (feature.marker.getPopup()) {
          feature.marker.setPopupContent(description);
        } else {
          feature.marker.bindPopup(description, {
            autoPan: false
          });
        }

        const accuracy = alert.location_accuracy;

        if (Number.isFinite(accuracy) && accuracy >= 0) {
          if (!feature.circle) {
            feature.circle = L.circle(point, {
              radius: accuracy,
              interactive: false,
              color: "#1d6f72",
              weight: 2,
              fillOpacity: 0.12
            }).addTo(this.layers);
          }

          feature.circle.setLatLng(point).setRadius(accuracy);

          const path = feature.circle.getElement();
          path.setAttribute("role", "img");
          path.setAttribute(
            "aria-label",
            "Accuracy radius for alert " +
            alert.id + ": " + accuracy + " metres"
          );
        } else if (feature.circle) {
          this.layers.removeLayer(feature.circle);
          feature.circle = null;
        }
      }

      if (!this.fitted) {
        this.map.fitBounds(
          visible.map(alert => [alert.lat, alert.lng]),
          {
            maxZoom: 16,
            padding: [35, 35],
            animate: false
          }
        );
        this.fitted = true;
      }

      this.button.disabled = false;
      this.note.textContent =
        "Showing " + visible.length +
        " reported locations. These are snapshots, not continuous tracking. " +
        "The circle shows device-reported accuracy when known.";
    }

    focus(id) {
      const feature = this.features.get(id);
      if (!this.map || !feature) return;

      this.map.setView(
        feature.marker.getLatLng(),
        16,
        {animate: false}
      );
      feature.marker.openPopup();
    }

    toggleBackground() {
      if (!this.map || !this.features.size) return;

      if (this.tiles) {
        this.map.removeLayer(this.tiles);
        this.tiles = null;
        this.button.textContent = "Load street map";
        return;
      }

      this.tiles = L.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          maxZoom: 19,
          referrerPolicy: "origin",
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">' +
            "OpenStreetMap</a> contributors"
        }
      ).addTo(this.map);

      this.tiles.on("tileerror", () => {
        this.note.textContent =
          "Street map unavailable. Reported locations remain visible.";
      });

      this.button.textContent = "Hide street map";
    }

    clear() {
      if (!this.map) return;

      this.map.closePopup();
      this.layers.clearLayers();
      this.features.clear();

      if (this.tiles) this.map.removeLayer(this.tiles);

      this.tiles = null;
      this.fitted = false;
      this.button.disabled = true;
      this.button.textContent = "Load street map";

      this.map.setView(
        [-33.9249, 18.4241],
        11,
        {animate: false}
      );

      this.note.textContent =
        "No permitted alert locations are currently displayed.";
    }

    destroy() {
      this.clear();
      if (this.map) this.map.remove();
      this.map = null;
    }
  }

  window.AlertMap = AlertMap;
})();