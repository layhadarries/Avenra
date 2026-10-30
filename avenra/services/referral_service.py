"""Referral placement and workflow service."""
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone
from avenra.repositories.referral_repository import ReferralRepository
from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.repositories.case_access_repository import CaseAccessRepository
from avenra.repositories.portal_repository import PortalRepository
from avenra.models.identifiers import valid_identifier


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReferralService:
    """Manages shelter referrals, approval workflows, and capacity placement."""

    ALLOWED_TRANSITIONS = {
        "sent": {"accepted", "declined"},
        "accepted": {"placed", "declined"},
        "declined": set(),
        "placed": set(),
    }

    def __init__(
        self,
        referral_repo: Optional[ReferralRepository] = None,
        alert_repo: Optional[AlertRepository] = None,
        shelter_repo: Optional[ShelterRepository] = None,
        consent_repo: Optional[ConsentRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
    ):
        self.referral_repo = referral_repo or ReferralRepository()
        self.alert_repo = alert_repo or AlertRepository()
        self.shelter_repo = shelter_repo or ShelterRepository()
        self.consent_repo = consent_repo or ConsentRepository()
        self.audit_repo = audit_repo or AuditRepository()

    def list_referrals(self, user: User) -> List[Dict[str, Any]]:
        if user.role == "shelter":
            if user.shelter_id is None:
                return []
            referrals = self.referral_repo.get_all(shelter_id=user.shelter_id)
        elif user.role == "admin":
            # Mirrors CaseAccessRepository.allows(): create/update already let
            # administrators work across cases, so the list must not narrow
            # them to explicit grants. Consent remains the hard gate.
            referrals = self.referral_repo.get_all()
        else:
            referrals = self.referral_repo.get_all(staff_id=user.id)
        return [r.serialize() for r in referrals]

    def create_referral(
        self,
        alert_id: int,
        shelter_id: int,
        user: User,
    ) -> Tuple[Dict[str, Any], int]:
        if not valid_identifier(alert_id) or not valid_identifier(shelter_id):
            return {'error': 'alert_id_and_shelter_id_required'}, 400
        conn = self.referral_repo.conn
        committed = False
        try:
            conn.execute('BEGIN IMMEDIATE')
            alert = self.alert_repo.get_by_id(alert_id)
            shelter = self.shelter_repo.get_by_id(shelter_id)
            if alert is None or shelter is None:
                return {"error": "not_found"}, 404

            if not CaseAccessRepository(conn).allows(user.id, alert.user_id):
                return {"error": "not_found"}, 404
            if not self.consent_repo.is_active(alert.user_id, "shelter_referral_sharing"):
                return {"error": "referral_consent_required"}, 403
            if alert.status == 'resolved':
                return {"error": "alert_resolved"}, 409
            existing = conn.execute(
                "SELECT id FROM referrals WHERE alert_id=? AND status IN ('sent','accepted','placed')", (alert_id,)).fetchone()
            if existing:
                referral = self.referral_repo.get_by_id(existing['id'])
                if referral.shelter_id == shelter_id:
                    return {"referral": referral.serialize(), "already": True}, 200
                return {"error": "active_referral"}, 409

            now = utc_now()
            referral = self.referral_repo.create(alert_id, shelter_id)

            if alert.status in ("new", "acknowledged"):
                self.alert_repo.set_in_progress(alert_id, user.name, now)

            portal = PortalRepository(conn)
            state = portal.workflow(alert_id)
            portal.update_workflow(alert_id, state['assigned_to'] or user.id, state['escalated_at'])
            portal.record(alert_id, user.id, 'referral_sent', f'Referral #{referral.id}')
            self.audit_repo.log(
                f'user:{user.id}',
                "referral_sent",
                alert.case_code,
                f"referral {referral.id} -> {shelter.name} (alert {alert_id})",
                commit=False,
            )
            conn.commit()
            committed = True
            return {"referral": referral.serialize()}, 201
        finally:
            if not committed:
                conn.rollback()

    def update_status(
        self,
        ref_id: int,
        user: User,
        new_status: str,
        decline_reason: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], int]:
        new_status = str(new_status or "").strip().lower()
        if new_status not in ("accepted", "declined", "placed"):
            return {"error": "invalid_status"}, 400

        conn = self.referral_repo.conn
        committed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = self.referral_repo.get_by_id(ref_id)
            if existing is None:
                return {"error": "not_found"}, 404

            if user.role == "shelter" and user.shelter_id != existing.shelter_id:
                return {"error": "forbidden"}, 403

            alert = self.alert_repo.get_by_id(existing.alert_id)
            if user.role != 'shelter' and not CaseAccessRepository(conn).allows(user.id, alert.user_id):
                return {"error": "not_found"}, 404
            if not self.consent_repo.is_active(alert.user_id, 'shelter_referral_sharing'):
                return {"error": "referral_consent_required"}, 403
            decline_clean = None
            if new_status == "declined":
                if not isinstance(decline_reason, str):
                    return {"error": "invalid_decline_reason"}, 400

                decline_clean = decline_reason.strip()
                if not 1 <= len(decline_clean) <= 200:
                    return {"error": "invalid_decline_reason"}, 400
            if new_status == existing.status:
                return {"referral": existing.serialize(), "already": True}, 200
            if alert.status == 'resolved':
                return {"error": "alert_resolved"}, 409

            allowed = self.ALLOWED_TRANSITIONS.get(existing.status, set())
            if new_status != existing.status and new_status not in allowed:
                return {"error": "invalid_transition"}, 409

            shelter = self.shelter_repo.get_by_id(existing.shelter_id)
            if shelter is None:
                return {"error": "not_found"}, 404

            updated = self.referral_repo.update_status(ref_id, new_status, decline_clean)

            if new_status == "placed" and existing.status != "placed":
                self.alert_repo.resolve(existing.alert_id)

            detail = f"referral {ref_id} ({existing.shelter_name}) -> {new_status}"
            if new_status == "declined" and decline_clean:
                detail += f" ({decline_clean})"

            portal = PortalRepository(conn)
            state = portal.workflow(existing.alert_id)
            portal.update_workflow(existing.alert_id, state['assigned_to'], state['escalated_at'])
            portal.record(existing.alert_id, user.id, f'referral_{new_status}', f'Referral #{ref_id}')
            self.audit_repo.log(f'user:{user.id}', f"referral_{new_status}", existing.case_code, f'referral {ref_id}', commit=False)
            conn.commit()
            committed = True
            return {"referral": updated.serialize()}, 200
        finally:
            if not committed:
                conn.rollback()
