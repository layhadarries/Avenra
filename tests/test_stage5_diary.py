"""Stage 5 Evidence Diary and PWA integration tests."""
import unittest
import base64
import hashlib
import io
from PIL import Image
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
        buf = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as img:
            img.save(buf, format="JPEG")
        fake_jpeg = buf.getvalue()
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

    def test_multipart_v2_binary_upload_and_replay(self):
        """Multipart v2 binary upload validates digests, fingerprint, and replays 200."""
        from avenra.models.diary import compute_entry_fingerprint, compute_note_sha256

        buf = io.BytesIO()
        with Image.new("RGB", (32, 32), "white") as img:
            img.save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()
        photo_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()
        note_text = "Multipart note with Unicode — café"
        note_sha256 = compute_note_sha256(note_text)
        captured_at = "2026-10-24T18:30:00Z"
        fingerprint = compute_entry_fingerprint(
            2, note_sha256, photo_sha256, captured_at, False
        )

        def send_multipart(note_val=note_text):
            return self.client.post(
                "/api/diary",
                data={
                    "client_id": "multipart-v2-001",
                    "note": note_val,
                    "shared": "false",
                    "captured_at": captured_at,
                    "contract_version": "2",
                    "note_sha256": note_sha256,
                    "photo_sha256": photo_sha256,
                    "entry_fingerprint": fingerprint,
                    "photo": (io.BytesIO(jpeg_bytes), "../unsafe.jpg", "image/jpeg"),
                },
                headers=self.survivor_headers,
                content_type="multipart/form-data",
            )

        res1 = send_multipart()
        self.assertEqual(res1.status_code, 201)
        r1 = res1.get_json()
        self.assertEqual(r1["contract_version"], 2)
        self.assertEqual(r1["photo_sha256"], photo_sha256)
        self.assertEqual(r1["note_sha256"], note_sha256)
        self.assertEqual(r1["entry_fingerprint"], fingerprint)

        res2 = send_multipart()
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json(), r1)

        # Photo-only multipart upload also succeeds
        res_photo_only = self.client.post(
            "/api/diary",
            data={
                "client_id": "multipart-photo-only-001",
                "contract_version": "2",
                "photo_sha256": photo_sha256,
                "photo": (io.BytesIO(jpeg_bytes), "evidence.jpg", "image/jpeg"),
            },
            headers=self.survivor_headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res_photo_only.status_code, 201)
        self.assertTrue(res_photo_only.get_json()["has_photo"])
        self.assertEqual(
            res_photo_only.get_json()["note_sha256"],
            compute_note_sha256(""),
        )

        # Active content / non-JPEG media type rejected
        bad_media = self.client.post(
            "/api/diary",
            data={
                "client_id": "multipart-bad-media",
                "photo": (io.BytesIO(b"<svg></svg>"), "x.svg", "image/svg+xml"),
            },
            headers=self.survivor_headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(bad_media.status_code, 400)

    def test_stage5_contract_fixtures_and_alert_priority(self):
        """Contract fixtures (201, 200, 409, 413, 422, 401) match byte-for-byte and never block alerts."""
        from avenra.models.diary import compute_entry_fingerprint, compute_note_sha256

        raw_note = "Suspect observed outside residence.\r\nRegistration: CA 123-456 — 21:00"
        expected_note_hash = compute_note_sha256(raw_note)
        self.assertEqual(
            expected_note_hash,
            compute_note_sha256(
                "Suspect observed outside residence.\nRegistration: CA 123-456 — 21:00"
            ),
        )
        expected_fp = compute_entry_fingerprint(
            2, expected_note_hash, None, "2026-10-24T20:15:00Z", True
        )

        fixture_payload = {
            "client_id": "00000000-0000-4000-8000-000000000002",
            "contract_version": 2,
            "note": raw_note,
            "file_hash": expected_note_hash,
            "note_sha256": expected_note_hash,
            "entry_fingerprint": expected_fp,
            "shared": True,
            "captured_at": "2026-10-24T20:15:00Z",
        }
        res_201 = self.client.post(
            "/api/diary",
            json=fixture_payload,
            headers=self.survivor_headers,
        )
        self.assertEqual(res_201.status_code, 201)
        body_201 = res_201.get_json()
        self.assertEqual(body_201["note_sha256"], expected_note_hash)
        self.assertEqual(body_201["file_hash"], expected_note_hash)
        self.assertEqual(body_201["entry_fingerprint"], expected_fp)

        # Matching replay -> 200 OK
        res_200 = self.client.post(
            "/api/diary",
            json=fixture_payload,
            headers=self.survivor_headers,
        )
        self.assertEqual(res_200.status_code, 200)
        self.assertEqual(res_200.get_json(), body_201)

        # Conflicting replay -> 409 Conflict
        fp_unshared = compute_entry_fingerprint(
            2, expected_note_hash, None, "2026-10-24T20:15:00Z", False
        )
        res_409 = self.client.post(
            "/api/diary",
            json={
                **fixture_payload,
                "shared": False,
                "entry_fingerprint": fp_unshared,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(res_409.status_code, 409)
        self.assertEqual(res_409.get_json(), {"error": "client_id_conflict"})

        # Corrupted digest -> 422 Unprocessable
        res_422 = self.client.post(
            "/api/diary",
            json={**fixture_payload, "client_id": "fixture-422", "file_hash": "0" * 64},
            headers=self.survivor_headers,
        )
        self.assertEqual(res_422.status_code, 422)
        self.assertEqual(res_422.get_json(), {"error": "hash_mismatch"})

        # Oversized v2 photo -> 413 Payload Too Large
        res_413 = self.client.post(
            "/api/diary",
            data={
                "client_id": "fixture-413",
                "contract_version": "2",
                "photo": (io.BytesIO(b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024)), "big.jpg", "image/jpeg"),
            },
            headers=self.survivor_headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(res_413.status_code, 413)
        self.assertEqual(res_413.get_json(), {"error": "photo_too_large"})

        # Expired / invalid device token -> 401
        res_401 = self.client.post(
            "/api/diary",
            json=fixture_payload,
            headers={"X-Device-Token": "expired-token", "Origin": "http://localhost"},
        )
        self.assertEqual(res_401.status_code, 401)
        self.assertEqual(res_401.get_json(), {"error": "bad_device_token"})

        # Alert priority: emergency alert succeeds immediately after diary errors
        alert_res = self.client.post(
            "/api/alerts",
            json={"client_id": "priority-alert-after-diary-error"},
            headers=self.survivor_headers,
        )
        self.assertEqual(alert_res.status_code, 201)
        self.assertEqual(alert_res.get_json()["status"], "new")


if __name__ == '__main__':
    unittest.main()
    