"""Consent governance and privacy controls service."""
from typing import Optional, Tuple, Dict, Any, List
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.config import Config
import sqlite3


class ConsentService:
    """Manages survivor consent state and privacy audit tracking."""

    def __init__(
        self,
        consent_repo: Optional[ConsentRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
    ):
        self.consent_repo = consent_repo or ConsentRepository()
        self.audit_repo = audit_repo or AuditRepository()

    def get_consents(self, user_id: int) -> List[Dict[str, Any]]:
        cmap = self.consent_repo.get_consents_map(user_id)
        return list(cmap.values())

    def update_consent(
            self,
            survivor: User,
            item: str,
            active: Any,
    ) -> Tuple[Dict[str, Any], int]:
        item = str(item or "").strip()

        if item not in Config.CONSENT_CATALOG:
            return {"error": "invalid_consent_item"}, 400

        if not isinstance(active, bool):
            return {"error": "active_must_be_boolean"}, 400

        conn = self.consent_repo.conn

        # Both writes must use the same database transaction.
        if self.audit_repo.conn is not conn:
            return {"error": "consent_update_unavailable"}, 503

        transaction_started = False

        try:
            # Serialize competing changes before checking saved state.
            conn.execute("BEGIN IMMEDIATE")
            transaction_started = True

            cmap = self.consent_repo.get_consents_map(survivor.id)
            current = cmap[item]

            if current["active"] == active:
                body = {
                    "consent": current,
                    "consents": list(cmap.values()),
                }
            else:
                meta = Config.CONSENT_CATALOG[item]

                updated_item = self.consent_repo.update_consent(
                    survivor.id,
                    item,
                    active,
                )

                action = (
                    "consent_granted" if active else "consent_revoked"
                )

                self.audit_repo.log(
                    f"survivor {survivor.case_code}",
                    action,
                    survivor.case_code,
                    f"{item} ({meta['granted_to']})",
                    commit=False,
                )

                cmap = self.consent_repo.get_consents_map(survivor.id)
                body = {
                    "consent": updated_item,
                    "consents": list(cmap.values()),
                }

            conn.commit()
            transaction_started = False
            return body, 200

        except sqlite3.Error:
            if transaction_started:
                conn.rollback()

            # Do not expose database/provider details to the caller.
            return {"error": "consent_update_unavailable"}, 503
