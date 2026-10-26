"""Offline case diary and forensic evidence vault service."""
import os
import stat
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
from avenra.models.diary import (
    canonical_note,
    compute_entry_fingerprint,
    compute_note_sha256,
)
from avenra.services.alert_service import parse_client_ts, utc_now
import io
import warnings
from PIL import Image, UnidentifiedImageError

LEGACY_MAX_PHOTO_BYTES = 4 * 1024 * 1024
V2_MAX_PHOTO_BYTES = 2 * 1024 * 1024
LEGACY_MAX_DIMENSION = 8192
LEGACY_MAX_PIXELS = 16_000_000
V2_MAX_DIMENSION = 1280
V2_MAX_PIXELS = 1280 * 1280


def has_prohibited_jpeg_metadata(raw_bytes: bytes, image: Image.Image) -> bool:
    """Detect EXIF, XMP, ICC, or comment metadata segments in a JPEG derivative."""
    if (
        image.info.get("exif")
        or image.info.get("xmp")
        or image.info.get("icc_profile")
        or image.info.get("comment")
    ):
        return True
    try:
        if len(image.getexif()) > 0:
            return True
    except Exception:
        return True
    return (
        b"Exif\x00\x00" in raw_bytes
        or b"http://ns.adobe.com/xap" in raw_bytes
    )


def valid_diary_jpeg(
    raw_bytes: bytes,
    max_dimension: int = LEGACY_MAX_DIMENSION,
    max_pixels: int = LEGACY_MAX_PIXELS,
    reject_metadata: bool = False,
) -> bool:
    """Validate without modifying the bytes used for the receipt hash."""
    if (
        not isinstance(raw_bytes, bytes)
        or len(raw_bytes) < 4
        or not raw_bytes.startswith(b"\xff\xd8")
        or not raw_bytes.endswith(b"\xff\xd9")
    ):
        return False

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

                if reject_metadata and has_prohibited_jpeg_metadata(raw_bytes, image):
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


from abc import ABC, abstractmethod
import logging


class DiaryStorageBackend(ABC):
    """Storage interface for private diary photo objects."""

    @staticmethod
    def is_safe_object_name(object_name: str) -> bool:
        return (
            isinstance(object_name, str)
            and bool(object_name)
            and os.path.basename(object_name) == object_name
            and "/" not in object_name
            and "\\" not in object_name
            and ".." not in object_name
        )

    @abstractmethod
    def put_object(
        self, object_name: str, data: bytes, expected_sha256: str
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_object(
        self, object_name: str, max_bytes: int = LEGACY_MAX_PHOTO_BYTES
    ) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def verify_object(
        self,
        object_name: str,
        expected_sha256: str,
        max_bytes: int = LEGACY_MAX_PHOTO_BYTES,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_object(self, object_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def reconcile_orphans(self, referenced_names: set) -> List[str]:
        raise NotImplementedError


class LocalDiaryStorage(DiaryStorageBackend):
    """Filesystem storage backend for local development and isolated tests."""

    def __init__(self, uploads_dir: str):
        self.uploads_dir = uploads_dir

    def _target_path(self, object_name: str) -> str:
        if not self.is_safe_object_name(object_name):
            raise OSError("Unsafe object name")
        return os.path.join(self.uploads_dir, object_name)

    def put_object(
        self, object_name: str, data: bytes, expected_sha256: str
    ) -> None:
        target_path = self._target_path(object_name)
        created = False
        try:
            with open(target_path, "xb") as fh:
                created = True
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())

            if os.name == "posix":
                directory_fd = os.open(self.uploads_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

            if not self.verify_object(
                object_name, expected_sha256, max_bytes=len(data)
            ):
                raise OSError("Stored object checksum verification failed")
        except Exception:
            if created:
                self.delete_object(object_name)
            raise

    def get_object(
        self, object_name: str, max_bytes: int = LEGACY_MAX_PHOTO_BYTES
    ) -> bytes:
        target_path = self._target_path(object_name)
        if os.path.islink(target_path):
            raise OSError('Unsafe object type')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(target_path, flags)
        with os.fdopen(descriptor, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise OSError('Unsafe object type')
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise OSError("Stored object exceeds maximum size")
        return data

    def verify_object(
        self,
        object_name: str,
        expected_sha256: str,
        max_bytes: int = LEGACY_MAX_PHOTO_BYTES,
    ) -> bool:
        if not self.is_safe_object_name(object_name) or not expected_sha256:
            return False
        try:
            stored_bytes = self.get_object(object_name, max_bytes=max_bytes)
        except OSError:
            return False
        return hashlib.sha256(stored_bytes).hexdigest() == expected_sha256

    def delete_object(self, object_name: str) -> None:
        if not self.is_safe_object_name(object_name):
            return
        target_path = os.path.join(self.uploads_dir, object_name)
        try:
            os.unlink(target_path)
        except FileNotFoundError:
            pass
        except OSError:
            quarantine_dir = os.path.join(self.uploads_dir, ".quarantine")
            try:
                os.makedirs(quarantine_dir, mode=0o700, exist_ok=True)
                os.replace(
                    target_path, os.path.join(quarantine_dir, object_name)
                )
            except OSError:
                pass
            logging.getLogger(__name__).error(
                "Diary orphan cleanup requires attention"
            )

    def reconcile_orphans(self, referenced_names: set) -> List[str]:
        reconciled = []
        if not os.path.isdir(self.uploads_dir):
            return reconciled
        quarantine_dir = os.path.join(self.uploads_dir, ".quarantine")
        for name in sorted(os.listdir(self.uploads_dir)):
            if not (name.startswith("diary_") and name.endswith(".jpg")):
                continue
            if name in referenced_names:
                continue
            if not self.is_safe_object_name(name):
                continue
            src = os.path.join(self.uploads_dir, name)
            if not os.path.isfile(src):
                continue
            os.makedirs(quarantine_dir, mode=0o700, exist_ok=True)
            os.replace(src, os.path.join(quarantine_dir, name))
            reconciled.append(name)
        return reconciled


class PrivateObjectDiaryStorage(DiaryStorageBackend):
    """Private object-store adapter with mandatory checksum verification."""

    def __init__(self, client: Any, bucket: str):
        if not bucket or not isinstance(bucket, str):
            raise ValueError("Private bucket name is required")
        self.client = client
        self.bucket = bucket
        self.quarantined: List[str] = []

    def put_object(
        self, object_name: str, data: bytes, expected_sha256: str
    ) -> None:
        if not self.is_safe_object_name(object_name):
            raise OSError("Unsafe object name")
        created = False
        try:
            self.client.put_object(
                bucket=self.bucket,
                key=object_name,
                body=data,
                content_type="image/jpeg",
                sha256=expected_sha256,
            )
            created = True
            if not self.verify_object(
                object_name, expected_sha256, max_bytes=len(data)
            ):
                raise OSError("Object store checksum verification failed")
        except Exception as exc:
            if created:
                self.delete_object(object_name)
            raise OSError("Object store write failed") from exc

    def get_object(
        self, object_name: str, max_bytes: int = LEGACY_MAX_PHOTO_BYTES
    ) -> bytes:
        if not self.is_safe_object_name(object_name):
            raise OSError("Unsafe object name")
        try:
            data = self.client.get_object(
                bucket=self.bucket, key=object_name, max_bytes=max_bytes + 1
            )
        except Exception as exc:
            raise OSError("Object store read failed") from exc
        if not isinstance(data, bytes) or len(data) > max_bytes:
            raise OSError("Object store returned invalid payload")
        return data

    def verify_object(
        self,
        object_name: str,
        expected_sha256: str,
        max_bytes: int = LEGACY_MAX_PHOTO_BYTES,
    ) -> bool:
        if not self.is_safe_object_name(object_name) or not expected_sha256:
            return False
        try:
            stored = self.get_object(object_name, max_bytes=max_bytes)
        except OSError:
            return False
        return hashlib.sha256(stored).hexdigest() == expected_sha256

    def delete_object(self, object_name: str) -> None:
        if not self.is_safe_object_name(object_name):
            return
        try:
            self.client.delete_object(bucket=self.bucket, key=object_name)
        except Exception:
            if object_name not in self.quarantined:
                self.quarantined.append(object_name)
            logging.getLogger(__name__).error(
                "Diary orphan cleanup requires attention"
            )

    def reconcile_orphans(self, referenced_names: set) -> List[str]:
        reconciled = []
        keys = list(self.client.list_objects(bucket=self.bucket, prefix="diary_"))
        for key in sorted(set(keys) | set(self.quarantined)):
            if key in referenced_names or not self.is_safe_object_name(key):
                continue
            self.client.delete_object(bucket=self.bucket, key=key)
            if key in self.quarantined:
                self.quarantined.remove(key)
            reconciled.append(key)
        return reconciled


class DiaryService:
    """Manages incident notes, verified hashes, and access-controlled photos."""

    FORBIDDEN_AUTHORITY_KEYS = frozenset({
        "user_id",
        "case_code",
        "owner_id",
        "survivor_id",
    })

    def __init__(
        self,
        diary_repo: Optional[DiaryRepository] = None,
        consent_repo: Optional[ConsentRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
        user_repo: Optional[UserRepository] = None,
        storage: Optional[DiaryStorageBackend] = None,
    ):
        self.diary_repo = diary_repo or DiaryRepository()
        self.consent_repo = consent_repo or ConsentRepository()
        self.audit_repo = audit_repo or AuditRepository()
        self.user_repo = user_repo or UserRepository()
        self.storage = storage

    def _storage_for(self, uploads_dir: str) -> DiaryStorageBackend:
        if self.storage is not None:
            return self.storage
        if os.environ.get('DATABASE_URL') or os.environ.get('DIARY_STORAGE_BACKEND') == 'database':
            from avenra.services.database_diary_storage import DatabaseDiaryStorage
            return DatabaseDiaryStorage(self.diary_repo.conn)
        return LocalDiaryStorage(uploads_dir)

    def reconcile_orphans(self, uploads_dir: str) -> List[str]:
        conn = self.diary_repo.conn
        if conn.in_transaction:
            raise RuntimeError("Reconciliation requires its own transaction")
        # Share the upload writer lock: never quarantine an in-flight object.
        conn.execute("BEGIN IMMEDIATE")
        try:
            referenced = self.diary_repo.list_all_photo_paths()
            result = self._storage_for(uploads_dir).reconcile_orphans(referenced)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    def create_entry(
        self,
        survivor: User,
        data: Dict[str, Any],
        uploads_dir: str,
    ) -> Tuple[Dict[str, Any], int]:
        if not isinstance(data, dict):
            return {"error": "json_object_required"}, 400

        if any(key in data for key in self.FORBIDDEN_AUTHORITY_KEYS):
            return {"error": "invalid_authority_selector"}, 400

        contract_version = data.get("contract_version", 1)
        if type(contract_version) is not int or contract_version not in (1, 2):
            return {"error": "invalid_contract_version"}, 400

        client_id = data.get("client_id")
        if (
            not isinstance(client_id, str)
            or not client_id.strip()
            or len(client_id) > 64
            or client_id != client_id.strip()
        ):
            return {"error": "client_id_required"}, 400

        from avenra.repositories.retention_repository import RetentionRepository
        if RetentionRepository(self.diary_repo.conn).was_deleted(survivor.id,'diary',client_id):
            return {'error':'entry_removed_by_retention'},410

        note = data.get("note", "")
        if not isinstance(note, str):
            return {"error": "note_must_be_string"}, 400

        note = canonical_note(note)
        if len(note) > 4000:
            return {"error": "note_too_long"}, 400

        photo_data = data.get("photo_data")
        photo_bytes = data.get("photo_bytes")
        if photo_data is not None and photo_bytes is not None:
            return {"error": "conflicting_photo_inputs"}, 400

        if not note and photo_data is None and photo_bytes is None:
            return {"error": "note_or_photo_required"}, 400

        max_photo_bytes = (
            V2_MAX_PHOTO_BYTES
            if contract_version == 2
            else LEGACY_MAX_PHOTO_BYTES
        )
        max_dimension = (
            V2_MAX_DIMENSION
            if contract_version == 2
            else LEGACY_MAX_DIMENSION
        )
        max_pixels = (
            V2_MAX_PIXELS
            if contract_version == 2
            else LEGACY_MAX_PIXELS
        )

        photo_filename = None
        raw_bytes = b""

        if photo_bytes is not None:
            if not isinstance(photo_bytes, bytes) or not photo_bytes:
                return {"error": "invalid_photo"}, 400
            if len(photo_bytes) > max_photo_bytes:
                return {"error": "photo_too_large"}, 413
            raw_bytes = photo_bytes
        elif photo_data is not None:
            if (
                not isinstance(photo_data, str)
                or not photo_data.startswith("data:image/jpeg;base64,")
            ):
                return {"error": "jpeg_data_url_required"}, 400

            encoded_part = photo_data.split(",", 1)[1]
            max_b64_len = ((max_photo_bytes + 2) // 3) * 4
            if len(encoded_part) > max_b64_len:
                if contract_version == 2:
                    return {"error": "photo_too_large"}, 413
                return {"error": "invalid_photo"}, 400

            try:
                raw_bytes = base64.b64decode(encoded_part, validate=True)
            except (ValueError, TypeError):
                return {"error": "invalid_photo"}, 400

            if not raw_bytes:
                return {"error": "invalid_photo"}, 400

            if len(raw_bytes) > max_photo_bytes:
                if contract_version == 2:
                    return {"error": "photo_too_large"}, 413
                return {"error": "invalid_photo"}, 400

        if raw_bytes:
            if contract_version == 2 and valid_diary_jpeg(
                raw_bytes,
                max_dimension=max_dimension,
                max_pixels=max_pixels,
                reject_metadata=False,
            ) and not valid_diary_jpeg(
                raw_bytes,
                max_dimension=max_dimension,
                max_pixels=max_pixels,
                reject_metadata=True,
            ):
                return {"error": "prohibited_photo_metadata"}, 400

            if not valid_diary_jpeg(
                raw_bytes,
                max_dimension=max_dimension,
                max_pixels=max_pixels,
                reject_metadata=(contract_version == 2),
            ):
                return {"error": "invalid_photo"}, 400

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

        note_sha256 = compute_note_sha256(note)
        photo_sha256 = (
            hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None
        )
        final_hash = (
            photo_sha256 if photo_sha256 is not None else note_sha256
        )
        entry_fingerprint = compute_entry_fingerprint(
            contract_version,
            note_sha256,
            photo_sha256,
            captured_at,
            bool(shared),
        )

        client_hash = data.get("file_hash")
        if client_hash is not None and (
            not isinstance(client_hash, str) or client_hash != final_hash
        ):
            return {"error": "hash_mismatch"}, 422

        client_note_hash = data.get("note_sha256")
        if client_note_hash is not None and (
            not isinstance(client_note_hash, str)
            or client_note_hash != note_sha256
        ):
            return {"error": "hash_mismatch"}, 422

        client_photo_hash = data.get("photo_sha256")
        if client_photo_hash is not None and (
            photo_sha256 is None
            or not isinstance(client_photo_hash, str)
            or client_photo_hash != photo_sha256
        ):
            return {"error": "hash_mismatch"}, 422

        client_fingerprint = data.get("entry_fingerprint")
        if client_fingerprint is not None and (
            not isinstance(client_fingerprint, str)
            or client_fingerprint != entry_fingerprint
        ):
            return {"error": "hash_mismatch"}, 422

        storage = self._storage_for(uploads_dir)

        def replay_response(existing):
            matches = (
                existing.user_id == survivor.id
                and canonical_note(existing.note) == note
                and existing.note_sha256 == note_sha256
                and existing.photo_sha256 == photo_sha256
                and existing.file_hash == final_hash
                and bool(existing.photo_path) == bool(raw_bytes)
                and (existing.entry_fingerprint == entry_fingerprint
                     if existing.received_at is not None
                     else existing.shared == bool(shared))
                and existing.contract_version == contract_version
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
                if not storage.verify_object(
                    existing.photo_path,
                    existing.file_hash,
                    max_bytes=LEGACY_MAX_PHOTO_BYTES,
                ):
                    return {"error": "diary_storage_unavailable"}, 503

            return existing.stored_body(), 200

        existing = self.diary_repo.get_by_client_id(client_id)
        if existing is not None:
            return replay_response(existing)

        conn = self.diary_repo.conn
        if self.audit_repo.conn is not conn or conn.in_transaction:
            return {"error": "diary_storage_unavailable"}, 503

        created_object = None

        try:
            # Serialise creation so concurrent retries see one committed entry.
            conn.execute("BEGIN IMMEDIATE")

            if RetentionRepository(conn).was_deleted(survivor.id,'diary',client_id):
                conn.rollback()
                return {'error':'entry_removed_by_retention'},410

            existing = self.diary_repo.get_by_client_id(client_id)
            if existing is not None:
                result = replay_response(existing)
                conn.rollback()
                return result

            if raw_bytes:
                photo_filename = f"diary_{uuid.uuid4().hex}.jpg"
                storage.put_object(photo_filename, raw_bytes, photo_sha256)
                created_object = photo_filename

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
                note_sha256=note_sha256,
                photo_sha256=photo_sha256,
                entry_fingerprint=entry_fingerprint,
                contract_version=contract_version,
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

        except sqlite3.IntegrityError:
            conn.rollback()
            if created_object is not None:
                storage.delete_object(created_object)
            existing = self.diary_repo.get_by_client_id(client_id)
            if existing is not None:
                return replay_response(existing)
            return {"error": "diary_storage_unavailable"}, 503

        except (OSError, sqlite3.Error):
            conn.rollback()
            if created_object is not None:
                storage.delete_object(created_object)

            return {"error": "diary_storage_unavailable"}, 503

        return entry.stored_body(), 201

    CURSOR_SALT = "avenra-survivor-diary-list-v1"
    CURSOR_MAX_AGE = 900

    def _cursor_serializer(self):
        from flask import current_app
        from itsdangerous import URLSafeTimedSerializer
        return URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"],
            salt=self.CURSOR_SALT,
        )

    def list_for_survivor(self, survivor_id: int) -> List[Dict[str, Any]]:
        entries = self.diary_repo.list_for_survivor(survivor_id)
        return [e.stored_body() for e in entries]

    def list_for_survivor_paginated(
        self, survivor: User, args=None
    ) -> Tuple[Dict[str, Any], int]:
        if args is None:
            return {
                "entries": self.list_for_survivor(survivor.id),
                "next_cursor": None,
            }, 200

        if set(args) - {"limit", "cursor"}:
            return {"error": "invalid_diary_parameters"}, 400
        if any(len(args.getlist(key)) != 1 for key in args):
            return {"error": "invalid_diary_parameters"}, 400

        raw_limit = args.get("limit", "30")
        if (
            not isinstance(raw_limit, str)
            or not 1 <= len(raw_limit) <= 2
            or not raw_limit.isascii()
            or not raw_limit.isdigit()
        ):
            return {"error": "invalid_diary_limit"}, 400

        limit = int(raw_limit)
        if not 1 <= limit <= 50:
            return {"error": "invalid_diary_limit"}, 400

        before = None
        if "cursor" in args:
            from itsdangerous import BadData
            token = args["cursor"]
            if not token or len(token) > 2048:
                return {"error": "invalid_diary_cursor"}, 400
            try:
                cursor = self._cursor_serializer().loads(
                    token, max_age=self.CURSOR_MAX_AGE
                )
            except BadData:
                return {"error": "invalid_diary_cursor"}, 400

            if (
                not isinstance(cursor, dict)
                or set(cursor) != {"survivor_id", "created_at", "id"}
                or type(cursor["survivor_id"]) is not int
                or cursor["survivor_id"] != survivor.id
                or not isinstance(cursor["created_at"], str)
                or not 1 <= len(cursor["created_at"]) <= 64
                or type(cursor["id"]) is not int
                or cursor["id"] < 1
            ):
                return {"error": "invalid_diary_cursor"}, 400

            before = (cursor["created_at"], cursor["id"])

        rows = self.diary_repo.get_page_for_survivor(
            survivor.id, limit + 1, before=before
        )
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = visible[-1]
            next_cursor = self._cursor_serializer().dumps({
                "survivor_id": survivor.id,
                "created_at": last.created_at,
                "id": last.id,
            })

        return {
            "entries": [e.stored_body() for e in visible],
            "next_cursor": next_cursor,
        }, 200

    def get_entry_for_survivor(
        self, survivor: User, entry_id: int
    ) -> Tuple[Dict[str, Any], int]:
        entry = self.diary_repo.get_by_id(entry_id)
        if entry is None or entry.user_id != survivor.id:
            return {"error": "not_found"}, 404

        detail = entry.stored_body()
        detail["note"] = entry.note or ""
        detail["photo_url"] = (
            f"/api/diary/{entry.id}/photo" if entry.photo_path else None
        )
        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            "survivor_diary_entry_viewed",
            survivor.case_code,
            detail=f"entry {entry.id}",
        )
        return {"entry": detail}, 200

    def get_survivor_photo_path(
        self, survivor: User, entry_id: int, uploads_dir: str
    ) -> Optional[str]:
        entry = self.diary_repo.get_by_id(entry_id)
        if (
            entry is None
            or entry.user_id != survivor.id
            or not entry.photo_path
        ):
            return None
        storage = self._storage_for(uploads_dir)
        if not storage.verify_object(
            entry.photo_path,
            entry.file_hash,
            max_bytes=LEGACY_MAX_PHOTO_BYTES,
        ):
            return None
        return entry.photo_path

    def set_entry_shared(
        self, survivor: User, entry_id: int, data: Any
    ) -> Tuple[Dict[str, Any], int]:
        if (
            not isinstance(data, dict)
            or set(data.keys()) != {"shared"}
            or not isinstance(data.get("shared"), bool)
        ):
            return {"error": "shared_must_be_boolean"}, 400

        shared = data["shared"]
        conn = self.diary_repo.conn
        if self.audit_repo.conn is not conn or conn.in_transaction:
            return {"error": "diary_storage_unavailable"}, 503

        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = self.diary_repo.get_by_id(entry_id)
            if existing is None or existing.user_id != survivor.id:
                conn.rollback()
                return {"error": "not_found"}, 404

            if existing.shared == shared:
                conn.rollback()
                return {"entry": existing.stored_body(),
                        "global_diary_consent_active": self.consent_repo.is_active(
                            survivor.id, "diary_sharing")}, 200

            updated = self.diary_repo.update_shared(
                entry_id, survivor.id, int(shared)
            )
            if updated is None:
                conn.rollback()
                return {"error": "not_found"}, 404

            self.audit_repo.log(
                f"survivor {survivor.case_code}",
                "diary_entry_shared" if shared else "diary_entry_unshared",
                survivor.case_code,
                f"entry {entry_id}; shared={'yes' if shared else 'no'}",
                commit=False,
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            return {"error": "diary_storage_unavailable"}, 503

        return {
            "entry": updated.stored_body(),
            "global_diary_consent_active": self.consent_repo.is_active(
                survivor.id, "diary_sharing"
            ),
        }, 200

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
                "note_sha256": e.note_sha256,
                "photo_sha256": e.photo_sha256,
                "entry_fingerprint": e.entry_fingerprint,
                "contract_version": e.contract_version,
                "shared": e.shared,
                "created_at": e.created_at,
                "captured_at": e.captured_at,
                "received_at": e.received_at,
            }
            for e in entries
        ]
        return out, True

    def get_photo_path(
        self, entry_id: int, uploads_dir: Optional[str] = None
    ) -> Optional[str]:
        entry = self.diary_repo.get_by_id(entry_id)
        if entry is None or not entry.photo_path or not entry.shared:
            return None
        if not self.consent_repo.is_active(entry.user_id, "diary_sharing"):
            raise PermissionError("Consent revoked")
        if uploads_dir is not None:
            storage = self._storage_for(uploads_dir)
            if not storage.verify_object(
                entry.photo_path,
                entry.file_hash,
                max_bytes=LEGACY_MAX_PHOTO_BYTES,
            ):
                return None
        return entry.photo_path
