"""Case workspace must honour current location consent."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import test_avenra as fixtures
from avenra.repositories.portal_repository import PortalRepository
from avenra.services.case_service import CaseService
import db


class CaseLocationConsentTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff

    def create_alert(self, *, with_location=True):
        payload = {"client_id": "stage4-case-location"}
        if with_location:
            payload.update({
                "lat": -33.9249,
                "lng": 18.4241,
                "location_accuracy": 35.5,
                "location_recorded_at": datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

        response = self.client.post(
            "/api/alerts",
            json=payload,
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def set_location_consent(self, active):
        response = self.client.post(
            "/api/consents",
            json={"item": "location_sharing", "active": active},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)

    def case_alert(self, receipt):
        self._login_staff("responder")
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        with self.client.application.app_context():
            workspace = CaseService(
                PortalRepository(db.get_db())
            ).view(
                SimpleNamespace(id=staff_id, role="responder"),
                receipt["case_code"],
            )
            self.assertIsNotNone(workspace)
            return next(
                alert for alert in workspace["alerts"]
                if alert["id"] == receipt["id"]
            )

    def test_granted_consent_preserves_location_metadata(self):
        self.set_location_consent(True)
        receipt = self.create_alert()
        alert = self.case_alert(receipt)

        self.assertAlmostEqual(alert["lat"], -33.9249)
        self.assertAlmostEqual(alert["lng"], 18.4241)
        self.assertEqual(alert["location_accuracy"], 35.5)
        self.assertIsNotNone(alert["location_recorded_at"])
        self.assertFalse(alert["location_redacted"])

    def test_withdrawal_hides_location_and_regrant_restores_it(self):
        self.set_location_consent(True)
        receipt = self.create_alert()

        self.set_location_consent(False)
        hidden = self.case_alert(receipt)
        for field in (
            "lat", "lng",
            "location_accuracy", "location_recorded_at",
        ):
            with self.subTest(field=field):
                self.assertIsNone(hidden[field])
        self.assertTrue(hidden["location_redacted"])

        self.set_location_consent(True)
        restored = self.case_alert(receipt)
        self.assertAlmostEqual(restored["lat"], -33.9249)
        self.assertAlmostEqual(restored["lng"], 18.4241)
        self.assertEqual(restored["location_accuracy"], 35.5)
        self.assertIsNotNone(restored["location_recorded_at"])
        self.assertFalse(restored["location_redacted"])

    def test_alert_without_coordinates_has_no_location_metadata(self):
        self.set_location_consent(True)
        receipt = self.create_alert(with_location=False)
        alert = self.case_alert(receipt)

        for field in (
            "lat", "lng",
            "location_accuracy", "location_recorded_at",
        ):
            with self.subTest(field=field):
                self.assertIsNone(alert[field])
        self.assertFalse(alert["location_redacted"])


if __name__ == "__main__":
    unittest.main()