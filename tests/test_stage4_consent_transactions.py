"""Consent and audit changes must succeed or fail together."""
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import test_avenra
import test_stage4_consent_changes

from avenra.repositories.consent_repository import ConsentRepository


class ConsentTransactionTests(unittest.TestCase):
    setUp = test_stage4_consent_changes.ConsentChangeTests.setUp
    tearDown = test_stage4_consent_changes.ConsentChangeTests.tearDown
    snapshot = test_stage4_consent_changes.ConsentChangeTests.snapshot
    save_location_consent = (
        test_stage4_consent_changes.ConsentChangeTests.save_location_consent
    )

    def test_audit_failure_does_not_commit_consent_change(self):
        before, before_count = self.snapshot()

        with patch(
            "avenra.repositories.audit_repository.AuditRepository.log",
            side_effect=sqlite3.OperationalError("private-audit-error"),
        ):
            response = self.save_location_consent(False)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(
            "private-audit-error",
            response.get_data(as_text=True),
        )

        after, after_count = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after_count, before_count)

    def test_failure_after_consent_write_rolls_back(self):
        before, before_count = self.snapshot()
        original = ConsentRepository.update_consent

        def write_then_fail(repository, *args, **kwargs):
            original(repository, *args, **kwargs)
            raise sqlite3.OperationalError("private-write-error")

        with patch.object(
            ConsentRepository,
            "update_consent",
            new=write_then_fail,
        ):
            response = self.save_location_consent(False)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(
            "private-write-error",
            response.get_data(as_text=True),
        )

        after, after_count = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after_count, before_count)

    def test_simultaneous_revocations_record_one_change(self):
        _, before_count = self.snapshot()
        start = Barrier(2)
        app = test_avenra.avenra_app.app
        headers = dict(self.survivor_headers)

        def revoke():
            with app.test_client() as client:
                start.wait(timeout=10)
                response = client.post(
                    "/api/consents",
                    headers=headers,
                    json={
                        "item": "location_sharing",
                        "active": False,
                    },
                )
                return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(revoke) for _ in range(2)]
            outcomes = [
                future.result(timeout=20)
                for future in futures
            ]

        for status, body in outcomes:
            self.assertEqual(status, 200)
            self.assertFalse(body["consent"]["active"])

        after, after_count = self.snapshot()
        self.assertIsNotNone(after["revoked_at"])
        self.assertEqual(after_count, before_count + 1)


if __name__ == "__main__":
    unittest.main()