"""Diary validation and replay checks without database or network access."""
import base64
import hashlib
import tempfile
import unittest
import io
from PIL import Image
from types import SimpleNamespace
from unittest.mock import Mock

from avenra.models.diary import DiaryEntry
from avenra.services.diary_service import DiaryService


class DiaryRetryTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.audit = Mock()
        self.user = SimpleNamespace(id=10, case_code="TEST-10")
        self.entry = DiaryEntry(
            id=1,
            user_id=10,
            client_id="entry-one",
            note="Original note",
            file_hash=hashlib.sha256(b"Original note").hexdigest(),
            shared=0,
            created_at="2026-10-24T12:00:00Z",
        )
        self.repo.get_by_client_id.return_value = self.entry
        self.service = DiaryService(
            diary_repo=self.repo,
            audit_repo=self.audit,
            consent_repo=Mock(),
            user_repo=Mock(),
        )
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def submit(self, data):
        result = self.service.create_entry(
            self.user, data, self.directory.name
        )
        self.repo.create.assert_not_called()
        self.audit.log.assert_not_called()
        return result

    def test_identical_retry_returns_existing_receipt(self):
        body, status = self.submit({
            "client_id": "entry-one",
            "note": "Original note",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], 1)

    def test_changed_note_is_rejected(self):
        _, status = self.submit({
            "client_id": "entry-one",
            "note": "Different note",
        })
        self.assertEqual(status, 409)
        self.assertEqual(self.entry.note, "Original note")

    def test_changed_sharing_is_rejected(self):
        _, status = self.submit({
            "client_id": "entry-one",
            "note": "Original note",
            "shared": True,
        })
        self.assertEqual(status, 409)

    def test_other_owner_cannot_recover_receipt(self):
        self.user.id = 11
        body, status = self.submit({
            "client_id": "entry-one",
            "note": "Original note",
        })
        self.assertEqual(status, 409)
        self.assertNotIn("id", body)

    def test_changed_capture_time_is_rejected(self):
        _, status = self.submit({
            "client_id": "entry-one",
            "note": "Original note",
            "created_at": "2026-10-24T13:00:00Z",
        })
        self.assertEqual(status, 409)

    def test_invalid_input_is_not_coerced(self):
        payloads = [
            [],
            {"client_id": 123, "note": "Original note"},
            {"client_id": "entry-one", "note": 123},
            {"client_id": "entry-one", "note": None},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                _, status = self.submit(payload)
                self.assertEqual(status, 400)

    def test_bad_hash_on_retry_is_rejected(self):
        _, status = self.submit({
            "client_id": "entry-one",
            "note": "Original note",
            "file_hash": "0" * 64,
        })
        self.assertEqual(status, 422)

    def test_photo_digest_cannot_hide_changed_note(self):
        buffer = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as image:
            image.save(buffer,format="JPEG")
        photo = buffer.getvalue()
        self.entry.photo_path = "existing.jpg"
        self.entry.file_hash = hashlib.sha256(photo).hexdigest()

        _, status = self.submit({
            "client_id": "entry-one",
            "note": "Changed accompanying note",
            "photo_data": (
                "data:image/jpeg;base64,"
                + base64.b64encode(photo).decode("ascii")
            ),
        })
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()