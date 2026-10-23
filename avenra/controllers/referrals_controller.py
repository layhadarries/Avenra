"""Referrals API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.services.referral_service import ReferralService
from avenra.security import current_user, require_role
from avenra.config import Config


class ReferralsController:
    """Handles referral creation, tracking, and placement workflows."""

    def __init__(self, referral_service: Optional[ReferralService] = None):
        self.referral_service = referral_service or ReferralService()

    @require_role("responder", "shelter", "admin")
    def list_referrals(self):
        user = current_user()
        return jsonify({"referrals": self.referral_service.list_referrals(user)})

    @require_role(*Config.ALERT_ROLES)
    def create_referral(self):
        user = current_user()
        data = request.get_json(silent=True) or {}
        try:
            alert_id = int(data.get("alert_id"))
            shelter_id = int(data.get("shelter_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "alert_id_and_shelter_id_required"}), 400

        res, status = self.referral_service.create_referral(alert_id, shelter_id, user)
        return jsonify(res), status

    @require_role("shelter", "responder", "admin")
    def update_referral_status(self, ref_id: int):
        user = current_user()
        data = request.get_json(silent=True) or {}
        res, status = self.referral_service.update_status(
            ref_id=ref_id,
            user=user,
            new_status=data.get("status"),
            decline_reason=data.get("decline_reason"),
        )
        return jsonify(res), status
