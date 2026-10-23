"""Contacts API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.repositories.contact_repository import ContactRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.security import device_user


class ContactsController:
    """Handles trusted contacts configuration for survivors."""

    def __init__(
        self,
        contact_repo: Optional[ContactRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
    ):
        self.contact_repo = contact_repo or ContactRepository()
        self.audit_repo = audit_repo or AuditRepository()

    def list_contacts(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        contacts = self.contact_repo.get_for_user(survivor.id)
        return jsonify({"contacts": contacts})

    def save_contacts(self):
        survivor = device_user()
        if survivor is None:
            return jsonify({"error": "bad_device_token"}), 401

        data = request.get_json(silent=True) or {}
        items = data.get("contacts")
        if not isinstance(items, list):
            return jsonify({"error": "contacts_list_required"}), 400

        cleaned = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:60]
            phone = str(item.get("phone") or "").strip()[:30]
            if name and phone:
                cleaned.append((name, phone))

        self.contact_repo.replace_contacts(survivor.id, cleaned)
        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            "contacts_updated",
            survivor.case_code,
            f"{len(cleaned)} contact(s) saved",
        )
        return self.list_contacts()
