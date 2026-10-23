"""Validation policy for survivor-managed trusted contacts."""
import re

class ContactValidationError(ValueError):
    """The entire contact submission must be rejected"""

class ContactService:
    MAX_CONTACTS = 5
    MAX_NAME_LENGTH = 60

    @staticmethod
    def clean_contacts(items):
        """Validate every entry before returning any data for persistence"""
        if not isinstance(items, list):
            raise ContactValidationError("Contacts must be a list.")

        if len(items) > ContactService.MAX_CONTACTS:
            raise ContactValidationError("A maximum of five contacts is allowed.")

        cleaned = []
        seen_numbers = set()

        for item in items:
            if not isinstance(item, dict):
                raise ContactValidationError("Each contact must be an object.")

            name = item.get("name")
            phone = item.get("phone")

            if not isinstance(name, str):
                raise ContactValidationError("Contact names must be text.")

            name = name.strip()

            if (
                not name
                or len(name) > ContactService.MAX_NAME_LENGTH
                or any(not character.isprintable() for character in name)
            ):
                raise ContactValidationError("Contact names must containt 1-6- printable characters.")

            if not isinstance(phone, str):
                raise ContactValidationError("Phone numbers must be text.")

                # Bound input before processing; allow familiar display separators.
            if len(phone) > 40:
                raise ContactValidationError("Invalid South African phone number.")

            phone = re.sub(r"[ ()-]", "", phone.strip())

            if re.fullmatch(r"0[1-9][0-9]{8}", phone):
                phone = "+27" + phone[1:]
            elif not re.fullmatch(r"\+27[1-9][0-9]{8}", phone):
                raise ContactValidationError("Invalid South African phone number.")

            if phone in seen_numbers:
                raise ContactValidationError("Duplicate contact phone number.")

            seen_numbers.add(phone)
            cleaned.append((name, phone))

        return cleaned