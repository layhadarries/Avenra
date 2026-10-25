"""Diary API controller."""
from typing import Optional
import sys
import io
from flask import request, jsonify, abort, url_for, send_file
from avenra.services.diary_service import DiaryService, LEGACY_MAX_PHOTO_BYTES
from avenra.security import device_user, current_user, require_role
from avenra.config import Config
from avenra.repositories.case_access_repository import CaseAccessRepository


def get_uploads_dir() -> str:
    app_mod = sys.modules.get("app")
    if app_mod and hasattr(app_mod, "UPLOADS_DIR"):
        return app_mod.UPLOADS_DIR
    return Config.UPLOADS_DIR


def serve_private_photo(service, uploads_dir, filename):
    storage = service._storage_for(uploads_dir)
    try:
        raw = storage.get_object(filename)
    except OSError:
        abort(404)
    # Serve the safely opened, bounded bytes, not a second path-based open after
    # verification. This also avoids public validators on local private media.
    response = send_file(io.BytesIO(raw), mimetype='image/jpeg',
                         download_name='evidence.jpg', conditional=False,
                         etag=False, max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


class DiaryController:
    """Handles evidence diary capture, listing, and photo retrieval."""

    ALLOWED_MULTIPART_FIELDS = frozenset({
        "client_id",
        "note",
        "shared",
        "captured_at",
        "created_at",
        "file_hash",
        "note_sha256",
        "photo_sha256",
        "entry_fingerprint",
        "contract_version",
    })

    def __init__(self, diary_service: Optional[DiaryService] = None):
        self.diary_service = diary_service or DiaryService()

    def _parse_multipart_upload(self):
        if set(request.form.keys()) - self.ALLOWED_MULTIPART_FIELDS:
            return None, ({"error": "invalid_multipart_fields"}, 400)
        if any(len(request.form.getlist(k)) != 1 for k in request.form.keys()):
            return None, ({"error": "invalid_multipart_fields"}, 400)
        if set(request.files.keys()) - {"photo"}:
            return None, ({"error": "invalid_multipart_fields"}, 400)
        if "photo" in request.files and len(request.files.getlist("photo")) != 1:
            return None, ({"error": "invalid_multipart_fields"}, 400)

        data = {}
        raw_version = request.form.get("contract_version", "2")
        if raw_version not in ("1", "2"):
            return None, ({"error": "invalid_contract_version"}, 400)
        data["contract_version"] = int(raw_version)

        for key in (
            "client_id",
            "note",
            "captured_at",
            "created_at",
            "file_hash",
            "note_sha256",
            "photo_sha256",
            "entry_fingerprint",
        ):
            if key in request.form:
                data[key] = request.form[key]

        if "shared" in request.form:
            raw_shared = request.form["shared"]
            if raw_shared == "true":
                data["shared"] = True
            elif raw_shared == "false":
                data["shared"] = False
            else:
                return None, ({"error": "shared_must_be_boolean"}, 400)

        if "photo" in request.files:
            photo_file = request.files["photo"]
            if photo_file.mimetype != "image/jpeg":
                return None, ({"error": "jpeg_media_type_required"}, 400)
            data["photo_bytes"] = photo_file.stream.read(
                LEGACY_MAX_PHOTO_BYTES + 1
            )

        return data, None

    def create_diary_entry(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        if request.mimetype == "multipart/form-data":
            data, err = self._parse_multipart_upload()
            if err is not None:
                return jsonify(err[0]), err[1]
        else:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "json_object_required"}), 400

        uploads_dir = get_uploads_dir()
        res, status = self.diary_service.create_entry(survivor, data, uploads_dir)
        return jsonify(res), status

    def list_diary_entries(self):
        survivor = device_user()
        if survivor is not None:
            # Survivor sees only vault receipts (no raw text)
            res, status = self.diary_service.list_for_survivor_paginated(
                survivor, request.args
            )
            return jsonify(res), status

        user = current_user()
        if user is None:
            return jsonify({"error": "sign_in_required"}), 401
        if user.role not in Config.ALERT_ROLES:
            return jsonify({"error": "forbidden"}), 403

        case_code = request.args.get('case_code', Config.DEMO_CASE_CODE)
        owner = self.diary_service.user_repo.get_survivor_by_case(case_code)
        if owner is None or not CaseAccessRepository().allows(user.id, owner.id):
            return jsonify({"error": "not_found"}), 404
        entries, consent_ok = self.diary_service.list_for_staff(case_code)
        if not consent_ok:
            return jsonify({"entries": [], "consent_active": False})

        if entries:
            self.diary_service.audit_repo.log(
                f"user:{user.id}",
                "diary_viewed",
                owner.case_code,
            )

        out = [
            {
                "id": e["id"],
                "note": e["note"],
                "has_photo": e["has_photo"],
                "photo_url": url_for("diary_photo", entry_id=e["id"]) if e["has_photo"] else None,
                "file_hash": e["file_hash"],
                "note_sha256": e["note_sha256"],
                "photo_sha256": e["photo_sha256"],
                "entry_fingerprint": e["entry_fingerprint"],
                "contract_version": e["contract_version"],
                "shared": e["shared"],
                "created_at": e["created_at"],
                "captured_at": e["captured_at"],
                "received_at": e["received_at"],
            }
            for e in entries
        ]
        return jsonify({"consent_active": True, "entries": out})

    def get_diary_entry(self, entry_id: int):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        res, status = self.diary_service.get_entry_for_survivor(
            survivor, entry_id
        )
        return jsonify(res), status

    def survivor_diary_photo(self, entry_id: int):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        uploads_dir = get_uploads_dir()
        filename = self.diary_service.get_survivor_photo_path(
            survivor, entry_id, uploads_dir
        )
        if not filename:
            abort(404)

        response = serve_private_photo(self.diary_service, uploads_dir, filename)
        if request.method == "GET" and response.status_code == 200:
            self.diary_service.audit_repo.log(
                f"survivor {survivor.case_code}",
                "survivor_diary_photo_viewed",
                survivor.case_code,
                detail=f"entry {entry_id}",
            )
        return response

    def update_diary_entry_sharing(self, entry_id: int):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        data = request.get_json(silent=True)
        res, status = self.diary_service.set_entry_shared(
            survivor, entry_id, data
        )
        return jsonify(res), status

    @require_role(*Config.ALERT_ROLES)
    def diary_photo(self, entry_id: int):
        user = current_user()
        entry = self.diary_service.diary_repo.get_by_id(entry_id)

        if entry is None or not CaseAccessRepository().allows(
                user.id, entry.user_id
        ):
            abort(404)

        owner = self.diary_service.user_repo.get_by_id(entry.user_id)
        if owner is None:
            abort(404)

        uploads_dir = get_uploads_dir()
        try:
            filename = self.diary_service.get_photo_path(
                entry_id, uploads_dir=uploads_dir
            )
        except PermissionError:
            abort(403)

        if not filename:
            abort(404)

        # Check that the file can actually be served before recording a view.
        response = serve_private_photo(self.diary_service, uploads_dir, filename)

        if request.method == "GET" and response.status_code == 200:
            self.diary_service.audit_repo.log(
                f"user:{user.id}",
                "diary_photo_viewed",
                owner.case_code,
                detail=f"entry {entry_id}",
            )

        return response
