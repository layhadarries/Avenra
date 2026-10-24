"""The legacy audit endpoint must not bypass survivor history privacy."""
import unittest
from contextlib import closing

import test_avenra
import test_stage4_my_access


class AuditBoundaryTests(unittest.TestCase):
    setUp = test_stage4_my_access.MyAccessTests.setUp
    tearDown = test_stage4_my_access.MyAccessTests.tearDown
    seed_history = test_stage4_my_access.MyAccessTests.seed_history

    def test_legacy_survivor_response_matches_safe_history(self):
        self.seed_history()

        history = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
        )
        legacy = self.client.get(
            "/api/audit-log",
            headers=self.survivor_headers,
        )

        self.assertEqual(history.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.get_json(), history.get_json())
        self.assertIn("no-store", legacy.headers["Cache-Control"])
        self.assertNotIn(
            "PRIVATE-DETAIL-MUST-NOT-LEAK",
            legacy.get_data(as_text=True),
        )

    def test_legacy_endpoint_rejects_client_selected_ownership(self):
        for selector in ("case_code", "survivor_id", "staff_id"):
            with self.subTest(selector=selector):
                response = self.client.get(
                    "/api/audit-log",
                    headers=self.survivor_headers,
                    query_string={selector: "OTHER"},
                )
                self.assertEqual(response.status_code, 400)

    def test_reading_history_does_not_create_more_audit_events(self):
        self.seed_history()

        with closing(test_avenra.db.connect()) as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM audit_log"
            ).fetchone()[0]

        for endpoint in ("/api/my-access", "/api/audit-log"):
            response = self.client.get(
                endpoint,
                headers=self.survivor_headers,
            )
            self.assertEqual(response.status_code, 200)

        with closing(test_avenra.db.connect()) as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM audit_log"
            ).fetchone()[0]

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()