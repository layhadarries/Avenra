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

    def test_orphan_reconciliation_quarantines_unreferenced_files(self):
        from avenra.services.diary_service import DiaryService

        self.assertEqual(self.upload().status_code, 201)
        committed_file = os.path.basename(self.photo_path())
        orphan_file = "diary_00000000000000000000000000000000.jpg"
        with open(os.path.join(self.upload_dir, orphan_file), "wb") as fh:
            fh.write(b"unreferenced-orphan")

        with self.client.application.app_context():
            reconciled = DiaryService().reconcile_orphans(self.upload_dir)

        self.assertEqual(reconciled, [orphan_file])
        self.assertTrue(
            os.path.exists(os.path.join(self.upload_dir, committed_file))
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.upload_dir, orphan_file))
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.upload_dir, ".quarantine", orphan_file)
            )
        )

    def test_private_object_storage_verifies_checksum_and_reconciles_orphans(self):
        import hashlib
        from avenra.services.diary_service import PrivateObjectDiaryStorage

        class FakeObjectClient:
            def __init__(self):
                self.objects = {}
                self.corrupt_next_read = False
                self.fail_delete = False

            def put_object(self, bucket, key, body, content_type, sha256):
                self.objects[(bucket, key)] = (
                    b"tampered" if self.corrupt_next_read else body
                )

            def get_object(self, bucket, key, max_bytes):
                if (bucket, key) not in self.objects:
                    raise OSError("missing")
                return self.objects[(bucket, key)][:max_bytes]

            def delete_object(self, bucket, key):
                if self.fail_delete:
                    raise OSError("delete_denied")
                self.objects.pop((bucket, key), None)

            def list_objects(self, bucket, prefix=""):
                return [
                    k for (b, k) in self.objects if b == bucket and k.startswith(prefix)
                ]

        client = FakeObjectClient()
        store = PrivateObjectDiaryStorage(client, bucket="private-diary")
        raw = b"valid-photo-bytes"
        digest = hashlib.sha256(raw).hexdigest()

        store.put_object("diary_a1.jpg", raw, digest)
        self.assertTrue(store.verify_object("diary_a1.jpg", digest))

        # Checksum mismatch during put_object cleans up the bad object and raises OSError
        client.corrupt_next_read = True
        with self.assertRaises(OSError):
            store.put_object("diary_bad.jpg", raw, digest)
        self.assertNotIn(("private-diary", "diary_bad.jpg"), client.objects)
        client.corrupt_next_read = False

        # Interrupted cleanup records quarantine and reconcile_orphans removes it
        store.put_object("diary_orphan.jpg", raw, digest)
        client.fail_delete = True
        store.delete_object("diary_orphan.jpg")
        self.assertIn("diary_orphan.jpg", store.quarantined)

        client.fail_delete = False
        reconciled = store.reconcile_orphans({"diary_a1.jpg"})
        self.assertEqual(reconciled, ["diary_orphan.jpg"])
        self.assertEqual(store.quarantined, [])
        self.assertIn(("private-diary", "diary_a1.jpg"), client.objects)
        self.assertNotIn(("private-diary", "diary_orphan.jpg"), client.objects)

    def test_disk_full_and_permission_denied_leave_no_record_or_photo(self):
        import errno

        for err_code in (errno.ENOSPC, errno.EACCES):
            with self.subTest(err_code=err_code):
                before = self.counts()
                files_before = set(os.listdir(self.upload_dir))
                with patch(
                    "avenra.services.diary_service.open",
                    side_effect=OSError(err_code, "simulated storage error"),
                ):
                    response = self.upload()
                self.assert_failed_cleanly(response, before, files_before)

    def test_concurrent_integrity_error_recovers_existing_receipt(self):
        first = self.upload()
        self.assertEqual(first.status_code, 201)
        before = self.counts()
        files_before = set(os.listdir(self.upload_dir))

        call_count = {"n": 0}
        original_get = DiaryRepository.get_by_client_id

        def race_get_by_client_id(repo, client_id):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return None
            return original_get(repo, client_id)

        with patch.object(
            DiaryRepository, "get_by_client_id", race_get_by_client_id
        ):
            response = self.upload()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), first.get_json())
        self.assertEqual(self.counts(), before)
        self.assertEqual(set(os.listdir(self.upload_dir)), files_before)

    def test_concurrent_identical_uploads_produce_single_entry(self):
        import threading

        results = []
        barrier = threading.Barrier(2)
        payload = self.payload()
        payload["client_id"] = "concurrent-race-entry"

        def worker():
            client = self.client.application.test_client()
            barrier.wait(timeout=5)
            resp = client.post(
                "/api/diary",
                json=payload,
                headers=self.survivor_headers,
            )
            results.append((resp.status_code, resp.get_json()))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = sorted(s for s, _ in results)
        self.assertEqual(statuses, [200, 201])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(self.counts(), (1, 1))
        jpg_files = [
            f for f in os.listdir(self.upload_dir) if f.endswith(".jpg")
        ]
        self.assertEqual(len(jpg_files), 1)

    def test_additive_migration_preserves_stage4_records_and_owner_index(self):
        with closing(fixtures.db.connect()) as conn:
            survivor_id = conn.execute(
                "SELECT id FROM users WHERE role = 'survivor' LIMIT 1"
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO diary_entries
                   (user_id, note, file_hash, shared, client_id, created_at)
                   VALUES (?, ?, ?, 0, ?, '2026-10-20T10:00:00Z')""",
                (survivor_id, "Stage 4 legacy note", "a" * 64, "legacy-s4-1"),
            )
            conn.commit()

            before_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            before_diary = conn.execute(
                "SELECT COUNT(*) FROM diary_entries"
            ).fetchone()[0]

            fixtures.db.migrate(conn)
            conn.commit()
            fixtures.db.migrate(conn)
            conn.commit()

            after_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            after_diary = conn.execute(
                "SELECT COUNT(*) FROM diary_entries"
            ).fetchone()[0]
            self.assertEqual(before_users, after_users)
            self.assertEqual(before_diary, after_diary)

            indexes = {
                r["name"]
                for r in conn.execute("PRAGMA index_list(diary_entries)").fetchall()
            }
            self.assertIn("uq_diary_user_client", indexes)
            versions = {
                r["version"]
                for r in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            self.assertIn(4, versions)

            repo = DiaryRepository(conn)
            found = repo.get_by_owner_and_client_id(survivor_id, "legacy-s4-1")
            self.assertIsNotNone(found)
            self.assertEqual(found.note, "Stage 4 legacy note")
            self.assertIsNone(
                repo.get_by_owner_and_client_id(survivor_id + 999, "legacy-s4-1")
            )


if __name__ == "__main__":
    unittest.main()