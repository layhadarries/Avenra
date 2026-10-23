"""Case-access regression tests using temporary test data."""
import unittest

import test_avenra


class DashboardAccessTests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff
    _staff_post = test_avenra.avenraStagesTestCase._staff_post

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)

        response = self.client.post(
            "/api/alerts",
            json={
                "client_id": "dashboard.js-access-test",
                "lat": -33.9249,
                "lng": 18.4241,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.get_json()["id"]
        self._login_staff("responder")

    def revoke_case_access(self):
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        conn = test_avenra.db.connect()
        try:
            conn.execute(
                "DELETE FROM case_access WHERE staff_id = ?",
                (staff_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def test_revoked_staff_cannot_list_case_alerts(self):
        before = self.client.get("/api/alerts")
        self.assertEqual(before.status_code, 200)
        self.assertIn(
            self.alert_id,
            [a["id"] for a in before.get_json()["alerts"]],
        )

        self.revoke_case_access()

        after = self.client.get("/api/alerts")
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.get_json()["alerts"], [])

    def test_revoked_staff_cannot_acknowledge_alert(self):
        self.revoke_case_access()

        response = self._staff_post(
            f"/api/alerts/{self.alert_id}/acknowledge"
        )
        self.assertEqual(response.status_code, 404)

        conn = test_avenra.db.connect()
        try:
            row = conn.execute(
                "SELECT status, acknowledged_by FROM alerts WHERE id = ?",
                (self.alert_id,),
            ).fetchone()
            self.assertEqual(row["status"], "new")
            self.assertIsNone(row["acknowledged_by"])
        finally:
            conn.close()

    def test_revoked_staff_cannot_read_case_consents(self):
        self.assertEqual(
            self.client.get("/api/consents").status_code,
            200,
        )

        self.revoke_case_access()

        response = self.client.get("/api/consents")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("consents", response.get_json())

    def test_alert_preserves_measured_location_metadata(self):
        captured_at = "2026-10-23T12:00:00Z"

        created = self.client.post(
            "/api/alerts",
            json={
                "client_id": "dashboard.js-measured-location",
                "lat": -33.9249,
                "lng": 18.4241,
                "location_accuracy": 35.5,
                "location_recorded_at": captured_at,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(created.status_code, 201)

        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)

        alert = next(
            a for a in response.get_json()["alerts"]
            if a["id"] == created.get_json()["id"]
        )
        self.assertAlmostEqual(alert["lat"], -33.9249)
        self.assertAlmostEqual(alert["lng"], 18.4241)
        self.assertEqual(alert["location_accuracy"], 35.5)
        self.assertEqual(alert["location_recorded_at"], captured_at)

    def test_alert_without_location_has_no_fix_metadata(self):
        created = self.client.post(
            "/api/alerts",
            json={"client_id": "dashboard.js-no-location"},
            headers=self.survivor_headers,
        )
        self.assertEqual(created.status_code, 201)

        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)

        alert = next(
            a for a in response.get_json()["alerts"]
            if a["id"] == created.get_json()["id"]
        )

        for field in (
            "lat", "lng",
            "location_accuracy", "location_recorded_at",
        ):
            with self.subTest(field=field):
                self.assertIsNone(alert[field])

    def test_location_revocation_hides_fix_metadata(self):
        revoked = self.client.post(
            "/api/consents",
            json={"item": "location_sharing", "active": False},
            headers=self.survivor_headers,
        )
        self.assertEqual(revoked.status_code, 200)

        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)

        alert = next(
            a for a in response.get_json()["alerts"]
            if a["id"] == self.alert_id
        )
        self.assertTrue(alert["location_redacted"])

        for field in (
            "lat", "lng",
            "location_accuracy", "location_recorded_at",
        ):
            with self.subTest(field=field):
                self.assertIsNone(alert[field])