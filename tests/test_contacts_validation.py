"""Trusted-contact validation: reject invalid submissions without truncation."""
import unittest

from avenra.services.contact_service import (
    ContactService,
    ContactValidationError,
)


class ContactValidationTests(unittest.TestCase):
    def test_normalises_south_african_phone_formats(self):
        result = ContactService.clean_contacts([
            {"name": "  Contact One  ", "phone": "082 123 4567"},
            {"name": "Contact Two", "phone": "+27 83 234 5678"},
        ])

        self.assertEqual(result, [
            ("Contact One", "+27821234567"),
            ("Contact Two", "+27832345678"),
        ])

    def test_empty_list_explicitly_clears_contacts(self):
        self.assertEqual(ContactService.clean_contacts([]), [])

    def test_rejects_more_than_five_instead_of_truncating(self):
        contacts = [
            {"name": f"Contact {i}", "phone": f"+2782123456{i}"}
            for i in range(6)
        ]

        with self.assertRaises(ContactValidationError):
            ContactService.clean_contacts(contacts)

    def test_rejects_duplicate_numbers_after_normalisation(self):
        with self.assertRaises(ContactValidationError):
            ContactService.clean_contacts([
                {"name": "One", "phone": "082 123 4567"},
                {"name": "Two", "phone": "+27821234567"},
            ])

    def test_rejects_invalid_structure_instead_of_skipping(self):
        for value in (
            None,
            {},
            "contacts",
            [None],
            ["invalid"],
            [{"name": "Valid", "phone": "+27821234567"}, None],
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContactValidationError):
                    ContactService.clean_contacts(value)

    def test_rejects_invalid_names_instead_of_converting_or_truncating(self):
        for name in (None, "", "   ", 123, {}, "A" * 61):
            with self.subTest(name=name):
                with self.assertRaises(ContactValidationError):
                    ContactService.clean_contacts([
                        {"name": name, "phone": "+27821234567"},
                    ])

    def test_rejects_invalid_phone_numbers(self):
        for phone in (
            None,
            "",
            821234567,
            {},
            "123",
            "082123456",
            "+278212345678",
            "+2782ABC4567",
            "https://example.test",
        ):
            with self.subTest(phone=phone):
                with self.assertRaises(ContactValidationError):
                    ContactService.clean_contacts([
                        {"name": "Contact", "phone": phone},
                    ])


if __name__ == "__main__":
    unittest.main()