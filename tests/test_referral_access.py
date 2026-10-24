"""Shelter referral scope and consent regression tests."""
import unittest
from contextlib import closing

import test_avenra
import test_referral_requests


class ReferralAccessTests(unittest.TestCase):
    tearDown = test_referral_requests.ReferralRequestTests.tearDown
    _login_staff = test_referral_requests.ReferralRequestTests._login_staff
    _staff_post = test_referral_requests.ReferralRequestTests._staff_post
    request_referral = (
        test_referral_requests.ReferralRequestTests.request_referral
    )

    def setUp(self):
        test_referral_requests.ReferralRequestTests.setUp(self)

        with closing(test_avenra.db.connect()) as conn:
            shelter_id = conn.execute(
                "SELECT shelter_id FROM users WHERE role = 'shelter' LIMIT 1"
            ).fetchone()["shelter_id"]
            other_id = conn.execute(
                "SELECT id FROM shelters WHERE id != ? ORDER BY id LIMIT 1",
                (shelter_id,),
            ).fetchone()["id"]

        self.shelter_id = shelter_id
        own = self.request_referral()
        self.assertEqual(own.status_code, 201)
        self.own_referral_id = own.json["referral"]["id"]

        alert = self.client.post(
            "/api/alerts",
            headers=self.survivor_headers,
            json={
                "client_id": "other-shelter-referral",
                "lat": -33.9249,
                "lng": 18.4241,
            },
        )
        self.assertEqual(alert.status_code, 201)

        other = self._staff_post(
            "/api/referrals",
            json={
                "alert_id": alert.json["id"],
                "shelter_id": other_id,
            },
        )
        self.assertEqual(other.status_code, 201)
        self.other_referral_id = other.json["referral"]["id"]

    def test_shelter_sees_only_own_referrals_without_incident_location(self):
        self._login_staff("shelter")
        response = self.client.get("/api/referrals")
        self.assertEqual(response.status_code, 200)

        entries = response.json["referrals"]
        self.assertEqual(
            [entry["id"] for entry in entries],
            [self.own_referral_id],
        )
        for entry in entries:
            for field in (
                "lat", "lng", "location_accuracy", "location_recorded_at"
            ):
                self.assertNotIn(field, entry)

        page = self.client.get("/referrals")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn(
            f'data-referral-id="{self.own_referral_id}"', html
        )
        self.assertNotIn(
            f'data-referral-id="{self.other_referral_id}"', html
        )

    def test_shelter_cannot_update_another_shelters_referral(self):
        self._login_staff("shelter")
        response = self._staff_post(
            f"/api/referrals/{self.other_referral_id}/status",
            json={"status": "accepted"},
        )
        self.assertEqual(response.status_code, 403)

        with closing(test_avenra.db.connect()) as conn:
            status = conn.execute(
                "SELECT status FROM referrals WHERE id = ?",
                (self.other_referral_id,),
            ).fetchone()["status"]

        self.assertEqual(status, "sent")

    def test_revoked_consent_hides_referrals_from_api_and_page(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE consents
                    SET revoked_at = '2026-10-23T00:00:00Z'
                    WHERE item = 'shelter_referral_sharing'
                    """
                )

        for role in ("responder", "shelter"):
            with self.subTest(role=role):
                self._login_staff(role)

                response = self.client.get("/api/referrals")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["referrals"], [])

                page = self.client.get("/referrals")
                self.assertEqual(page.status_code, 200)
                self.assertNotIn(
                    "data-referral-id=",
                    page.get_data(as_text=True),
                )


if __name__ == "__main__":
    unittest.main()