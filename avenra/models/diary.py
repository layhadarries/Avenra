"""Diary entry domain entity."""
import hashlib
import json
from typing import Optional, Any


def canonical_note(note: Optional[str]) -> str:
    if not note:
        return ""
    return note.replace("\r\n", "\n").replace("\r", "\n").strip()


def compute_note_sha256(note: Optional[str]) -> str:
    return hashlib.sha256(canonical_note(note).encode("utf-8")).hexdigest()


def compute_entry_fingerprint(
    contract_version: int,
    note_sha256: str,
    photo_sha256: Optional[str],
    captured_at: Optional[str],
    shared: bool,
) -> str:
    payload = json.dumps(
        {
            "captured_at": captured_at,
            "note_sha256": note_sha256,
            "photo_sha256": photo_sha256,
            "shared": bool(shared),
            "v": int(contract_version),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class DiaryEntry:
    """Represents a private diary entry with separate capture and receipt times."""

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
        captured_at: Optional[str] = None,
        received_at: Optional[str] = None,
        note_sha256: Optional[str] = None,
        photo_sha256: Optional[str] = None,
        entry_fingerprint: Optional[str] = None,
        contract_version: int = 1,
    ):
        self.id = id
        self.user_id = user_id
        self.client_id = client_id
        self.note = note
        self.photo_path = photo_path
        self.shared = bool(shared)
        self.created_at = created_at
        self.captured_at = captured_at
        self.received_at = received_at
        self.contract_version = int(contract_version or 1)
        self.note_sha256 = note_sha256 or compute_note_sha256(note)
        self.photo_sha256 = (
            photo_sha256
            if photo_sha256 is not None
            else (file_hash if photo_path else None)
        )
        self.file_hash = (
            file_hash
            if file_hash is not None
            else (self.photo_sha256 or self.note_sha256)
        )
        effective_captured = (
            captured_at
            if received_at is not None
            else (captured_at or created_at)
        )
        self.entry_fingerprint = entry_fingerprint or compute_entry_fingerprint(
            self.contract_version,
            self.note_sha256,
            self.photo_sha256,
            effective_captured,
            self.shared,
        )

    @classmethod
    def from_row(cls, row) -> Optional["DiaryEntry"]:
        if row is None:
            return None

        keys = set(row.keys())
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            client_id=row["client_id"],
            note=row["note"],
            photo_path=row["photo_path"],
            file_hash=row["file_hash"],
            shared=row["shared"],
            created_at=row["created_at"],
            captured_at=row["captured_at"] if "captured_at" in keys else None,
            received_at=row["received_at"] if "received_at" in keys else None,
            note_sha256=row["note_sha256"] if "note_sha256" in keys else None,
            photo_sha256=row["photo_sha256"] if "photo_sha256" in keys else None,
            entry_fingerprint=(
                row["entry_fingerprint"] if "entry_fingerprint" in keys else None
            ),
            contract_version=(
                row["contract_version"]
                if "contract_version" in keys and row["contract_version"] is not None
                else 1
            ),
        )

    def stored_body(self) -> dict:
        """Return storage receipt metadata without private note or photo content."""
        return {
            "id": self.id,
            "client_id": self.client_id,
            "stored": True,
            "contract_version": self.contract_version,
            "entry_fingerprint": self.entry_fingerprint,
            "photo_sha256": self.photo_sha256,
            "note_sha256": self.note_sha256,
            "file_hash": self.file_hash,
            "shared": self.shared,
            "has_photo": bool(self.photo_path),
            "created_at": self.created_at,
            "captured_at": self.captured_at,
            "received_at": self.received_at,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)