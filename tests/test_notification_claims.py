"""Workers must claim notification jobs exclusively."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import test_avenra
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
from datetime import datetime, timedelta, timezone


class NotificationClaimTests(unittest.TestCase):
    def setUp(self):
        test_avenra.avenraStagesTestCase.setUp(self)
        self.conn = None

        response = self.client.post(
            "/api/alerts",
            json={"client_id": "notification-claim-test"},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)

        self.conn = test_avenra.db.connect()
        self.repo = NotificationOutboxRepository(self.conn)
        self.assertGreaterEqual(len(self.repo.pending()), 2)

    def tearDown(self):
        if self.conn is not None:
            self.conn.close()
        test_avenra.avenraStagesTestCase.tearDown(self)

    def test_claim_records_processing_state_and_ownership(self):
        job = self.repo.claim_next()
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "processing")
        self.assertTrue(job["claim_token"])
        self.assertTrue(job["claimed_at"])

        stored = self.conn.execute(
            "SELECT * FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")
        self.assertEqual(stored["claim_token"], job["claim_token"])

    def test_committed_claim_is_not_available_to_another_worker(self):
        first = self.repo.claim_next()
        self.conn.commit()

        other_conn = test_avenra.db.connect()
        try:
            other_repo = NotificationOutboxRepository(other_conn)
            second = other_repo.claim_next()
            self.assertIsNotNone(second)
            self.assertNotEqual(first["id"], second["id"])
            other_conn.commit()
        finally:
            other_conn.close()

    def test_rollback_returns_claim_to_pending(self):
        job = self.repo.claim_next()
        self.conn.rollback()

        pending_ids = {row["id"] for row in self.repo.pending()}
        self.assertIn(job["id"], pending_ids)

    def test_no_pending_jobs_returns_none(self):
        while self.repo.claim_next() is not None:
            pass

        self.assertIsNone(self.repo.claim_next())

    def test_concurrent_workers_claim_different_jobs(self):
        barrier = Barrier(2)

        def claim():
            conn = test_avenra.db.connect()
            try:
                repo = NotificationOutboxRepository(conn)
                barrier.wait(timeout=5)
                job = repo.claim_next()
                conn.commit()
                return job
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(claim) for _ in range(2)]
            jobs = [future.result(timeout=20) for future in futures]

        self.assertTrue(all(job is not None for job in jobs))
        self.assertEqual(len({job["id"] for job in jobs}), 2)
        self.assertEqual(len({job["claim_token"] for job in jobs}), 2)

    def test_owner_can_record_provider_acceptance(self):
        job = self.repo.claim_next()
        self.conn.commit()

        changed = self.repo.finish(
            job["id"], job["claim_token"], "accepted"
        )
        self.conn.commit()

        self.assertTrue(changed)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "accepted")

    def test_wrong_claim_token_cannot_complete_job(self):
        job = self.repo.claim_next()
        self.conn.commit()

        changed = self.repo.finish(
            job["id"], "not-the-owning-token", "accepted"
        )
        self.conn.commit()

        self.assertFalse(changed)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")

    def test_completed_job_cannot_be_overwritten(self):
        job = self.repo.claim_next()
        self.conn.commit()

        self.assertTrue(
            self.repo.finish(job["id"], job["claim_token"], "accepted")
        )
        self.conn.commit()

        self.assertFalse(
            self.repo.finish(job["id"], job["claim_token"], "failed")
        )
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "accepted")

    def test_worker_cannot_claim_delivery_without_delivery_evidence(self):
        job = self.repo.claim_next()
        self.conn.commit()

        for outcome in ("delivered", "pending", "processing", "invalid"):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ValueError):
                    self.repo.finish(
                        job["id"], job["claim_token"], outcome
                    )

        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")

    def test_unknown_outcome_does_not_return_job_to_pending(self):
        job = self.repo.claim_next()
        self.conn.commit()

        self.assertTrue(
            self.repo.finish(job["id"], job["claim_token"], "unknown")
        )
        self.conn.commit()

        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "unknown")
        self.assertNotIn(
            job["id"],
            {pending["id"] for pending in self.repo.pending()},
        )

    def test_stale_processing_job_becomes_unknown(self):
        job = self.repo.claim_next()
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T11:00:00Z", job["id"]),
        )
        self.conn.commit()

        changed = self.repo.mark_stale_unknown(
            datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        )
        self.conn.commit()

        self.assertEqual(changed, 1)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "unknown")
        self.assertNotIn(
            job["id"],
            {row["id"] for row in self.repo.pending()},
        )

        # A late worker cannot overwrite the recovered outcome.
        self.assertFalse(
            self.repo.finish(job["id"], job["claim_token"], "accepted")
        )

    def test_recent_processing_job_is_not_recovered(self):
        job = self.repo.claim_next()
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T12:30:00Z", job["id"]),
        )
        self.conn.commit()

        changed = self.repo.mark_stale_unknown(
            datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        )
        self.conn.commit()

        self.assertEqual(changed, 0)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")

    def test_recovery_does_not_change_pending_jobs(self):
        before = self.repo.pending()

        changed = self.repo.mark_stale_unknown(
            datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        )
        self.conn.commit()

        self.assertEqual(changed, 0)
        self.assertEqual(self.repo.pending(), before)

    def test_recovery_does_not_overwrite_completed_jobs(self):
        job = self.repo.claim_next()
        self.repo.finish(job["id"], job["claim_token"], "accepted")
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T11:00:00Z", job["id"]),
        )
        self.conn.commit()

        self.assertEqual(
            self.repo.mark_stale_unknown(
                datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
            ),
            0,
        )
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "accepted")

    def test_recovery_rejects_timezone_ambiguous_cutoff(self):
        with self.assertRaises(ValueError):
            self.repo.mark_stale_unknown(
                datetime(2026, 10, 23, 12)
            )

    def test_claim_exactly_at_cutoff_is_not_stale(self):
        job = self.repo.claim_next()
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T12:00:00Z", job["id"]),
        )
        self.conn.commit()

        changed = self.repo.mark_stale_unknown(
            datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        )
        self.conn.commit()

        self.assertEqual(changed, 0)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")

    def test_recovery_normalises_cutoff_timezone(self):
        job = self.repo.claim_next()
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T11:00:00Z", job["id"]),
        )
        self.conn.commit()

        # 13:00 at UTC+1 is 12:00 UTC.
        changed = self.repo.mark_stale_unknown(
            datetime(
                2026, 10, 23, 13,
                tzinfo=timezone(timedelta(hours=1)),
            )
        )
        self.conn.commit()

        self.assertEqual(changed, 1)
        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "unknown")

    def test_recovery_participates_in_callers_transaction(self):
        job = self.repo.claim_next()
        self.conn.execute(
            """
            UPDATE notification_outbox
            SET claimed_at = ?
            WHERE id = ?
            """,
            ("2026-10-23T11:00:00Z", job["id"]),
        )
        self.conn.commit()

        changed = self.repo.mark_stale_unknown(
            datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        )
        self.assertEqual(changed, 1)
        self.conn.rollback()

        stored = self.conn.execute(
            "SELECT status FROM notification_outbox WHERE id = ?",
            (job["id"],),
        ).fetchone()
        self.assertEqual(stored["status"], "processing")


if __name__ == "__main__":
    unittest.main()