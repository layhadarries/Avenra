"""Diary entry domain entity."""
from typing import Optional, Any


class DiaryEntry:
    """Represents a private evidence entry (note and/or photo) in the vault."""

    def __init__(
        self,
        id: int,
        user_id: int,
        client_id: str,
        note: Optional[str] = None,
        photo_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        shared: int = 0,
        created_at: Optional[str] = None,
    ):
        self.id = id
        self.user_id = user_id
        self.client_id = client_id
        self.note = note
        self.photo_path = photo_path
        self.file_hash = file_hash
        self.shared = bool(shared)
        self.created_at = created_at

    @classmethod
    def from_row(cls, row) -> Optional["DiaryEntry"]:
        if row is None:
            return None
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            client_id=row["client_id"],
            note=row["note"],
            photo_path=row["photo_path"],
            file_hash=row["file_hash"],
            shared=row["shared"],
            created_at=row["created_at"],
        )

    def stored_body(self) -> dict:
        """Metadata returned to the survivor device upon successful storage."""
        return {
            "id": self.id,
            "client_id": self.client_id,
            "stored": True,
            "file_hash": self.file_hash,
            "shared": self.shared,
            "has_photo": bool(self.photo_path),
            "created_at": self.created_at,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
