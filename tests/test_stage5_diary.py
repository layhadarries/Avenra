"""Stage 5 Evidence Diary and PWA integration tests."""
import unittest
import base64
import hashlib
import json
import test_avenra


class Stage5DiaryIntegrationTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def test_diary_shell_and_script_available(self):
        """Diary HTML shell and client script are served with Clear Sky identity."""
        with self.client.get('/survivor/diary.html') as res_html:
            self.assertEqual(res_html.status_code, 200)
            html = res_html.get_data(as_text=True)
            self.assertIn('<title>Clear Sky</title>', html)
            self.assertIn('Incident Diary', html)
            self.assertIn('id="diary-note"', html)
            self.assertIn('id="diary-photo-input"', html)
            self.assertIn('id="diary-share-toggle"', html)
            self.assertIn('id="diary-save-btn"', html)
            self.assertIn('id="quick-exit-btn"', html)

        with self.client.get('/survivor/diary.js') as res_js:
            self.assertEqual(res_js.status_code, 200)
            js = res_js.get_data(as_text=True)
            self.assertIn('clear-sky-diary-queue', js)
            self.assertIn('computeSha256', js)
            self.assertIn('quickExit', js)

    def test_navigation_includes_diary_link(self):
        """Index and help shells include navigation to diary.html."""
        with self.client.get('/survivor/index.html') as res_index:
            self.assertEqual(res_index.status_code, 200)
            index_html = res_index.get_data(as_text=True)
            self.assertIn('/survivor/diary.html', index_html)

        with self.client.get('/survivor/help.html') as res_help:
            self.assertEqual(res_help.status_code, 200)
            help_html = res_help.get_data(as_text=True)
            self.assertIn('/survivor/diary.html', help_html)

    def test_diary_entry_note_only_upload_and_idempotency(self):
        """Note-only diary entry upload returns 201; replaying client_id returns 200."""
        note_text = "Suspicious vehicle parked outside driveway at 22:30."
        note_hash = hashlib.sha256(note_text.encode('utf-8')).hexdigest()
        client_id = "test-diary-note-001"

        res = self.client.post(
            '/api/diary',
            json={
                "client_id": client_id,
                "note": note_text,
                "file_hash": note_hash,
                "shared": False,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["stored"])
        self.assertEqual(data["client_id"], client_id)
        self.assertEqual(data["file_hash"], note_hash)
        self.assertFalse(data["shared"])
        self.assertFalse(data["has_photo"])
        entry_id = data["id"]

        # Replay with same client_id returns 200 with matching receipt
        replay_res = self.client.post(
            '/api/diary',
            json={
                "client_id": client_id,
                "note": note_text,
                "file_hash": note_hash,
                "shared": False,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(replay_res.status_code, 200)
        replay_data = replay_res.get_json()
        self.assertEqual(replay_data["id"], entry_id)
        self.assertEqual(replay_data["file_hash"], note_hash)

    def test_diary_entry_photo_upload_and_consent_gate(self):
        """Photo upload verification and dual-gate consent restriction for staff."""
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        photo_hash = hashlib.sha256(fake_jpeg).hexdigest()
        b64_photo = "data:image/jpeg;base64," + base64.b64encode(fake_jpeg).decode("ascii")
        client_id = "test-diary-photo-001"

        res = self.client.post(
            '/api/diary',
            json={
                "client_id": client_id,
                "note": "Photo of broken lock latch.",
                "photo_data": b64_photo,
                "file_hash": photo_hash,
                "shared": True,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["stored"])
        self.assertTrue(data["has_photo"])
        entry_id = data["id"]

        # Staff with active consent can view photo
        self._login_staff("responder")
        photo_res = self.client.get(f'/cases/diary-photo/{entry_id}')
        self.assertEqual(photo_res.status_code, 200)
        self.assertEqual(photo_res.data, fake_jpeg)
        photo_res.close()


if __name__ == '__main__':
    unittest.main()
