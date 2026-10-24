"""Case workspace controls remain restricted to authorised staff."""
import unittest
from contextlib import closing

import test_avenra


class CaseWorkspaceTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)

        response = self.client.post(
            "/api/alerts",
            json={
                "client_id": "case-workspace-test",
                "lat": -33.9249,
                "lng": 18.4241,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.json["id"]
        self.case_code = response.json["case_code"]
        self.url = f"/cases/{self.case_code}"

        self._login_staff("responder")

    def test_authorised_case_has_alert_and_nearby_controls(self):
        response = self.client.get(
            self.url,
            query_string={"alert_id": self.alert_id},
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('id="case-alert-select"', html)
        self.assertIn('id="nearby-radius"', html)
        self.assertIn('id="nearby-services"', html)
        self.assertIn('value="25"', html)
        self.assertIn('value="50"', html)
        self.assertIn(
            f'data-selected-alert-id="{self.alert_id}"', html
        )
        self.assertIn("Contact to confirm", html)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_revoked_case_access_prevents_workspace_access(self):
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    "DELETE FROM case_access WHERE staff_id = ?",
                    (staff_id,),
                )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(
            'id="case-alert-select"',
            response.get_data(as_text=True),
        )

    def test_shelter_staff_cannot_open_case_workspace(self):
        self._login_staff("shelter")
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(
            'id="case-alert-select"',
            response.get_data(as_text=True),
        )

    def test_case_workspace_renders_shared_diary_and_updates_access_signature(self):
        self.client.post(
            "/api/consents",
            json={"item": "diary_sharing", "active": True},
            headers=self.survivor_headers,
        )
        shared_res = self.client.post(
            "/api/diary",
            headers=self.survivor_headers,
            json={
                "client_id": "workspace-shared-entry",
                "note": "VISIBLE-SHARED-NOTE",
                "shared": True,
                "captured_at": "2026-04-01T10:00:00Z",
            },
        )
        self.assertEqual(shared_res.status_code, 201)
        shared_id = shared_res.json["id"]

        private_res = self.client.post(
            "/api/diary",
            headers=self.survivor_headers,
            json={
                "client_id": "workspace-private-entry",
                "note": "HIDDEN-PRIVATE-NOTE",
                "shared": False,
            },
        )
        self.assertEqual(private_res.status_code, 201)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"), "private, no-store"
        )
        html = response.get_data(as_text=True)
        self.assertIn('id="case-diary-section"', html)
        self.assertIn('id="case-diary-entries"', html)
        self.assertIn("VISIBLE-SHARED-NOTE", html)
        self.assertNotIn("HIDDEN-PRIVATE-NOTE", html)
        self.assertNotIn("download all", html.lower())

        sig_before = self.client.get("/api/session").json["access_signature"]
        unshare_res = self.client.post(
            f"/api/diary/{shared_id}/share",
            headers=self.survivor_headers,
            json={"shared": False},
        )
        self.assertEqual(unshare_res.status_code, 200)
        sig_after = self.client.get("/api/session").json["access_signature"]
        self.assertNotEqual(sig_before, sig_after)

        response_after = self.client.get(self.url)
        self.assertNotIn(
            "VISIBLE-SHARED-NOTE", response_after.get_data(as_text=True)
        )


if __name__ == "__main__":
    unittest.main()