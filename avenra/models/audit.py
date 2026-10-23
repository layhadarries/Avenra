"""Audit log entry domain entity."""
from typing import Optional, Any


class AuditEntry:
    """Represents an immutable record in the security audit log."""

    def __init__(
        self,
        id: int,
        ts: str,
        actor: str,
        action: str,
        case_code: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        self.id = id
        self.ts = ts
        self.actor = actor
        self.action = action
        self.case_code = case_code
        self.detail = detail

    @classmethod
    def from_row(cls, row) -> Optional["AuditEntry"]:
        if row is None:
            return None
        return cls(
            id=row["id"],
            ts=row["ts"],
            actor=row["actor"],
            action=row["action"],
            case_code=row["case_code"],
            detail=row["detail"],
        )

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "actor": self.actor,
            "action": self.action,
            "case_code": self.case_code,
            "detail": self.detail,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
