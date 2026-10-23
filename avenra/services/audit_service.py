"""Audit logging and system transparency service."""
from typing import Optional, List, Dict, Any
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.audit import AuditEntry


class AuditService:
    """Manages audit logging and access reporting."""

    def __init__(self, audit_repo: Optional[AuditRepository] = None):
        self.audit_repo = audit_repo or AuditRepository()

    def log(
        self,
        actor: str,
        action: str,
        case_code: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.audit_repo.log(actor, action, case_code, detail)

    def list_for_survivor(self, case_code: str) -> List[Dict[str, Any]]:
        entries = self.audit_repo.list_entries(case_code=case_code, limit=30)
        return [e.serialize() for e in entries]

    def list_for_staff(self, limit: int = 100) -> List[Dict[str, Any]]:
        limit = min(200, max(10, limit))
        entries = self.audit_repo.list_entries(limit=limit)
        return [e.serialize() for e in entries]

    def get_health_counts(self) -> Dict[str, int]:
        return self.audit_repo.table_counts()
