/* Staff alert queue. Private data stays in memory; Portal owns session and CSRF. */
(function () {
  'use strict';

  class AlertQueue {
    constructor(portal) {
      this.portal = portal;
      this.list = document.getElementById('alert-list');
      this.connection = document.getElementById('queue-connection');
      this.feedback = document.getElementById('queue-action');
      this.summary = document.getElementById('queue-summary');
      this.mapView = window.AlertMap ? new window.AlertMap() : null;
      this.rows = new Map();
      this.pending = new Set();
      this.loading = false;
      this.stopped = false;
      this.generation = 0;
      portal.onClear(() => this.stop());
      this.load();
    }

    clear() {
      this.rows.clear();
      this.list.replaceChildren();
      this.summary.textContent = '';
      if (this.mapView) this.mapView.clear();
    }

    stop() {
      this.stopped = true;
      this.generation += 1;
      clearTimeout(this.timer);
      this.pending.clear();
      this.clear();
      this.feedback.textContent = '';
      if (this.mapView) this.mapView.destroy();
    }

    time(value) {
      const date = value ? new Date(value) : null;
      return date && Number.isFinite(date.getTime())
        ? date.toLocaleString('en-ZA') : 'Unknown';
    }

    makeRow(alert) {
      const el = document.createElement('article');
      el.className = 'card alert-card';
      el.setAttribute('aria-label', 'Alert ' + alert.id);
      const title = document.createElement('h2');
      const status = document.createElement('p');
      const created = document.createElement('p');
      const location = document.createElement('p');
      const acknowledged = document.createElement('p');
      const notification = document.createElement('p');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-primary section-gap';
      button.textContent = 'Acknowledge';
      button.addEventListener('click', () => this.acknowledge(alert.id));
      const locate = document.createElement('button');
      locate.type = 'button';
      locate.className = 'btn btn-outline section-gap';
      locate.textContent = 'Show on map';
      locate.addEventListener('click', () => this.mapView?.focus(alert.id));
      el.append(title, status, created, location, acknowledged, notification, button, locate);
      return {el, title, status, created, location, acknowledged, notification, button, locate};
    }

    render(data) {
      const present = new Set();
      const labels = {new: 'New', acknowledged: 'Acknowledged',
        in_progress: 'In progress', resolved: 'Resolved'};
      data.alerts.forEach((alert, index) => {
        present.add(alert.id);
        let row = this.rows.get(alert.id);
        if (!row) {
          row = this.makeRow(alert);
          this.rows.set(alert.id, row);
        }
        row.title.textContent = 'Case ' + alert.case_code;
        row.status.textContent = labels[alert.status] || 'Unknown status';
        row.created.textContent = 'Pressed (device reported): ' + this.time(alert.client_ts) +
          ' · Received: ' + this.time(alert.created_at) +
          (alert.timing?.device_clock_ahead ? ' · Device clock is ahead; timing uncertain.' : '') +
          (alert.timing?.delay_seconds >= 60 ? ' · Received after a delay (device clock unverified).' : '');
        const notificationLabels = {
          queued: 'Queued; awaiting notification worker.', processing: 'Contact notification being attempted.',
          accepted: 'Provider accepted contact messages; delivery unconfirmed.',
          delivered: 'Provider reports delivery; this does not prove the message was read.',
          failed: 'Contact notification failed.', unknown: 'Contact notification outcome unknown; not automatically resent.',
          skipped: 'Contact notification skipped: hourly limit reached. The alert remains active.',
          cancelled: 'Contact notification cancelled.', partial: 'Contact notification outcomes differ; follow-up required.',
          not_requested: 'No contact notification jobs recorded.'
        };
        row.notification.textContent = notificationLabels[alert.notification?.status] || 'Contact notification status unavailable.';
        if (alert.notification?.contact_acknowledged > 0) {
          row.notification.textContent += ' Contacts who confirmed seeing it: ' + alert.notification.contact_acknowledged + '.';
        }
        const located = !alert.location_redacted &&
          Number.isFinite(alert.lat) && Number.isFinite(alert.lng);
        row.location.textContent = located
          ? 'Reported location: ' + alert.lat.toFixed(5) + ', ' + alert.lng.toFixed(5) +
            ' · Device fix time: ' + this.time(alert.location_recorded_at) +
            ' · Accuracy: ' + (Number.isFinite(alert.location_accuracy)
              ? alert.location_accuracy + ' m (device-reported)' : 'Unknown')
          : 'Location unavailable or not shared.';
        row.acknowledged.textContent = alert.acknowledged_by
          ? 'Acknowledged by ' + alert.acknowledged_by + ' · ' + this.time(alert.acknowledged_at)
          : '';
        row.locate.hidden = !located || !this.mapView?.map || alert.status === 'resolved';
        row.button.hidden = alert.status !== 'new';
        row.button.disabled = this.pending.has(alert.id);
        if (this.list.children[index] !== row.el) {
          this.list.insertBefore(row.el, this.list.children[index] || null);
        }
      });
      for (const [id, row] of this.rows) {
        if (!present.has(id)) {
          row.el.remove();
          this.rows.delete(id);
        }
      }
      if (this.mapView) this.mapView.sync(data.alerts);
      this.summary.textContent = data.alerts.length === 0
        ? 'No alerts are currently visible within your access.'
        : data.has_next
          ? 'Showing the newest 100 of ' + data.total + ' alerts in your scope; older alerts are not shown.'
          : 'Showing ' + data.alerts.length + ' alerts in your scope.';
    }

    async load() {
      if (this.stopped || this.portal.stopped || this.loading) return;
      clearTimeout(this.timer);
      this.loading = true;
      const generation = this.generation;
      try {
        const response = await this.portal.request('/api/alerts?per_page=100');
        if (this.stopped || generation !== this.generation) return;
        if (response.status === 403) {
          this.stop();
          this.connection.textContent = 'Your account cannot view this alert queue.';
          return;
        }
        if (!response.ok) throw new Error('Alert request failed');
        const data = await response.json();
        if (this.stopped || generation !== this.generation) return;
        if (!Array.isArray(data.alerts)) throw new Error('Invalid alert response');
        this.render(data);
        this.connection.textContent = 'Connected · last refreshed ' + this.time(Date.now());
      } catch (_) {
        if (!this.stopped && !this.portal.stopped && generation === this.generation) {
          this.clear();
          this.connection.textContent = 'Connection unavailable. Alert details cleared; retrying…';
        }
      } finally {
        this.loading = false;
        if (!this.stopped && !this.portal.stopped) {
          this.timer = setTimeout(() => this.load(), 2500);
        }
      }
    }

    async acknowledge(id) {
      if (this.stopped || this.portal.stopped || this.pending.has(id)) return;
      this.pending.add(id);
      this.generation += 1;
      const row = this.rows.get(id);
      if (row) row.button.disabled = true;
      this.feedback.textContent = 'Saving acknowledgement…';
      try {
        const response = await this.portal.request('/api/alerts/' + id + '/acknowledge', {method: 'POST'});
        if (this.stopped || this.portal.stopped) return;
        if (response.status === 403 || response.status === 404) this.clear();
        if (!response.ok) throw new Error('Acknowledgement not confirmed');
        const receipt = await response.json();
        if (this.stopped || this.portal.stopped) return;
        if (receipt.id !== id || !['acknowledged', 'in_progress', 'resolved'].includes(receipt.status)) {
          throw new Error('Invalid acknowledgement response');
        }
        this.feedback.textContent = 'Acknowledgement saved. Refreshing the queue…';
      } catch (_) {
        if (!this.stopped && !this.portal.stopped) {
          this.feedback.textContent = 'Acknowledgement could not be confirmed. Refreshing before you retry.';
        }
      } finally {
        this.pending.delete(id);
        if (!this.stopped && !this.portal.stopped) {
          if (row) row.button.disabled = false;
          this.load();
        }
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('alert-list') && window.Portal) new AlertQueue(window.Portal);
  });
})();
