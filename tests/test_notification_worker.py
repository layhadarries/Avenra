"""Notification worker safety tests. No real messages are sent."""
import unittest
from unittest.mock import Mock

import test_avenra
from avenra.services.notification_worker import NotificationWorker


class NotificationWorkerTests(unittest.TestCase):
    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)
        self.conn = None

        response = self.client.post(
            "/api/alerts",
            json={
                "client_id": "worker-test-alert",
                "lat": -33.9249,
                "lng": 18.4241,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.get_json()["id"]

        self.conn = test_avenra.db.connect()
        # Explicit permission in these synthetic provider-dispatch fixtures.
        self.conn.execute("UPDATE contacts SET sms_opt_in=1")
        self.conn.commit()

        # Keep one job in this temporary fixture for deterministic tests.
        row = self.conn.execute(
            """
            SELECT id FROM notification_outbox
            WHERE alert_id = ?
            ORDER BY id LIMIT 1
            """,
            (self.alert_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.job_id = row["id"]

        self.conn.execute(
            """
            DELETE FROM notification_outbox
            WHERE alert_id = ? AND id != ?
            """,
            (self.alert_id, self.job_id),
        )
        self.conn.commit()

    def tearDown(self):
        if self.conn is not None:
            self.conn.close()
        test_avenra.avenraStagesTestCase.tearDown(self)

    def status(self):
        return self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (self.job_id,),
        ).fetchone()["status"]

    def worker(self, sender, evaluation_mode=False):
        return NotificationWorker(
            connection=self.conn,
            sender=sender,
            evaluation_mode=evaluation_mode,
        )

    def test_commits_claim_before_calling_sender(self):
        def send(**kwargs):
            other = test_avenra.db.connect()
            try:
                row = other.execute(
                    """
                    SELECT status, claim_token
                    FROM notification_outbox WHERE id = ?
                    """,
                    (self.job_id,),
                ).fetchone()
                self.assertEqual(row["status"], "processing")
                self.assertTrue(row["claim_token"])
            finally:
                other.close()

            return {"outcome": "accepted"}

        sender = Mock(side_effect=send)
        worker = self.worker(sender)

        self.assertTrue(worker.run_once())
        self.assertEqual(self.status(), "accepted")
        sender.assert_called_once()

        self.assertFalse(worker.run_once())
        sender.assert_called_once()

    def test_timeout_is_unknown_and_is_not_automatically_retried(self):
        sender = Mock(side_effect=TimeoutError("private-provider-detail"))
        worker = self.worker(sender)

        self.assertTrue(worker.run_once())
        self.assertEqual(self.status(), "unknown")
        self.assertFalse(worker.run_once())
        sender.assert_called_once()

    def test_evaluation_mode_does_not_claim_or_send(self):
        sender = Mock()
        worker = self.worker(sender, evaluation_mode=True)

        self.assertFalse(worker.run_once())
        self.assertEqual(self.status(), "pending")
        sender.assert_not_called()

    def test_revoked_location_is_not_in_message(self):
        response = self.client.post(
            "/api/consents",
            json={"item": "location_sharing", "active": False},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)

        sender = Mock(return_value={"outcome": "accepted"})
        self.assertTrue(self.worker(sender).run_once())

        message = sender.call_args.kwargs["message"]
        self.assertIn("Location unavailable", message)
        self.assertNotIn("-33.9249", message)
        self.assertNotIn("18.4241", message)
        self.assertNotIn("maps.google", message)

    def test_missing_provider_outcome_is_unknown(self):
        sender = Mock(return_value={})

        self.assertTrue(self.worker(sender).run_once())
        self.assertEqual(self.status(), "unknown")

    def test_provider_response_cannot_directly_claim_delivery(self):
        sender = Mock(return_value={"outcome": "delivered"})

        self.assertTrue(self.worker(sender).run_once())
        self.assertEqual(self.status(), "unknown")

    def test_recovery_commits_unknown_state_and_audit(self):
        sender = Mock()
        worker = self.worker(sender)
        job = worker.repo.claim_next()

        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = '2000-01-01T00:00:00Z'
            WHERE id = ?
            """,
            (job["id"],),
        )
        self.conn.commit()

        self.assertEqual(worker.recover_stale(), 1)
        sender.assert_not_called()

        other = test_avenra.db.connect()
        try:
            status = other.execute(
                "SELECT status FROM notification_outbox WHERE id = ?",
                (job["id"],),
            ).fetchone()["status"]
            self.assertEqual(status, "unknown")

            event = other.execute(
                """
                SELECT detail FROM audit_log
                WHERE action = 'notification_recovery'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(
                event["detail"], "claims_marked_unknown=1"
            )
        finally:
            other.close()

    def test_evaluation_mode_does_not_recover_claims(self):
        sender = Mock()
        worker = self.worker(sender, evaluation_mode=True)
        job = worker.repo.claim_next()

        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = '2000-01-01T00:00:00Z'
            WHERE id = ?
            """,
            (job["id"],),
        )
        self.conn.commit()

        self.assertEqual(worker.recover_stale(), 0)
        self.assertEqual(self.status(), "processing")
        sender.assert_not_called()

    def test_recovery_rejects_invalid_age(self):
        sender = Mock()
        worker = self.worker(sender)

        for age in (None, True, "900", 0, -1, 59, 86401):
            with self.subTest(age=age):
                with self.assertRaises(ValueError):
                    worker.recover_stale(age)

        self.assertEqual(self.status(), "pending")
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()