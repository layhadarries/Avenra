"""Notification jobs must survive reconnects and remain idempotent."""
import unittest
from unittest.mock import patch

import test_avenra
from avenra.repositories.notification_outbox_repository import (
    NotificationOutboxRepository,
)


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)
        self.conn = None

        with patch(
            "avenra.services.alert_service.sms.notify_contacts",
            return_value=[],
        ):
            response = self.client.post(
                "/api/alerts",
                json={"client_id": "outbox-test-alert"},
                headers=self.survivor_headers,
            )

        self.assertEqual(response.status_code, 201)
        self.alert_id = response.get_json()["id"]

        self.conn = test_avenra.db.connect()

        # Alert creation now queues jobs automatically.
        # Clear this fixture alert's jobs so repository tests start empty.
        self.conn.execute(
            "DELETE FROM notification_outbox WHERE alert_id = ?",
            (self.alert_id,),
        )
        self.conn.commit()

        self.repo = NotificationOutboxRepository(self.conn)

        rows = self.conn.execute(
            """
            SELECT contacts.id
            FROM contacts
            JOIN alerts ON alerts.user_id = contacts.user_id
            WHERE alerts.id = ?
            ORDER BY contacts.id
            """,
            (self.alert_id,),
        ).fetchall()
        self.contact_ids = {row["id"] for row in rows}
        self.assertTrue(self.contact_ids)

    def tearDown(self):
        if self.conn is not None:
            self.conn.close()
        test_avenra.avenraStagesTestCase.tearDown(self)

    def test_queues_one_pending_job_per_selected_contact(self):
        self.repo.enqueue_for_alert(self.alert_id)

        jobs = self.repo.pending()

        self.assertEqual(len(jobs), len(self.contact_ids))
        self.assertEqual(
            {job["contact_id"] for job in jobs},
            self.contact_ids,
        )
        for job in jobs:
            self.assertEqual(job["alert_id"], self.alert_id)
            self.assertEqual(job["status"], "pending")

    def test_enqueue_retry_does_not_duplicate_jobs(self):
        self.repo.enqueue_for_alert(self.alert_id)
        self.conn.commit()
        first = self.repo.pending()

        self.repo.enqueue_for_alert(self.alert_id)
        self.conn.commit()
        second = self.repo.pending()

        self.assertEqual(len(first), len(self.contact_ids))
        self.assertEqual(
            {job["id"] for job in first},
            {job["id"] for job in second},
        )

    def test_committed_jobs_survive_database_reconnect(self):
        self.repo.enqueue_for_alert(self.alert_id)
        self.conn.commit()
        original_ids = {job["id"] for job in self.repo.pending()}

        other_conn = test_avenra.db.connect()
        try:
            other_repo = NotificationOutboxRepository(other_conn)
            recovered_ids = {
                job["id"] for job in other_repo.pending()
            }
            self.assertEqual(recovered_ids, original_ids)
            self.assertTrue(recovered_ids)
        finally:
            other_conn.close()

    def test_enqueue_participates_in_callers_transaction(self):
        self.repo.enqueue_for_alert(self.alert_id)
        self.conn.rollback()

        self.assertEqual(self.repo.pending(), [])


if __name__ == "__main__":
    unittest.main()