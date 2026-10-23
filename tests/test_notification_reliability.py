"""Alert receipt must not depend on request-time provider calls."""
import unittest
from unittest.mock import patch

import test_avenra


class NotificationReliabilityTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown

    def create_alert(self, client_id):
        return self.client.post(
            "/api/alerts",
            json={"client_id": client_id},
            headers=self.survivor_headers,
        )

    def test_provider_is_not_called_during_alert_creation(self):
        with patch(
            "avenra.services.alert_service.sms.notify_contacts",
            side_effect=TimeoutError("private-provider-detail"),
        ) as dispatch:
            response = self.create_alert("provider-independent-alert")

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["notification_mode"], "queued")
        self.assertGreater(body["contacts_queued"], 0)
        self.assertEqual(body["contacts_accepted"], 0)
        self.assertEqual(body["contacts_notified"], 0)
        dispatch.assert_not_called()

    def test_alert_retry_returns_same_alert_without_dispatch(self):
        with patch(
            "avenra.services.alert_service.sms.notify_contacts"
        ) as dispatch:
            first = self.create_alert("notification-retry")
            second = self.create_alert("notification-retry")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.get_json()["id"], second.get_json()["id"]
        )
        dispatch.assert_not_called()

    def test_queued_receipt_does_not_claim_acceptance_or_delivery(self):
        response = self.create_alert("queued-not-delivered")

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["notification_mode"], "queued")
        self.assertEqual(body["contacts_accepted"], 0)
        self.assertEqual(body["contacts_notified"], 0)


if __name__ == "__main__":
    unittest.main()