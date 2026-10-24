"""Capture time is device-reported; receipt time belongs to the server."""
import unittest
from contextlib import closing
from unittest.mock import patch

import test_avenra as fixtures


class DiaryTimeTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def upload(self, **extra):
        payload = {
            "client_id": "diary-time-test",
            "note": "Fictional timestamp test",
        }
        payload.update(extra)
        return self.client.post(
            "/api/diary",
            json=payload,
            headers=self.survivor_headers,
        )

    def test_capture_is_normalised_and_receipt_is_server_assigned(self):
        with patch(
            "avenra.services.diary_service.utc_now",
            return_value="2026-10-24T15:00:00Z",
        ):
            response = self.upload(
                captured_at="2026-10-24T14:00:00+02:00",
                received_at="1999-01-01T00:00:00Z",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json["captured_at"], "2026-10-24T12:00:00Z"
        )
        self.assertEqual(
            response.json["received_at"], "2026-10-24T15:00:00Z"
        )

    def test_missing_capture_time_remains_unknown(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json["captured_at"])
        self.assertIsNotNone(response.json["received_at"])

    def test_legacy_input_alias_is_supported(self):
        response = self.upload(created_at="2026-10-24T12:00:00Z")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json["captured_at"], "2026-10-24T12:00:00Z"
        )

    def test_invalid_capture_time_is_rejected(self):
        for value in (None, True, 123, "", "bad", "2026-10-24T12:00:00"):
            with self.subTest(value=value):
                response = self.upload(captured_at=value)
                self.assertEqual(response.status_code, 400)

    def test_conflicting_aliases_are_rejected(self):
        response = self.upload(
            captured_at="2026-10-24T12:00:00Z",
            created_at="2026-10-24T13:00:00Z",
        )
        self.assertEqual(response.status_code, 400)

    def test_retry_preserves_original_receipt_time(self):
        with patch(
            "avenra.services.diary_service.utc_now",
            return_value="2026-10-24T15:00:00Z",
        ):
            first = self.upload(captured_at="2026-10-24T12:00:00Z")

        with patch(
            "avenra.services.diary_service.utc_now",
            return_value="2026-10-25T15:00:00Z",
        ):
            second = self.upload(captured_at="2026-10-24T14:00:00+02:00")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json, second.json)

    def test_retry_cannot_remove_capture_time(self):
        self.assertEqual(
            self.upload(captured_at="2026-10-24T12:00:00Z").status_code,
            201,
        )
        self.assertEqual(self.upload().status_code, 409)

    def test_migration_does_not_invent_historical_receipt_time(self):
        with closing(fixtures.db.connect()) as conn:
            owner = conn.execute(
                "SELECT id FROM users WHERE role = 'survivor' LIMIT 1"
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO diary_entries (
                    user_id, client_id, note, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    owner,
                    "historical-entry",
                    "Fictional old entry",
                    "2026-01-01T12:00:00Z",
                ),
            )
            conn.commit()

            fixtures.db.migrate(conn)
            conn.commit()

            row = conn.execute(
                """
                SELECT created_at, captured_at, received_at
                FROM diary_entries WHERE client_id = ?
                """,
                ("historical-entry",),
            ).fetchone()

        self.assertEqual(row["created_at"], "2026-01-01T12:00:00Z")
        self.assertIsNone(row["captured_at"])
        self.assertIsNone(row["received_at"])


if __name__ == "__main__":
    unittest.main()