"""Shelter directory API contracts using an isolated test database."""
import unittest

import test_avenra


class ShelterDirectoryAPITests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def assert_directory_contract(self, response):
        self.assertEqual(response.status_code, 200)

        entries = response.json["shelters"]
        self.assertGreater(len(entries), 0)

        for entry in entries:
            with self.subTest(shelter_id=entry["id"]):
                self.assertEqual(
                    entry["availability"],
                    "contact_to_confirm",
                )
                for field in (
                    "beds_total",
                    "beds_available",
                    "accepting",
                ):
                    self.assertNotIn(field, entry)

    def test_signed_out_request_is_rejected(self):
        response = self.client.get("/api/shelters")
        self.assertEqual(response.status_code, 401)

    def test_invalid_device_credentials_are_rejected(self):
        response = self.client.get(
            "/api/shelters",
            headers={"X-Device-Token": "invalid-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_survivor_receives_directory_without_capacity_claims(self):
        response = self.client.get(
            "/api/shelters",
            headers=self.survivor_headers,
        )
        self.assert_directory_contract(response)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_responder_receives_directory_without_capacity_claims(self):
        self._login_staff("responder")

        response = self.client.get("/api/shelters")

        self.assert_directory_contract(response)


if __name__ == "__main__":
    unittest.main()