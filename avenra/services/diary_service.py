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
import io
import warnings
from PIL import Image, UnidentifiedImageError

def valid_diary_jpeg(raw_bytes: bytes) -> bool:
    """Validate without modifying the bytes used for the receipt hash."""
    max_dimension = 8192
    max_pixels = 16_000_000

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(io.BytesIO(raw_bytes)) as image:
                if image.format != "JPEG":
                    return False

                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > max_dimension
                    or height > max_dimension
                    or width * height > max_pixels
                ):
                    return False

                image.verify()

            # verify() alone does not decode all image data.
            with Image.open(io.BytesIO(raw_bytes)) as image:
                image.load()

        return True
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        return False

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
        if not isinstance(data, dict):
            return {"error": "json_object_required"}, 400

        client_id = data.get("client_id")
        if (
                not isinstance(client_id, str)
                or not client_id.strip()
                or len(client_id) > 64
                or client_id != client_id.strip()
        ):
            return {"error": "client_id_required"}, 400

        note = data.get("note", "")
        if not isinstance(note, str):
            return {"error": "note_must_be_string"}, 400

        # Preserve existing whitespace normalisation for compatibility.
        note = note.strip()
        if len(note) > 4000:
            return {"error": "note_too_long"}, 400
        photo_data = data.get("photo_data")
        if not note and not photo_data:
            return {"error": "note_or_photo_required"}, 400

        photo_filename = None
        raw_bytes = b""

        if photo_data is not None:
            if (
                not isinstance(photo_data, str)
                or not photo_data.startswith("data:image/jpeg;base64,")
            ):
                return {"error": "jpeg_data_url_required"}, 400

            try:
                raw_bytes = base64.b64decode(
                    photo_data.split(",", 1)[1],
                    validate=True,
                )
            except (ValueError, TypeError):
                return {"error": "invalid_photo"}, 400

            if (
                not raw_bytes
                or len(raw_bytes) > 4 * 1024 * 1024
                or not valid_diary_jpeg(raw_bytes)
            ):
                return {"error": "invalid_photo"}, 400

        final_hash = hashlib.sha256(
            raw_bytes if raw_bytes else note.encode("utf-8")
        ).hexdigest()

        client_hash = data.get("file_hash")
        if client_hash is not None and client_hash != final_hash:
            return {"error": "hash_mismatch"}, 422

        if "shared" in data and not isinstance(data["shared"], bool):
            return {"error": "shared_must_be_boolean"}, 400

        shared = int(data.get("shared", False))

        # created_at remains a supported legacy input alias.
        captured_at = None
        for field in ("captured_at", "created_at"):
            if field not in data:
                continue

            parsed = parse_client_ts(data[field])
            if parsed is None:
                return {"error": "invalid_capture_time"}, 400

            if captured_at is not None and captured_at != parsed:
                return {"error": "conflicting_capture_times"}, 400

            captured_at = parsed

        def replay_response(existing):
            matches = (
                existing.user_id == survivor.id
                and existing.note == note
                and existing.file_hash == final_hash
                and bool(existing.photo_path) == bool(raw_bytes)
                and existing.shared == bool(shared)
            )

            if existing.received_at is not None:
                # New entries have explicit timestamp semantics.
                matches = matches and existing.captured_at == captured_at
            elif captured_at is not None:
                # Historical records retain their original legacy value.
                historical_time = (
                        existing.captured_at or existing.created_at
                )
                matches = matches and historical_time == captured_at

            if not matches:
                return {"error": "client_id_conflict"}, 409

            if existing.photo_path:
                # a user mustnt confirm a missing or changed photo
                filename = existing.photo_path
                if os.path.basename(filename) != filename:
                    return {"error": "diary_storage_unavailable"}, 503

                try:
                    with open(os.path.join(uploads_dir, filename), "rb") as fh:
                        stored_bytes = fh.read(4 * 1024 * 1024 + 1)
                except OSError:
                    return {"error": "diary_storage_unavaiable"}, 503

                if (
                    len(stored_bytes) > 4 * 1024 * 1024
                    or hashlib.sha256(stored_bytes).hexdigest()
                    != existing.file_hash
                ):
                    return {"error": "diary_storage_unavaiable"}, 503

            return existing.stored_body(), 200

        existing = self.diary_repo.get_by_client_id(client_id)
        if existing is not None:
            return replay_response(existing)

        conn = self.diary_repo.conn
        if self.audit_repo.conn is not conn or conn.in_transaction:
            return {"error": "diary_storage_unavailable"}, 503

        created_path = None

        try:
            # Serialise creation so concurrent retries see one committed entry.
            conn.execute("BEGIN IMMEDIATE")

            existing = self.diary_repo.get_by_client_id(client_id)
            if existing is not None:
                result = replay_response(existing)
                conn.rollback()
                return result

            if raw_bytes:
                photo_filename = f"diary_{uuid.uuid4().hex}.jpg"
                target_path = os.path.join(uploads_dir, photo_filename)

                with open(target_path, "xb") as fh:
                    # Only clean up files this request actually created.
                    created_path = target_path
                    fh.write(raw_bytes)
                    fh.flush()
                    os.fsync(fh.fileno())

                # Persist the directory entry on the Linux deployment target.
                if os.name == "posix":
                    directory_fd = os.open(uploads_dir, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)

            received_at = utc_now()
            # Preserve the old display field for existing consumers.
            created_at = captured_at or received_at

            entry = self.diary_repo.create(
                user_id=survivor.id,
                note=note,
                photo_path=photo_filename,
                file_hash=final_hash,
                shared=shared,
                client_id=client_id,
                created_at=created_at,
                captured_at=captured_at,
                received_at=received_at,
            )

            self.audit_repo.log(
                f"survivor {survivor.case_code}",
                "diary_entry_uploaded",
                survivor.case_code,
                f"entry {entry.id}; "
                f"photo={'yes' if photo_filename else 'no'}; "
                f"shared={'yes' if shared else 'no'}",
                commit=False,
            )

            conn.commit()

        except (OSError, sqlite3.Error):
            conn.rollback()
            if created_path is not None:
                try:
                    os.unlink(created_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    # No sensitive paths or provider errors in logs.
                    import logging
                    logging.getLogger(__name__).error(
                        "Diary orphan cleanup requires attention"
                    )

            return {"error": "diary_storage_unavailable"}, 503

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
                "captured_at": e.captured_at,
                "received_at": e.received_at,
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
