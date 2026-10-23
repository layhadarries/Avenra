"""Offline case diary and forensic evidence vault service."""
import os
import base64
import uuid
import hashlib
import sqlite3
from typing import Optional, Tuple, Dict, Any, List
from avenra.repositories.diary_repository import DiaryRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.repositories.user_repository import UserRepository
from avenra.models.user import User
from avenra.services.alert_service import parse_client_ts, utc_now


class DiaryService:
    """Manages incident notes, verified hashes, and access-controlled photos."""

    def __init__(
        self,
        diary_repo: Optional[DiaryRepository] = None,
        consent_repo: Optional[ConsentRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
        user_repo: Optional[UserRepository] = None,
    ):
        self.diary_repo = diary_repo or DiaryRepository()
        self.consent_repo = consent_repo or ConsentRepository()
        self.audit_repo = audit_repo or AuditRepository()
        self.user_repo = user_repo or UserRepository()

    def create_entry(
        self,
        survivor: User,
        data: Dict[str, Any],
        uploads_dir: str,
    ) -> Tuple[Dict[str, Any], int]:
        client_id = str(data.get("client_id") or "").strip()
        if not client_id or len(client_id) > 64:
            return {"error": "client_id_required"}, 400

        # Idempotency check
        existing = self.diary_repo.get_by_client_id(client_id)
        if existing is not None:
            if existing.user_id != survivor.id:
                return {"error": "client_id_conflict"}, 409
            return existing.stored_body(), 200

        note = str(data.get("note") or "").strip()
        if len(note) > 4000:
            return {"error": "note_too_long"}, 400

        photo_data = data.get("photo_data")
        if not note and not photo_data:
            return {"error": "note_or_photo_required"}, 400

        photo_filename = None
        raw_bytes = b""
        if photo_data:
            if not isinstance(photo_data, str) or not photo_data.startswith("data:image/jpeg;base64,"):
                return {"error": "jpeg_data_url_required"}, 400
            try:
                raw_bytes = base64.b64decode(photo_data.split(",", 1)[1], validate=True)
            except (ValueError, TypeError):
                return {"error": "invalid_photo"}, 400

            if not raw_bytes or len(raw_bytes) > 4 * 1024 * 1024 or not raw_bytes.startswith(b"\xff\xd8"):
                return {"error": "invalid_photo"}, 400

        final_hash = hashlib.sha256(raw_bytes if raw_bytes else note.encode("utf-8")).hexdigest()
        client_hash = data.get("file_hash")
        if client_hash is not None and client_hash != final_hash:
            return {"error": "hash_mismatch"}, 422

        if "shared" in data and not isinstance(data["shared"], bool):
            return {"error": "shared_must_be_boolean"}, 400
        shared = int(data.get("shared", False))

        if raw_bytes:
            photo_filename = f"diary_{uuid.uuid4().hex}.jpg"
            target_path = os.path.join(uploads_dir, photo_filename)
            with open(target_path, "xb") as fh:
                fh.write(raw_bytes)
                fh.flush()
                os.fsync(fh.fileno())

        created_at = parse_client_ts(data.get("created_at")) or utc_now()

        try:
            entry = self.diary_repo.create(
                user_id=survivor.id,
                note=note,
                photo_path=photo_filename,
                file_hash=final_hash,
                shared=shared,
                client_id=client_id,
                created_at=created_at,
            )
        except sqlite3.IntegrityError:
            self.diary_repo.conn.rollback()
            if photo_filename:
                try:
                    os.unlink(os.path.join(uploads_dir, photo_filename))
                except OSError:
                    pass
            existing = self.diary_repo.get_by_client_id(client_id)
            if existing is None or existing.user_id != survivor.id:
                return {"error": "client_id_conflict"}, 409
            return existing.stored_body(), 200

        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            "diary_entry_uploaded",
            survivor.case_code,
            f"entry {entry.id}; sha256={final_hash[:12]}…; photo={'yes' if photo_filename else 'no'}; shared={'yes' if shared else 'no'}",
        )
        return entry.stored_body(), 201

    def list_for_survivor(self, survivor_id: int) -> List[Dict[str, Any]]:
        entries = self.diary_repo.list_for_survivor(survivor_id)
        return [e.stored_body() for e in entries]

    def list_for_staff(self, case_code: str) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
        """Returns (entries_list, consent_active). If consent revoked, entries is []."""
        surv = self.user_repo.get_survivor_by_case(case_code)
        if surv is None:
            return [], False

        consent_ok = self.consent_repo.is_active(surv.id, "diary_sharing")
        if not consent_ok:
            return [], False

        entries = self.diary_repo.list_shared_for_case(surv.id)
        out = [
            {
                "id": e.id,
                "note": e.note,
                "has_photo": bool(e.photo_path),
                "photo_path": e.photo_path,
                "file_hash": e.file_hash,
                "created_at": e.created_at,
            }
            for e in entries
        ]
        return out, True

    def get_photo_path(self, entry_id: int) -> Optional[str]:
        entry = self.diary_repo.get_by_id(entry_id)
        if entry is None or not entry.photo_path or not entry.shared:
            return None
        if not self.consent_repo.is_active(entry.user_id, "diary_sharing"):
            raise PermissionError("Consent revoked")
        return entry.photo_path
