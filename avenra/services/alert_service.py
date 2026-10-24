"""Alert business logic and notification dispatching service."""
import sqlite3
import os
import math
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone
from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.referral_repository import ReferralRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.models.alert import Alert
import sms
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository


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
    """Unknown unless an explicit timezone accompanies device time."""
    return parse_location_recorded_at(value)


def parse_location_accuracy(value: Any) -> Optional[float]:
    """Accept finite, non-negative JSON numbers in metres; never block an alert."""
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def parse_location_recorded_at(value: Any) -> Optional[str]:
    """Normalise an explicit device fix time; never infer its timezone or age."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        captured = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if captured.tzinfo is None:
            return None
        return captured.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


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
        raw_location_accuracy: Any = None,
        raw_location_recorded_at: Any = None,
    ) -> Tuple[Dict[str, Any], int]:
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 64:
            return {"error": "client_id_required"}, 400
        client_id = client_id.strip()
        conn = self.alert_repo.conn

        try:
            with conn:
                # Serialize creation/retry checks and keep all writes atomic.
                conn.execute("BEGIN IMMEDIATE")
                existing = self.alert_repo.get_by_client_id(client_id)
                if existing is not None:
                    if existing.user_id != survivor.id:
                        return {"error": "client_id_conflict"}, 409
                    return existing.created_body(), 200

                lat = parse_coord(raw_lat, 90)
                lng = parse_coord(raw_lng, 180)
                allowed = self.consent_repo.is_active(survivor.id, "location_sharing")
                if lat is None or lng is None or not allowed:
                    lat = lng = None

                accuracy = parse_location_accuracy(raw_location_accuracy) if lat is not None else None
                recorded_at = parse_location_recorded_at(raw_location_recorded_at) if lat is not None else None
                client_ts = parse_client_ts(raw_client_ts)

                alert = self.alert_repo.create(
                    user_id=survivor.id,
                    case_code=survivor.case_code,
                    lat=lat,
                    lng=lng,
                    client_id=client_id,
                    client_ts=client_ts,
                    location_accuracy=accuracy,
                    location_recorded_at=recorded_at,
                )
                queued = NotificationOutboxRepository(conn).enqueue_for_alert(alert.id)
                self.audit_repo.log(
                    f"survivor {survivor.case_code}",
                    "alert_created",
                    survivor.case_code,
                    f"alert {alert.id}; location {'yes' if lat is not None else 'no'}; queued={queued}",
                    commit=False,
                )
        except sqlite3.Error:
            return {"error": "alert_storage_unavailable"}, 503

        body = alert.created_body()
        body["contacts_queued"] = queued
        body["contacts_accepted"] = 0
        body["contacts_notified"] = 0
        body["notification_mode"] = "queued" if queued else ("no_subscribed_contacts" if os.environ.get("AVENRA_WEBPUSH_ENABLED")=="1" else "no_contacts")
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
        from avenra.services.notification_status_service import NotificationStatusService
        return {
            "status": alert.status,
            "referral": self.referral_repo.get_latest_for_alert(alert_id),
            "notification": NotificationStatusService(self.alert_repo.conn).for_alert(alert_id),
        }, 200
