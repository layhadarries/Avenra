"""Alert creation and notification jobs must commit together."""
import sqlite3
import unittest
from unittest.mock import patch

import test_avenra


class AlertOutboxTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown

    def create_alert(self, client_id):
        return self.client.post(
            "/api/alerts",
            json={"client_id": client_id},
            headers=self.survivor_headers,
        )

    def jobs_for(self, alert_id):
        conn = test_avenra.db.connect()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, contact_id, status
                    FROM notification_outbox
                    WHERE alert_id = ?
                    ORDER BY id
                    """,
                    (alert_id,),
                )
            ]
        finally:
            conn.close()

    def test_alert_receipt_confirms_committed_pending_jobs(self):
        with patch(
            "avenra.services.alert_service.sms.notify_contacts",
            return_value=[],
        ):
            response = self.create_alert("outbox-api-create")

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        jobs = self.jobs_for(body["id"])

        conn = test_avenra.db.connect()
        try:
            expected = conn.execute(
                """
                SELECT COUNT(*)
                FROM contacts
                JOIN alerts ON alerts.user_id = contacts.user_id
                WHERE alerts.id = ?
                """,
                (body["id"],),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertGreater(expected, 0)
        self.assertEqual(len(jobs), expected)
        self.assertTrue(all(job["status"] == "pending" for job in jobs))
        self.assertEqual(body["notification_mode"], "queued")
        self.assertEqual(body["contacts_accepted"], 0)
        self.assertEqual(body["contacts_notified"], 0)

    def test_alert_request_does_not_send_notifications_directly(self):
        with patch(
            "avenra.services.alert_service.sms.notify_contacts",
            return_value=[],
        ) as dispatch:
            response = self.create_alert("outbox-api-no-direct-send")

        self.assertEqual(response.status_code, 201)
        dispatch.assert_not_called()

    def test_repeated_alert_does_not_duplicate_jobs(self):
        with patch(
            "avenra.services.alert_service.sms.notify_contacts",
            return_value=[],
        ):
            first = self.create_alert("outbox-api-repeat")
            self.assertEqual(first.status_code, 201)
            alert_id = first.get_json()["id"]
            original = self.jobs_for(alert_id)

            second = self.create_alert("outbox-api-repeat")

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["id"], alert_id)
        self.assertTrue(original)
        self.assertEqual(self.jobs_for(alert_id), original)

    def test_enqueue_failure_rolls_back_alert_creation(self):
        with (
            patch(
                "avenra.repositories.notification_outbox_repository."
                "NotificationOutboxRepository.enqueue_for_alert",
                side_effect=sqlite3.OperationalError(
                    "private-database-detail"
                ),
            ),
            patch(
                "avenra.services.alert_service.sms.notify_contacts",
                return_value=[],
            ) as dispatch,
        ):
            response = self.create_alert("outbox-api-storage-failure")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(
            "private-database-detail",
            response.get_data(as_text=True),
        )
        dispatch.assert_not_called()

        conn = test_avenra.db.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE client_id = ?",
                ("outbox-api-storage-failure",),
            ).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()