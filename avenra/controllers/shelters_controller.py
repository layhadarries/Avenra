"""Shelters API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.services.shelter_service import ShelterService
from avenra.security import current_user, device_user, require_role


class SheltersController:
    """Handles shelter listings and bed capacity updates."""

    def __init__(self, shelter_service: Optional[ShelterService] = None):
        self.shelter_service = shelter_service or ShelterService()

    def api_shelters(self):
        # Used by both survivor PWA and partner dashboard.js
        if current_user() is None and device_user() is None:
            return jsonify({"error": "unauthorized"}), 401
        return jsonify({"shelters": self.shelter_service.list_shelters()})

    @require_role("shelter", "responder", "admin")
    def update_capacity(self, shelter_id: int):
        user = current_user()
        data = request.get_json(silent=True) or {}
        res, status = self.shelter_service.update_capacity(shelter_id, user, data)
        return jsonify(res), status

    @require_role("responder", "admin")
    def nearby_services(self, alert_id: int):
        body, status = self.shelter_service.nearby_for_alert(
            alert_id,
            current_user(),
            request.args.getlist("radius_km"),
        )
        response = jsonify(body)
        response.headers["Cache-Control"] = "no-store"
        return response, status