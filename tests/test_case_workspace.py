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


if __name__ == "__main__":
    unittest.main()