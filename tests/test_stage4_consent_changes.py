"""Stage 4: consent changes must produce truthful history"""
import unittest
from contextlib import closing

import test_avenra

class ConsentChangeTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                survivor = conn.execute(
                    """
                    SELECT id, case_code FROM users
                    WHERE role = 'survivor'
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()

                self.survivor_id = survivor["id"]
                self.case_code = survivor["case_code"]

                conn.execute(
                    """
                    UPDATE consents
                    SET granted_at = '2026-01-01T12:00:00Z',
                        revoked_at = NULL
                    WHERE user_id = ? AND item = 'location_sharing'
                    """,
                    (self.survivor_id,)
                )

    def save_location_consent(self, active):
        return self.client.post(
            "/api/consents",
            headers=self.survivor_headers,
            json={
                "item": "location_sharing",
                "active": active,
            },
        )

    def snapshot(self):
        with closing(test_avenra.db.connect()) as conn:
            consent = conn.execute(
                """
                SELECT granted_at, revoked_at
                FROM consents
                WHERE user_id = ? AND item = 'location_sharing'
                ORDER BY id DESC LIMIT 1
                """,
                (self.survivor_id,),
            ).fetchone()

            count = conn.execute(
                """
                SELECT COUNT(*) FROM audit_log
                WHERE case_code = ?
                AND action IN ('consent_granted', 'consent_revoked')
                """,
                (self.case_code,),
            ).fetchone()[0]

        self.assertIsNotNone(consent)
        return dict(consent), count

    def test_unchanged_grant_preserves_timestamp_and_audit_count(self):
        before, before_count = self.snapshot()

        response = self.save_location_consent(True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["consent"]["active"])

        after, after_count = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after_count, before_count)

    def test_repeated_revocation_does_not_add_another_event(self):
        first = self.save_location_consent(False)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json["consent"]["active"])

        before, before_count = self.snapshot()

        repeated = self.save_location_consent(False)
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json["consent"]["active"])

        after, after_count = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after_count, before_count)

    def test_real_revocation_adds_exactly_one_matching_event(self):
        _, before_count = self.snapshot()

        response = self.save_location_consent(False)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["consent"]["active"])

        after, after_count = self.snapshot()
        self.assertIsNotNone(after["revoked_at"])
        self.assertEqual(after_count, before_count + 1)

        with closing(test_avenra.db.connect()) as conn:
            event = conn.execute(
                """
                SELECT action FROM audit_log
                WHERE case_code = ?
                AND action IN ('consent_granted', 'consent_revoked')
                ORDER BY id DESC LIMIT 1
                """,
                (self.case_code,),
            ).fetchone()

        self.assertEqual(event["action"], "consent_revoked")

if __name__ == "__main__":
    unittest.main()