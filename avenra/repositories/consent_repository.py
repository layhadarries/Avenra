"""Consent data access repository."""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from avenra.repositories.base import BaseRepository
from avenra.models.consent import Consent
from avenra.config import Config


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ConsentRepository(BaseRepository):
    """Encapsulates SQL operations on the consents table."""

    def get_consents_map(self, user_id: int) -> Dict[str, dict]:
        """Return a dict of item -> consent dict representation for the survivor."""
        rows = self.conn.execute(
            "SELECT * FROM consents WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        by_item = {r["item"]: r for r in rows}
        result = {}
        for key, meta in Config.CONSENT_CATALOG.items():
            r = by_item.get(key)
            consent = Consent.from_row(key, meta, r)
            result[key] = consent.to_dict()
        return result

    def is_active(self, user_id: int, item: str) -> bool:
        cmap = self.get_consents_map(user_id)
        return cmap.get(item, {}).get("active", False)

    def update_consent(self, user_id: int, item: str, active: bool) -> dict:
        meta = Config.CONSENT_CATALOG[item]
        existing = self.conn.execute(
            "SELECT * FROM consents WHERE user_id = ? AND item = ? ORDER BY id DESC LIMIT 1",
            (user_id, item),
        ).fetchone()
        now = utc_now()
        if existing is None:
            self.conn.execute(
                "INSERT INTO consents (user_id, item, granted_to, granted_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, item, meta["granted_to"], now, None if active else now),
            )
        else:
            if active:
                self.conn.execute(
                    "UPDATE consents SET granted_at = ?, revoked_at = NULL WHERE id = ?",
                    (now, existing["id"]),
                )
            else:
                self.conn.execute(
                    "UPDATE consents SET revoked_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
        return self.get_consents_map(user_id)[item]
