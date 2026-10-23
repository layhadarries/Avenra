"""Trusted-contact API tests using an isolated temporary database."""
import unittest

import test_avenra


class ContactsAPITests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def saved_contacts(self):
        response = self.client.get(
            "/api/contacts",
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["contacts"]

    def post_contacts(self, contacts):
        return self.client.post(
            "/api/contacts",
            json={"contacts": contacts},
            headers=self.survivor_headers,
        )

    def test_valid_submission_saves_normalised_contacts(self):
        response = self.post_contacts([
            {"name": "  Contact One  ", "phone": "082 123 4567"},
        ])

        self.assertEqual(response.status_code, 200)
        saved = self.saved_contacts()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "Contact One")
        self.assertEqual(saved[0]["phone"], "+27821234567")

    def test_invalid_submission_preserves_existing_contacts(self):
        initial = self.post_contacts([
            {"name": "Existing Contact", "phone": "+27821234567"},
        ])
        self.assertEqual(initial.status_code, 200)
        before = self.saved_contacts()

        invalid_submissions = [
            None,
            {},
            [None],
            [{"name": "Bad Number", "phone": "123"}],
            [{"name": 123, "phone": "+27821234567"}],
            [{"name": "A" * 61, "phone": "+27821234567"}],
            [
                {"name": "Valid", "phone": "+27832345678"},
                {"name": "Invalid", "phone": "bad"},
            ],
            [
                {"name": "One", "phone": "0821234567"},
                {"name": "Duplicate", "phone": "+27821234567"},
            ],
            [
                {"name": f"Contact {i}", "phone": f"+2782123456{i}"}
                for i in range(6)
            ],
        ]

        for contacts in invalid_submissions:
            with self.subTest(contacts=contacts):
                response = self.post_contacts(contacts)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.saved_contacts(), before)

    def test_missing_contacts_field_preserves_existing_contacts(self):
        before = self.saved_contacts()

        response = self.client.post(
            "/api/contacts",
            json={},
            headers=self.survivor_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved_contacts(), before)

    def test_explicit_empty_list_clears_contacts(self):
        response = self.post_contacts([])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_contacts(), [])

    def test_missing_device_credentials_cannot_read_or_write(self):
        before = self.saved_contacts()

        self.assertEqual(
            self.client.get("/api/contacts").status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/contacts", json={"contacts": []}
            ).status_code,
            401,
        )
        self.assertEqual(self.saved_contacts(), before)

    def test_invalid_device_credentials_cannot_read_or_write(self):
        before = self.saved_contacts()
        headers = {"X-Device-Token": "invalid-test-token"}

        self.assertEqual(
            self.client.get(
                "/api/contacts", headers=headers
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/contacts",
                json={"contacts": []},
                headers=headers,
            ).status_code,
            401,
        )
        self.assertEqual(self.saved_contacts(), before)

    def test_staff_session_cannot_replace_device_credentials(self):
        before = self.saved_contacts()
        self._login_staff("responder")

        self.assertEqual(
            self.client.get("/api/contacts").status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/contacts", json={"contacts": []}
            ).status_code,
            401,
        )
        self.assertEqual(self.saved_contacts(), before)


if __name__ == "__main__":
    unittest.main()
