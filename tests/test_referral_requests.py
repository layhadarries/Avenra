"""Referral requests must not rely on unverified capacity."""
import unittest
from contextlib import closing

import test_avenra


class ReferralRequestTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff
    _staff_post = test_avenra.avenraStagesTestCase._staff_post

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)

        response = self.client.post(
            "/api/alerts",
            json={"client_id": "referral-request-test"},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.json["id"]

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                row = conn.execute(
                    "SELECT id FROM shelters ORDER BY id LIMIT 1"
                ).fetchone()
                self.shelter_id = row["id"]

                # Deliberately stale, unverified capacity information.
                conn.execute(
                    """
                    UPDATE shelters
                    SET beds_total = 20, beds_available = 0, accepting = 0
                    WHERE id = ?
                    """,
                    (self.shelter_id,),
                )

        self._login_staff("responder")

    def request_referral(self):
        return self._staff_post(
            "/api/referrals",
            json={
                "alert_id": self.alert_id,
                "shelter_id": self.shelter_id,
            },
        )

    def test_stale_capacity_does_not_block_request(self):
        response = self.request_referral()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["referral"]["status"], "sent")

    def test_request_does_not_change_capacity_or_confirm_placement(self):
        response = self.request_referral()
        self.assertEqual(response.status_code, 201)

        with closing(test_avenra.db.connect()) as conn:
            shelter = conn.execute(
                """
                SELECT beds_total, beds_available, accepting
                FROM shelters WHERE id = ?
                """,
                (self.shelter_id,),
            ).fetchone()
            alert = conn.execute(
                "SELECT status FROM alerts WHERE id = ?",
                (self.alert_id,),
            ).fetchone()

        self.assertEqual(shelter["beds_total"], 20)
        self.assertEqual(shelter["beds_available"], 0)
        self.assertEqual(shelter["accepting"], 0)
        self.assertNotEqual(alert["status"], "resolved")

    def test_referral_consent_is_still_required(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE consents
                    SET revoked_at = '2026-10-23T00:00:00Z'
                    WHERE item = 'shelter_referral_sharing'
                    AND user_id = (
                        SELECT user_id FROM alerts WHERE id = ?
                    )
                    """,
                    (self.alert_id,),
                )

        response = self.request_referral()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json["error"], "referral_consent_required"
        )

        with closing(test_avenra.db.connect()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM referrals WHERE alert_id = ?",
                (self.alert_id,),
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_confirmed_placement_does_not_require_stored_capacity(self):
        created = self.request_referral()
        self.assertEqual(created.status_code, 201)
        referral_id = created.json["referral"]["id"]

        accepted = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={"status": "accepted"},
        )
        self.assertEqual(accepted.status_code, 200)

        placed = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={"status": "placed"},
        )
        self.assertEqual(placed.status_code, 200)
        self.assertEqual(placed.json["referral"]["status"], "placed")

        with closing(test_avenra.db.connect()) as conn:
            alert = conn.execute(
                "SELECT status FROM alerts WHERE id = ?",
                (self.alert_id,),
            ).fetchone()

        self.assertEqual(alert["status"], "resolved")

    def test_placement_does_not_adjust_unverified_bed_counts(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE shelters
                    SET beds_available = 8, accepting = 1
                    WHERE id = ?
                    """,
                    (self.shelter_id,),
                )

        created = self.request_referral()
        self.assertEqual(created.status_code, 201)
        referral_id = created.json["referral"]["id"]

        accepted = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={"status": "accepted"},
        )
        self.assertEqual(accepted.status_code, 200)

        placed = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={"status": "placed"},
        )
        self.assertEqual(placed.status_code, 200)

        with closing(test_avenra.db.connect()) as conn:
            shelter = conn.execute(
                """
                SELECT beds_available FROM shelters
                WHERE id = ?
                """,
                (self.shelter_id,),
            ).fetchone()

        self.assertEqual(shelter["beds_available"], 8)

if __name__ == "__main__":
    unittest.main()