"""Referral data access repository."""
from typing import Optional, List
from datetime import datetime, timezone
from avenra.repositories.base import BaseRepository
from avenra.models.referral import Referral


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReferralRepository(BaseRepository):
    """Encapsulates SQL operations on the referrals table."""

    def get_all(self, shelter_id: Optional[int] = None, staff_id: Optional[int] = None) -> List[Referral]:
        query = """SELECT r.*, a.case_code, s.name AS shelter_name
                   FROM referrals r
                   JOIN alerts a ON a.id = r.alert_id
                   JOIN shelters s ON s.id = r.shelter_id"""
        params = ()
        if shelter_id is not None:
            query += " WHERE r.shelter_id = ?"
            params = (shelter_id,)
        if staff_id is not None:
            query += " WHERE EXISTS (SELECT 1 FROM case_access c WHERE c.staff_id=? AND c.survivor_id=a.user_id)"
            params = (staff_id,)
        query += " AND EXISTS (SELECT 1 FROM consents co WHERE co.user_id=a.user_id AND co.item='shelter_referral_sharing' AND co.revoked_at IS NULL)" if params else " WHERE EXISTS (SELECT 1 FROM consents co WHERE co.user_id=a.user_id AND co.item='shelter_referral_sharing' AND co.revoked_at IS NULL)"
        query += " ORDER BY r.updated_at DESC, r.id DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [Referral.from_row(r) for r in rows]

    def get_by_id(self, ref_id: int) -> Optional[Referral]:
        row = self.conn.execute(
            """SELECT r.*, a.case_code, s.name AS shelter_name, s.beds_available
               FROM referrals r
               JOIN alerts a ON a.id = r.alert_id
               JOIN shelters s ON s.id = r.shelter_id
               WHERE r.id = ?""",
            (ref_id,),
        ).fetchone()
        return Referral.from_row(row)

    def get_latest_for_alert(self, alert_id: int) -> Optional[dict]:
        row = self.conn.execute(
            """SELECT r.id, r.status, r.decline_reason, r.updated_at, s.name AS shelter_name
               FROM referrals r
               JOIN shelters s ON s.id = r.shelter_id
               WHERE r.alert_id = ?
               ORDER BY r.id DESC LIMIT 1""",
            (alert_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "status": row["status"],
            "shelter_name": row["shelter_name"],
            "decline_reason": row["decline_reason"],
            "updated_at": row["updated_at"],
        }

    def get_for_case(self, case_code: str) -> List[Referral]:
        rows = self.conn.execute(
            """SELECT r.*, a.case_code, s.name AS shelter_name
               FROM referrals r
               JOIN alerts a ON a.id = r.alert_id
               JOIN shelters s ON s.id = r.shelter_id
               WHERE a.case_code = ?
               ORDER BY r.updated_at DESC, r.id DESC""",
            (case_code,),
        ).fetchall()
        return [Referral.from_row(r) for r in rows]

    def create(self, alert_id: int, shelter_id: int) -> Referral:
        now = utc_now()
        cur = self.conn.execute(
            """INSERT INTO referrals (alert_id, shelter_id, status, created_at, updated_at)
               VALUES (?, ?, 'sent', ?, ?)""",
            (alert_id, shelter_id, now, now),
        )
        return self.get_by_id(cur.lastrowid)

    def update_status(self, ref_id: int, new_status: str, decline_reason: Optional[str] = None) -> Optional[Referral]:
        now = utc_now()
        self.conn.execute(
            "UPDATE referrals SET status = ?, decline_reason = ?, updated_at = ? WHERE id = ?",
            (new_status, decline_reason if new_status == "declined" else None, now, ref_id),
        )
        return self.get_by_id(ref_id)
