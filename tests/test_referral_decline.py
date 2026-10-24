"""Declines require a valid reason and remain terminal."""
import unittest
from contextlib import closing

import test_avenra
import test_referral_requests


class ReferralDeclineTests(unittest.TestCase):
    setUp = test_referral_requests.ReferralRequestTests.setUp
    tearDown = test_referral_requests.ReferralRequestTests.tearDown
    _login_staff = test_referral_requests.ReferralRequestTests._login_staff
    _staff_post = test_referral_requests.ReferralRequestTests._staff_post
    request_referral = (test_referral_requests.ReferralRequestTests.request_referral)

    def create_referral(self):
        response = self.request_referral()
        self.assertEqual(response.status_code, 201)
        return response.json["referral"]["id"]

    def test_invalid_reason_preserves_sent_status(self):
        referral_id = self.create_referral()

        for reason in (None, "", "   ", 123, True, "A" * 201):
            with self.subTest(reason=reason):
                response = self._staff_post(
                    f"/api/referrals/{referral_id}/status",
                    json={
                        "status": "declined",
                        "decline_reason": reason,
                    },
                )
                self.assertEqual(response.status_code, 400)

                with closing(test_avenra.db.connect()) as conn:
                    row = conn.execute(
                        """
                        SELECT status, decline_reason
                        FROM referrals WHERE id = ?
                        """,
                        (referral_id,),
                    ).fetchone()

                self.assertEqual(row["status"], "sent")
                self.assertIsNone(row["decline_reason"])

    def test_valid_reason_is_saved_without_resolving_alert(self):
        referral_id = self.create_referral()
        response = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={
                "status": "declined",
                "decline_reason": "  Service cannot assist this referral.  ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["referral"]["status"], "declined")
        self.assertEqual(
            response.json["referral"]["decline_reason"],
            "Service cannot assist this referral.",
        )

        with closing(test_avenra.db.connect()) as conn:
            alert = conn.execute(
                "SELECT status FROM alerts WHERE id = ?",
                (self.alert_id,),
            ).fetchone()

        self.assertNotEqual(alert["status"], "resolved")

    def test_declined_referral_cannot_be_reopened(self):
        referral_id = self.create_referral()
        declined = self._staff_post(
            f"/api/referrals/{referral_id}/status",
            json={
                "status": "declined",
                "decline_reason": "Unable to assist.",
            },
        )
        self.assertEqual(declined.status_code, 200)

        for status in ("accepted", "placed"):
            with self.subTest(status=status):
                response = self._staff_post(
                    f"/api/referrals/{referral_id}/status",
                    json={"status": status},
                )
                self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()