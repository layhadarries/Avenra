"""Alert data access repository."""
import sqlite3
from typing import Optional, List
from datetime import datetime, timezone
from avenra.repositories.base import BaseRepository
from avenra.models.alert import Alert
import db


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertRepository(BaseRepository):
    """Encapsulates SQL operations on the alerts table."""

    @staticmethod
    def ensure_columns() -> None:
        """Stage 1 added two columns. CREATE TABLE IF NOT EXISTS won't add them to an
        old database file, so add them here if they're missing."""
        conn = db.connect()
        try:
            have = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
            for col in ("client_ts", "acknowledged_at"):
                if col not in have:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT")
                    print(f"Added missing column alerts.{col}")
            conn.commit()
        finally:
            conn.close()

    def get_by_id(self, alert_id: int) -> Optional[Alert]:
        row = self.conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return Alert.from_row(row)

    def get_by_client_id(self, client_id: str) -> Optional[Alert]:
        row = self.conn.execute("SELECT * FROM alerts WHERE client_id = ?", (client_id,)).fetchone()
        return Alert.from_row(row)

    def create(
        self,
        user_id: int,
        case_code: str,
        lat: Optional[float],
        lng: Optional[float],
        client_id: str,
        client_ts: Optional[str],
    ) -> Alert:
        cur = self.conn.execute(
            """INSERT INTO alerts (user_id, case_code, lat, lng, status, client_id, client_ts, created_at)
               VALUES (?, ?, ?, ?, 'new', ?, ?, ?)""",
            (user_id, case_code, lat, lng, client_id, client_ts, utc_now()),
        )
        row = self.conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return Alert.from_row(row)

    def get_recent(self, limit: int = 50) -> List[Alert]:
        rows = self.conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Alert.from_row(r) for r in rows]

    def get_for_case(self, case_code: str) -> List[Alert]:
        rows = self.conn.execute(
            "SELECT * FROM alerts WHERE case_code = ? ORDER BY created_at DESC, id DESC",
            (case_code,),
        ).fetchall()
        return [Alert.from_row(r) for r in rows]

    def acknowledge(self, alert_id: int, responder_name: str) -> tuple[Optional[Alert], bool]:
        """Atomically claim a 'new' alert. Returns (Alert, claimed_bool)."""
        cur = self.conn.execute(
            """UPDATE alerts SET status = 'acknowledged', acknowledged_by = ?, acknowledged_at = ?
               WHERE id = ? AND status = 'new'""",
            (responder_name, utc_now(), alert_id),
        )
        claimed = cur.rowcount == 1
        row = self.conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            return None, False
        return Alert.from_row(row), claimed

    def set_in_progress(self, alert_id: int, responder_name: str, now: str) -> None:
        self.conn.execute(
            """UPDATE alerts
               SET status = 'in_progress',
                   acknowledged_by = COALESCE(acknowledged_by, ?),
                   acknowledged_at = COALESCE(acknowledged_at, ?)
               WHERE id = ?""",
            (responder_name, now, alert_id),
        )

    def resolve(self, alert_id: int) -> None:
        self.conn.execute("UPDATE alerts SET status = 'resolved' WHERE id = ?", (alert_id,))
