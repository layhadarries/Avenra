"""Referral domain entity."""
from typing import Optional, Any


class Referral:
    """Represents a referral of a survivor/alert to a shelter."""

    def __init__(
        self,
        id: int,
        alert_id: int,
        shelter_id: int,
        status: str = "sent",
        decline_reason: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        case_code: Optional[str] = None,
        shelter_name: Optional[str] = None,
    ):
        self.id = id
        self.alert_id = alert_id
        self.shelter_id = shelter_id
        self.status = status
        self.decline_reason = decline_reason
        self.created_at = created_at
        self.updated_at = updated_at
        self.case_code = case_code
        self.shelter_name = shelter_name

    @classmethod
    def from_row(cls, row) -> Optional["Referral"]:
        if row is None:
            return None
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            id=row["id"],
            alert_id=row["alert_id"],
            shelter_id=row["shelter_id"],
            status=row["status"],
            decline_reason=row["decline_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            case_code=row["case_code"] if "case_code" in keys else None,
            shelter_name=row["shelter_name"] if "shelter_name" in keys else None,
        )

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "case_code": self.case_code,
            "shelter_id": self.shelter_id,
            "shelter_name": self.shelter_name,
            "status": self.status,
            "decline_reason": self.decline_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
