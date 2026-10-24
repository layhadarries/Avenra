"""Audit log API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.services.audit_service import AuditService
from avenra.security import device_user, current_user
from avenra.config import Config
from avenra.services.access_history_service import AccessHistoryService


class AuditController:
    """Handles audit trail inspection endpoints."""

    def __init__(self, audit_service: Optional[AuditService] = None):
        self.audit_service = audit_service or AuditService()

    def api_audit_log(self):
        survivor = device_user()
        if survivor is not None:
            body, status = AccessHistoryService().list_history(survivor, request.args)
            response = jsonify(body)
            response.headers["Cache-Control"] = "no-store"
            return response, status

        user = current_user()
        if user is None:
            return jsonify({"error": "sign_in_required"}), 401
        if user.role not in Config.ALERT_ROLES:
            return jsonify({"error": "forbidden"}), 403

        from avenra.repositories.portal_repository import PortalRepository
        try:
            return jsonify(PortalRepository().audit_page(user, request.args))
        except (ValueError, TypeError):
            return jsonify({"error": "invalid_filters"}), 400
