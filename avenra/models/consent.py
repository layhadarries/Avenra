"""Consent domain entity."""
from typing import Optional, Any


class Consent:
    """Represents a survivor's explicit consent grant or revocation."""

    def __init__(
        self,
        item: str,
        label: str,
        granted_to: str,
        active: bool = False,
        granted_at: Optional[str] = None,
        revoked_at: Optional[str] = None,
        id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        self.item = item
        self.label = label
        self.granted_to = granted_to
        self.active = active
        self.granted_at = granted_at
        self.revoked_at = revoked_at
        self.id = id
        self.user_id = user_id

    @classmethod
    def from_row(cls, item_key: str, meta: dict, row=None) -> "Consent":
        if row is None:
            return cls(
                item=item_key,
                label=meta["label"],
                granted_to=meta["granted_to"],
                active=False,
                granted_at=None,
                revoked_at=None,
            )
        active = row["revoked_at"] is None
        return cls(
            item=item_key,
            label=meta["label"],
            granted_to=row["granted_to"] if "granted_to" in row.keys() else meta["granted_to"],
            active=active,
            granted_at=row["granted_at"],
            revoked_at=row["revoked_at"],
            id=row["id"],
            user_id=row["user_id"],
        )

    def to_dict(self) -> dict:
        return {
            "item": self.item,
            "label": self.label,
            "granted_to": self.granted_to,
            "active": self.active,
            "granted_at": self.granted_at,
            "revoked_at": self.revoked_at,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
