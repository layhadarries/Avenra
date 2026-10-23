"""Alert business logic and notification dispatching service."""
import sqlite3
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone
from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.referral_repository import ReferralRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.models.alert import Alert
import sms


def utc_now() -> str:
    """UTC timestamp in the same format SQLite defaults use."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_coord(value: Any, limit: float) -> Optional[float]:
    """A latitude/longitude, or None. Bad location never blocks an alert."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) > limit:
        return None
    return round(f, 6)


def parse_client_ts(value: Any) -> Optional[str]:
    """The phone's clock when she pressed. Stored as UTC text, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertService:
    """Orchestrates emergency alert processing, idempotency, location privacy, and dispatch."""

    def __init__(
        self,
        alert_repo: Optional[AlertRepository] = None,
        consent_repo: Optional[ConsentRepository] = None,
        referral_repo: Optional[ReferralRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
    ):
        self.alert_repo = alert_repo or AlertRepository()
        self.consent_repo = consent_repo or ConsentRepository()
        self.referral_repo = referral_repo or ReferralRepository()
        self.audit_repo = audit_repo or AuditRepository()

    def create_alert(
        self,
        survivor: User,
        client_id: Optional[str],
        raw_lat: Any,
        raw_lng: Any,
        raw_client_ts: Any,
    ) -> Tuple[Dict[str, Any], int]:
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 64:
            return {"error": "client_id_required"}, 400
        client_id = client_id.strip()

        # Idempotency check: replay of known client_id returns identical response
        existing = self.alert_repo.get_by_client_id(client_id)
        if existing is not None:
            if existing.user_id != survivor.id:
                return {"error": "client_id_conflict"}, 409
            return existing.created_body(), 200

        # Location parsing & privacy consent verification
        lat = parse_coord(raw_lat, 90)
        lng = parse_coord(raw_lng, 180)
        location_allowed = self.consent_repo.is_active(survivor.id, "location_sharing")
        if lat is None or lng is None or not location_allowed:
            lat = lng = None

        client_ts = parse_client_ts(raw_client_ts)

        try:
            alert = self.alert_repo.create(
                user_id=survivor.id,
                case_code=survivor.case_code,
                lat=lat,
                lng=lng,
                client_id=client_id,
                client_ts=client_ts,
            )
        except sqlite3.IntegrityError:
            # Race condition handling
            self.alert_repo.conn.rollback()
            existing = self.alert_repo.get_by_client_id(client_id)
            if existing is None or existing.user_id != survivor.id:
                return {"error": "client_id_conflict"}, 409
            return existing.created_body(), 200

        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            "alert_created",
            survivor.case_code,
            f"alert {alert.id}; location {'yes' if lat is not None else 'no'}",
        )

        # Dispatch notifications to trusted contacts
        notified = sms.notify_contacts(
            self.alert_repo.conn,
            survivor,
            alert.id,
            lat=lat,
            lng=lng,
            client_ts=client_ts,
        )
        if notified:
            self.audit_repo.log(
                "system",
                "contact_dispatch_attempted",
                survivor.case_code,
                f"alert {alert.id}; attempted={len(notified)}; accepted={sum(bool(c['ok']) for c in notified)}",
            )

        body = alert.created_body()
        body["contacts_notified"] = 0
        body["contacts_accepted"] = sum(bool(c["ok"]) for c in notified)
        body["notification_mode"] = "provider" if any(c["ok"] for c in notified) else "unconfirmed"
        return body, 201

    def list_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        alerts = self.alert_repo.get_recent(limit)
        loc_cache = {}
        out = []
        for a in alerts:
            uid = a.user_id
            if uid not in loc_cache:
                loc_cache[uid] = self.consent_repo.is_active(uid, "location_sharing")
            out.append(a.serialize(location_allowed=loc_cache[uid]))
        return out

    def acknowledge_alert(self, alert_id: int, responder: User) -> Tuple[Dict[str, Any], int]:
        from avenra.repositories.case_access_repository import CaseAccessRepository
        from avenra.repositories.portal_repository import PortalRepository
        existing = self.alert_repo.get_by_id(alert_id)
        if existing is None or not CaseAccessRepository(self.alert_repo.conn).allows(responder.id, existing.user_id):
            return {"error": "not_found"}, 404
        alert, claimed = self.alert_repo.acknowledge(alert_id, responder.name)
        if alert is None:
            self.alert_repo.conn.rollback()
            return {"error": "not_found"}, 404

        if claimed:
            portal = PortalRepository(self.alert_repo.conn)
            workflow = portal.workflow(alert_id)
            portal.update_workflow(alert_id, workflow['assigned_to'] or responder.id, workflow['escalated_at'])
            portal.record(alert_id, responder.id, 'acknowledged')
            self.audit_repo.log(
                responder.name,
                "alert_acknowledged",
                alert.case_code,
                f"alert {alert_id}",
            )
        else:
            self.alert_repo.conn.rollback()

        body = {
            "id": alert.id,
            "status": alert.status,
            "acknowledged_by": alert.acknowledged_by,
            "acknowledged_at": alert.acknowledged_at,
        }
        if not claimed:
            body["already"] = True
        return body, 200

    def get_alert_status(self, alert_id: int, survivor: User) -> Tuple[Dict[str, Any], int]:
        alert = self.alert_repo.get_by_id(alert_id)
        if alert is None or alert.user_id != survivor.id:
            return {"error": "not_found"}, 404

        referral_info = self.referral_repo.get_latest_for_alert(alert_id)
        return {"status": alert.status, "referral": referral_info}, 200
