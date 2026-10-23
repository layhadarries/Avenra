"""Diary API controller."""
from typing import Optional
import sys
from flask import request, jsonify, abort, url_for, send_from_directory
from avenra.services.diary_service import DiaryService
from avenra.security import device_user, current_user, require_role
from avenra.config import Config
from avenra.repositories.case_access_repository import CaseAccessRepository


def get_uploads_dir() -> str:
    app_mod = sys.modules.get("app")
    if app_mod and hasattr(app_mod, "UPLOADS_DIR"):
        return app_mod.UPLOADS_DIR
    return Config.UPLOADS_DIR


class DiaryController:
    """Handles evidence diary capture, listing, and photo retrieval."""

    def __init__(self, diary_service: Optional[DiaryService] = None):
        self.diary_service = diary_service or DiaryService()

    def create_diary_entry(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        data = request.get_json(silent=True) or {}
        uploads_dir = get_uploads_dir()
        res, status = self.diary_service.create_entry(survivor, data, uploads_dir)
        return jsonify(res), status

    def list_diary_entries(self):
        survivor = device_user()
        if survivor is not None:
            # Survivor sees only vault receipts (no raw text)
            return jsonify({"entries": self.diary_service.list_for_survivor(survivor.id)})

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
        self.diary_service.audit_repo.log(f'user:{user.id}', 'diary_viewed', case_code)
        if not consent_ok:
            return jsonify({"entries": [], "consent_active": False})

        out = [
            {
                "id": e["id"],
                "note": e["note"],
                "has_photo": e["has_photo"],
                "photo_url": url_for("diary_photo", entry_id=e["id"]) if e["has_photo"] else None,
                "file_hash": e["file_hash"],
                "created_at": e["created_at"],
            }
            for e in entries
        ]
        return jsonify({"consent_active": True, "entries": out})

    @require_role(*Config.ALERT_ROLES)
    def diary_photo(self, entry_id: int):
        entry = self.diary_service.diary_repo.get_by_id(entry_id)
        if entry is None or not CaseAccessRepository().allows(current_user().id, entry.user_id):
            abort(404)
        try:
            filename = self.diary_service.get_photo_path(entry_id)
        except PermissionError:
            abort(403)

        if not filename:
            abort(404)
        self.diary_service.audit_repo.log(f'user:{current_user().id}', 'diary_photo_viewed', detail=f'entry {entry_id}')
        return send_from_directory(get_uploads_dir(), filename)
