"""Consent governance and privacy controls service."""
from typing import Optional, Tuple, Dict, Any, List
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.config import Config


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

        meta = Config.CONSENT_CATALOG[item]
        updated_item = self.consent_repo.update_consent(survivor.id, item, active)

        action_name = "consent_granted" if active else "consent_revoked"
        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            action_name,
            survivor.case_code,
            f"{item} ({meta['granted_to']})",
        )

        cmap = self.consent_repo.get_consents_map(survivor.id)
        return {"consent": updated_item, "consents": list(cmap.values())}, 200
