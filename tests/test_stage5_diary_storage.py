"""Diary storage failures must not produce successful receipts."""
import base64
import io
import os
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from PIL import Image
import test_avenra as fixtures
from avenra.repositories.diary_repository import DiaryRepository


class DiaryStorageTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def payload(self):
        buffer = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as image:
            image.save(buffer, format="JPEG")
        return {
            "client_id": "storage-test-entry",
            "note": "Fictional storage test",
            "photo_data": (
                "data:image/jpeg;base64,"
                + base64.b64encode(buffer.getvalue()).decode("ascii")
            ),
        }

    def upload(self):
        return self.client.post(
            "/api/diary",
            json=self.payload(),
            headers=self.survivor_headers,
        )

    def counts(self):
        with closing(fixtures.db.connect()) as conn:
            return (
                conn.execute(
                    "SELECT COUNT(*) FROM diary_entries"
                ).fetchone()[0],
                conn.execute(
                    """SELECT COUNT(*) FROM audit_log
                       WHERE action = 'diary_entry_uploaded'"""
                ).fetchone()[0],
            )

    def photo_path(self):
        with closing(fixtures.db.connect()) as conn:
            row = conn.execute(
                "SELECT photo_path FROM diary_entries WHERE client_id = ?",
                ("storage-test-entry",),
            ).fetchone()
        return os.path.join(self.upload_dir, row["photo_path"])

    def assert_failed_cleanly(self, response, before, files_before):
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"error": "diary_storage_unavailable"},
        )
        self.assertEqual(self.counts(), before)
        self.assertEqual(set(os.listdir(self.upload_dir)), files_before)

    def test_file_flush_failure_leaves_no_record_or_photo(self):
        before = self.counts()
        files_before = set(os.listdir(self.upload_dir))
        with patch(
            "avenra.services.diary_service.os.fsync",
            side_effect=OSError("private-storage-error"),
        ):
            response = self.upload()
        self.assert_failed_cleanly(response, before, files_before)

    def test_audit_failure_rolls_back_entry_and_removes_photo(self):
        before = self.counts()
        files_before = set(os.listdir(self.upload_dir))
        with patch(
            "avenra.repositories.audit_repository.AuditRepository.log",
            side_effect=sqlite3.OperationalError("private-audit-error"),
        ):
            response = self.upload()
        self.assert_failed_cleanly(response, before, files_before)

    def test_failure_after_database_insert_rolls_back(self):
        before = self.counts()
        files_before = set(os.listdir(self.upload_dir))
        original = DiaryRepository.create

        def insert_then_fail(repo, **kwargs):
            original(repo, **kwargs)
            raise sqlite3.OperationalError("private-write-error")

        with patch.object(DiaryRepository, "create", insert_then_fail):
            response = self.upload()
        self.assert_failed_cleanly(response, before, files_before)

    def test_missing_photo_cannot_receive_successful_retry(self):
        self.assertEqual(self.upload().status_code, 201)
        before = self.counts()
        os.unlink(self.photo_path())

        response = self.upload()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.counts(), before)

    def test_corrupted_photo_cannot_receive_successful_retry(self):
        self.assertEqual(self.upload().status_code, 201)
        before = self.counts()
        with open(self.photo_path(), "wb") as fh:
            fh.write(b"corrupted")

        response = self.upload()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.counts(), before)

    def test_successful_retry_does_not_duplicate_entry_or_audit(self):
        first = self.upload()
        self.assertEqual(first.status_code, 201)
        before = self.counts()
        files_before = set(os.listdir(self.upload_dir))

        second = self.upload()

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json(), first.get_json())
        self.assertEqual(self.counts(), before)
        self.assertEqual(set(os.listdir(self.upload_dir)), files_before)


if __name__ == "__main__":
    unittest.main()