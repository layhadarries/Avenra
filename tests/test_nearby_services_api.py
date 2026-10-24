"""Nearby services require authorised, consented alert access."""
import unittest
from contextlib import closing

import test_avenra


class NearbyServicesAPITests(unittest.TestCase):
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)

        response = self.client.post(
            "/api/alerts",
            json={
                "client_id": "nearby-services-test",
                "lat": 0,
                "lng": 0,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.json["id"]
        self.url = f"/api/alerts/{self.alert_id}/nearby-services"

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                rows = conn.execute(
                    "SELECT id FROM shelters ORDER BY id"
                ).fetchall()
                self.assertGreaterEqual(len(rows), 3)
                self.near_id = rows[0]["id"]
                self.medium_id = rows[1]["id"]

                conn.execute("UPDATE shelters SET lat = NULL, lng = NULL")
                conn.execute(
                    "UPDATE shelters SET lat = ?, lng = 0 WHERE id = ?",
                    (0.1, self.near_id),
                )
                conn.execute(
                    "UPDATE shelters SET lat = ?, lng = 0 WHERE id = ?",
                    (0.3, self.medium_id),
                )
                conn.execute(
                    "UPDATE shelters SET lat = ?, lng = 0 WHERE id = ?",
                    (0.6, rows[2]["id"]),
                )

        self._login_staff("responder")

    def test_default_returns_only_services_within_25_km(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["radius_km"], 25)
        entries = response.json["shelters"]
        self.assertEqual([entry["id"] for entry in entries], [self.near_id])
        self.assertEqual(entries[0]["availability"], "contact_to_confirm")
        self.assertNotIn("beds_available", entries[0])
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_50_km_returns_nearest_first(self):
        response = self.client.get(self.url + "?radius_km=50")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["radius_km"], 50)
        self.assertEqual(
            [entry["id"] for entry in response.json["shelters"]],
            [self.near_id, self.medium_id],
        )

    def test_invalid_radius_is_rejected(self):
        for radius in ("", "30", "100", "-25", "true", "25.0"):
            with self.subTest(radius=radius):
                response = self.client.get(
                    self.url, query_string={"radius_km": radius}
                )
                self.assertEqual(response.status_code, 400)

    def test_signed_out_request_is_rejected(self):
        client = test_avenra.avenra_app.app.test_client()
        self.assertEqual(client.get(self.url).status_code, 401)

    def test_device_credentials_cannot_replace_staff_login(self):
        client = test_avenra.avenra_app.app.test_client()
        response = client.get(self.url, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 401)

    def test_shelter_role_cannot_lookup_incident_location(self):
        self._login_staff("shelter")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_revoked_case_access_hides_alert(self):
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
        self.assertNotIn("shelters", response.json)

    def test_revoked_location_consent_prevents_matching(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE consents SET revoked_at = '2026-10-23T00:00:00Z'
                    WHERE item = 'location_sharing'
                    AND user_id = (
                        SELECT user_id FROM alerts WHERE id = ?
                    )
                    """,
                    (self.alert_id,),
                )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "location_unavailable")
        self.assertNotIn("shelters", response.json)

    def test_missing_location_does_not_return_entire_directory(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    "UPDATE alerts SET lat = NULL, lng = NULL WHERE id = ?",
                    (self.alert_id,),
                )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error"], "location_unavailable")
        self.assertNotIn("shelters", response.json)


if __name__ == "__main__":
    unittest.main()