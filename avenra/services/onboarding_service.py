"""Save optional profile details and contact additions as one transaction."""
import sqlite3

from avenra.repositories.audit_repository import AuditRepository
from avenra.repositories.contact_repository import ContactRepository
from avenra.repositories.user_repository import UserRepository
from avenra.services.contact_service import ContactService, ContactValidationError


class OnboardingService:
    def __init__(self, conn):
        self.conn = conn
        self.contacts = ContactRepository(conn)
        self.users = UserRepository(conn)

    def details(self, survivor):
        return {
            'name': '' if survivor.name == 'Private account' else survivor.name,
            'contacts': [
                {'id': row['id'], 'name': row['name'], 'phone_masked': '••••' + row['phone'][-4:]}
                for row in self.contacts.get_for_user(survivor.id)
            ],
        }

    def save(self, survivor, data):
        if not isinstance(data, dict) or set(data) - {'name', 'contacts'}:
            return {'error': 'invalid_setup_fields'}, 400
        name = data.get('name')
        if name is not None:
            if not isinstance(name, str):
                return {'error': 'invalid_name'}, 400
            name = name.strip()
            if not name or len(name) > 60 or any(not character.isprintable() for character in name):
                return {'error': 'invalid_name', 'message': 'Use 1–60 printable characters for your name.'}, 400
        try:
            additions = ContactService.clean_contacts(data.get('contacts', []))
            with self.conn:
                self.conn.execute('BEGIN IMMEDIATE')
                existing = self.contacts.get_for_user(survivor.id)
                combined = [{'name': row['name'], 'phone': row['phone']} for row in existing]
                pending = []
                for contact_name, phone in additions:
                    # A repeated request after a lost receipt must not duplicate contacts.
                    if any(item['name'] == contact_name and item['phone'] == phone for item in combined):
                        continue
                    if any(item['name'] == contact_name or item['phone'] == phone for item in combined):
                        raise ContactValidationError('Use a distinct name and number for each new contact.')
                    combined.append({'name': contact_name, 'phone': phone})
                    pending.append((contact_name, phone))
                # Existing recipients are untouched, including legacy demo numbers.
                if len(combined) > ContactService.MAX_CONTACTS:
                    raise ContactValidationError('A maximum of five contacts is allowed.')
                if name is not None:
                    self.users.update_survivor_name(survivor.id, name)
                for contact_name, phone in pending:
                    self.contacts.add_contact(survivor.id, contact_name, phone)
                AuditRepository(self.conn).log(
                    f'survivor {survivor.case_code}', 'onboarding_saved', survivor.case_code,
                    f'Profile updated: {name is not None}; contacts added: {len(pending)}', commit=False,
                )
        except ContactValidationError as error:
            return {'error': 'invalid_contacts', 'message': str(error)}, 400
        except sqlite3.Error:
            return {'error': 'setup_storage_unavailable'}, 503
        return {'saved': True}, 200
