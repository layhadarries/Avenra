"""Staff audit page controls, filtering and access boundaries."""
import unittest
from contextlib import closing

import test_avenra


class StaffAuditTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)
        self._login_staff("responder")

        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                self.case_code = conn.execute(
                    """
                    SELECT case_code FROM users
                    WHERE role = 'survivor'
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()["case_code"]

                self.own_event_id = conn.execute(
                    """
                    INSERT INTO audit_log
                        (actor, action, case_code, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        f"user:{staff_id}",
                        "case_viewed",
                        self.case_code,
                        "Permitted test event",
                    ),
                ).lastrowid

                self.other_event_id = conn.execute(
                    """
                    INSERT INTO audit_log
                        (actor, action, case_code, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        f"user:{staff_id}",
                        "case_viewed",
                        "UNASSIGNED-CASE",
                        "OTHER-CASE-DETAIL-MUST-NOT-LEAK",
                    ),
                ).lastrowid

    def test_page_has_filters_results_and_pagination(self):
        response = self.client.get("/audit-log")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        for element_id in (
            "audit-case",
            "audit-category",
            "audit-status",
            "audit-rows",
            "audit-previous",
            "audit-next",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)

        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_staff_api_excludes_unassigned_case_events(self):
        response = self.client.get("/api/audit-log")
        self.assertEqual(response.status_code, 200)

        ids = [event["id"] for event in response.json["events"]]
        self.assertIn(self.own_event_id, ids)
        self.assertNotIn(self.other_event_id, ids)
        self.assertNotIn(
            "OTHER-CASE-DETAIL-MUST-NOT-LEAK",
            response.get_data(as_text=True),
        )

    def test_case_filter_is_exact_and_preserves_access_scope(self):
        own = self.client.get(
            "/api/audit-log",
            query_string={"case_code": self.case_code},
        )
        self.assertEqual(own.status_code, 200)
        self.assertTrue(own.json["events"])

        for event in own.json["events"]:
            self.assertEqual(event["case_code"], self.case_code)

        # Even a known event cannot be fetched without case access.
        other = self.client.get(
            "/api/audit-log",
            query_string={"case_code": "UNASSIGNED-CASE"},
        )
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json["events"], [])
        self.assertEqual(other.json["total"], 0)

    def test_signed_out_staff_cannot_open_page_or_read_api(self):
        client = test_avenra.avenra_app.app.test_client()

        page = client.get("/audit-log")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/login", page.headers["Location"])

        response = client.get("/api/audit-log")
        self.assertEqual(response.status_code, 401)

    def test_shelter_staff_cannot_open_page_or_read_api(self):
        self._login_staff("shelter")

        self.assertEqual(
            self.client.get("/audit-log").status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/audit-log").status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()