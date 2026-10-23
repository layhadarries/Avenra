"""Alerts API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.services.alert_service import AlertService
from avenra.security import device_user, current_user, require_role
from avenra.config import Config
from avenra.services.portal_service import PortalService


class AlertsController:
    """Handles emergency alert dispatching, querying, and responder acknowledgment."""

    def __init__(self, alert_service: Optional[AlertService] = None):
        self.alert_service = alert_service or AlertService()

    def create_alert(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        data = request.get_json(silent=True) or {}
        res, status = self.alert_service.create_alert(
            survivor=survivor,
            client_id=data.get("client_id"),
            raw_lat=data.get("lat"),
            raw_lng=data.get("lng"),
            raw_client_ts=data.get("client_ts"),
        )
        return jsonify(res), status

    @require_role(*Config.ALERT_ROLES)
    def list_alerts(self):
        body, status = PortalService().list_alerts(current_user(), request.args)
        return jsonify(body), status

    @require_role(*Config.ALERT_ROLES)
    def acknowledge_alert(self, alert_id: int):
        user = current_user()
        res, status = self.alert_service.acknowledge_alert(alert_id, user)
        return jsonify(res), status

    @require_role(*Config.ALERT_ROLES)
    def change_alert(self, alert_id: int):
        body, status = PortalService().change_alert(alert_id, current_user(), request.get_json(silent=True) or {})
        return jsonify(body), status

    def alert_status(self, alert_id: int):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        res, status = self.alert_service.get_alert_status(alert_id, survivor)
        return jsonify(res), status
