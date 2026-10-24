"""Denied staff access must produce safe, bounded audit records."""
import unittest
from contextlib import closing

import test_avenra


class AccessDenialTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)
        self._login_staff("shelter")

        with self.client.session_transaction() as session:
            self.staff_id = session["user_id"]

    def denied_events(self):
        with closing(test_avenra.db.connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, actor, action, case_code, detail
                FROM audit_log
                WHERE actor = ? AND action = 'access_denied'
                ORDER BY id
                """,
                (f"user:{self.staff_id}",),
            ).fetchall()

        return [dict(row) for row in rows]

    def test_forbidden_audit_page_access_is_recorded(self):
        response = self.client.get("/audit-log")
        self.assertEqual(response.status_code, 403)

        events = self.denied_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["actor"], f"user:{self.staff_id}")
        self.assertIsNone(event["case_code"])
        self.assertIn("audit_log_page", event["detail"])
        self.assertIn("shelter", event["detail"])

    def test_denied_api_log_does_not_capture_query_values(self):
        response = self.client.get(
            "/api/audit-log",
            query_string={
                "case_code": "PRIVATE-CASE-REFERENCE",
                "token": "PRIVATE-TOKEN-MUST-NOT-LEAK",
            },
        )
        self.assertEqual(response.status_code, 403)

        events = self.denied_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertIsNone(event["case_code"])
        self.assertIn("api_audit_log", event["detail"])
        self.assertIn("shelter", event["detail"])
        self.assertNotIn("PRIVATE-CASE-REFERENCE", event["detail"])
        self.assertNotIn("PRIVATE-TOKEN-MUST-NOT-LEAK", event["detail"])

    def test_repeated_same_denial_is_coalesced(self):
        for _ in range(5):
            response = self.client.get("/api/audit-log")
            self.assertEqual(response.status_code, 403)

        # Same staff, endpoint and method within the suppression window.
        self.assertEqual(len(self.denied_events()), 1)

    def test_denial_after_suppression_window_records_new_event(self):
        import db
        from contextlib import closing
        from datetime import datetime, timedelta, timezone

        self.assertEqual(
            self.client.get("/api/audit-log").status_code, 403
        )
        events = self.denied_events()
        self.assertEqual(len(events), 1)

        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=120)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        with closing(db.connect()) as conn:
            with conn:
                conn.execute(
                    "UPDATE audit_log SET ts = ? WHERE id = ?",
                    (old_timestamp, events[0]["id"]),
                )

        self.assertEqual(
            self.client.get("/api/audit-log").status_code, 403
        )
        self.assertEqual(len(self.denied_events()), 2)

    def test_page_and_api_denials_are_recorded_separately(self):
        self.assertEqual(
            self.client.get("/audit-log").status_code, 403
        )
        self.assertEqual(
            self.client.get("/api/audit-log").status_code, 403
        )

        events = self.denied_events()
        self.assertEqual(len(events), 2)
        details = [event["detail"] for event in events]

        self.assertTrue(any(
            "endpoint=audit_log_page;" in detail
            for detail in details
        ))
        self.assertTrue(any(
            "endpoint=api_audit_log;" in detail
            for detail in details
        ))

    def test_simultaneous_denials_record_one_event(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from types import SimpleNamespace

        from avenra.services.access_denial_service import (
            AccessDenialService,
        )

        app = self.client.application
        user = SimpleNamespace(id=self.staff_id, role="shelter")
        barrier = Barrier(2)

        def record_denial():
            with app.app_context():
                barrier.wait(timeout=10)
                return AccessDenialService().record(
                    user, "api_audit_log", "GET"
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(record_denial)
                for _ in range(2)
            ]
            results = [
                future.result(timeout=20)
                for future in futures
            ]

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)
        self.assertEqual(len(self.denied_events()), 1)


if __name__ == "__main__":
    unittest.main()