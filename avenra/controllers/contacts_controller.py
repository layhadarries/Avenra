"""Contacts API controller."""
from typing import Optional
from flask import request, jsonify
from avenra.repositories.contact_repository import ContactRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.security import device_user
from avenra.services.contact_service import ContactValidationError, ContactService


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

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({"error": "contacts_object_required"}), 400

        if "contacts" not in data:
            return jsonify({"error": "contacts_list_required"}), 400

        try:
            cleaned = ContactService.clean_contacts(data["contacts"])
        except ContactValidationError as error:
            return jsonify({
                "error": "invalid_contacts",
                "message": str(error),
            }), 400

        # No database changes happen until every contact passes validation.
        self.contact_repo.replace_contacts(survivor.id, cleaned)

        self.audit_repo.log(
            f"survivor {survivor.case_code}",
            "contacts_updated",
            survivor.case_code,
            f"{len(cleaned)} contact(s) saved",
        )

        return self.list_contacts()
