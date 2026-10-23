"""Consents API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.services.consent_service import ConsentService
from avenra.repositories.user_repository import UserRepository
from avenra.security import device_user, current_user
from avenra.config import Config


class ConsentsController:
    """Handles survivor privacy consent management."""

    def __init__(
        self,
        consent_service: Optional[ConsentService] = None,
        user_repo: Optional[UserRepository] = None,
    ):
        self.consent_service = consent_service or ConsentService()
        self.user_repo = user_repo or UserRepository()

    def get_consents(self):
        survivor = device_user()
        if survivor is None:
            user = current_user()
            if user is None:
                return jsonify({"error": "unauthorized"}), 401
            if user.role not in Config.ALERT_ROLES:
                return jsonify({"error": "forbidden"}), 403
            survivor = self.user_repo.get_survivor_by_case(Config.DEMO_CASE_CODE)

        return jsonify({"consents": self.consent_service.get_consents(survivor.id)})

    def update_consent(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        data = request.get_json(silent=True) or {}
        res, status = self.consent_service.update_consent(
            survivor=survivor,
            item=data.get("item"),
            active=data.get("active"),
        )
        return jsonify(res), status
