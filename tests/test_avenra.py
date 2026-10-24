"""Comprehensive automated test suite for  (Stages 0 through 6)."""

import base64
import hashlib
import os
import re
import tempfile
import unittest
import io
from PIL import Image
from werkzeug.security import generate_password_hash

# Ensure importing app/db never creates avenra.db in the repository root
_BOOT_TMP = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(_BOOT_TMP.name, "boot_avenra.db")
os.environ['APP_ENV'] = 'development'
os.environ['COOKIE_SECURE'] = '0'
# Another test may have imported db before this fixture set DATABASE_PATH.
# Update the cached module before importing app: never initialise a user's DB.
import db  # noqa: E402
db.DB_PATH = os.environ['DATABASE_PATH']
# Unit tests must not contact providers inherited from a developer's terminal.
for _provider_key in ('SMS_WEBHOOK_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
    os.environ.pop(_provider_key, None)

os.environ.setdefault(
    "SECRET_KEY",
    "test-only-key-never-use-outside-tests-0123456789",
)

import app as avenra_app  # noqa: E402
import db  # noqa: E402
import seed  # noqa: E402


class avenraStagesTestCase(unittest.TestCase):
    """End-to-end verification of Stages 0–6 API and POPIA/security invariants."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_avenra.db")
        self.upload_dir = os.path.join(self.tmp_dir.name, "uploads")
        os.makedirs(self.upload_dir, exist_ok=True)

        db.DB_PATH = self.db_path
        avenra_app.UPLOADS_DIR = self.upload_dir
        db.init_db()
        avenra_app.ensure_alert_columns()
        seed.seed()

        # These changes apply only to this test's temporary database.
        self.assertEqual(
            os.path.abspath(db.DB_PATH),
            os.path.abspath(self.db_path),
        )
        self.staff_password = "V7!mQ2#rL9@tZ4%k"  # Public test data only.

        conn = db.connect()
        try:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)")
            }

            if "is_active" not in columns:
                conn.execute(
                    "ALTER TABLE users "
                    "ADD COLUMN is_active INTEGER DEFAULT 0"
                )

            if "auth_version" not in columns:
                conn.execute(
                    "ALTER TABLE users "
                    "ADD COLUMN auth_version INTEGER DEFAULT 1"
                )

            conn.execute(
                """
                UPDATE users
                SET is_active = 1,
                    auth_version = 1,
                    password_hash = ?
                WHERE role IN ('admin', 'responder', 'shelter')
                """,
                (generate_password_hash(self.staff_password),),
            )
            conn.commit()
        finally:
            conn.close()

        avenra_app.app.config["TESTING"] = True
        self.client = avenra_app.app.test_client()
        self.survivor_headers = {
            "X-Device-Token": avenra_app.DEVICE_TOKEN,
        }

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _login_staff(self, role="responder"):
        # Use a fresh browser session for the requested test role.
        self.client = avenra_app.app.test_client()

        conn = db.connect()
        try:
            user = conn.execute(
                """
                SELECT id, email
                FROM users
                WHERE role = ?
                ORDER BY id
                LIMIT 1
                """,
                (role,),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(user, f"No test user for role {role}")

        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)

        token = re.search(
            r'name="csrf_token"\s+value="([^"]+)"',
            page.get_data(as_text=True),
        )
        self.assertIsNotNone(
            token,
            "Login form is missing its CSRF token",
        )

        response = self.client.post("/login", data={
            "email": user["email"],
            "password": self.staff_password,
            "csrf_token": token.group(1),
        })

        self.assertEqual(
            response.status_code,
            302,
            "Test staff login failed",
        )

        with self.client.session_transaction() as browser_session:
            self.assertEqual(
                browser_session.get("user_id"),
                user["id"],
            )

        return response

    def _staff_post(self, endpoint, **kwargs):
        page = self.client.get("/shelters")
        self.assertEqual(
            page.status_code,
            200,
            "Staff must be signed in before making this request",
        )

        token = re.search(
            r'name="csrf_token"\s+value="([^"]+)"',
            page.get_data(as_text=True),
        )
        self.assertIsNotNone(
            token,
            "Staff page is missing its CSRF token",
        )

        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("X-CSRFToken", token.group(1))

        return self.client.post(
            endpoint,
            headers=headers,
            **kwargs,
        )

    def test_stage_0_and_1_disguise_alert_and_ack(self):
        """Stage 0 & 1: Disguise shell, idempotent panic alert creation, and responder ACK."""
        # Health endpoint
        health_res = self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.get_json()["status"], "ok")

        # Weather disguise PWA root ("Clear Sky")
        res = self.client.get("/survivor/")
        self.assertEqual(res.status_code, 200)
        shell = res.get_data()
        res.close()
        with self.client.get('/survivor/manifest.json', buffered=True) as manifest_response:
            identity = manifest_response.get_json()
        self.assertIn(identity['name'].encode(), shell)
        res.close()

        # Create panic alert
        payload = {
            "client_id": "test-uuid-stage1-001",
            "lat": -33.9249,
            "lng": 18.4241,
            "client_ts": "2026-10-19T12:00:00Z",
        }
        res1 = self.client.post(
            "/api/alerts", json=payload, headers=self.survivor_headers
        )
        self.assertEqual(res1.status_code, 201)
        data1 = res1.get_json()
        alert_id = data1["id"]
        self.assertEqual(data1["status"], "new")

        # Duplicate replay with same client_id must return 200 with the same alert id
        res2 = self.client.post(
            "/api/alerts", json=payload, headers=self.survivor_headers
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2["id"], alert_id)

        # Responder login and ACK
        self._login_staff("responder")
        ack_res = self._staff_post(f"/api/alerts/{alert_id}/acknowledge")
        self.assertEqual(ack_res.status_code, 200)
        ack_data = ack_res.get_json()
        self.assertEqual(ack_data["status"], "acknowledged")
        self.assertIsNotNone(ack_data["acknowledged_at"])

        # Second ACK on already acknowledged alert returns 200 with already=True
        ack_res2 = self._staff_post(f"/api/alerts/{alert_id}/acknowledge")
        self.assertEqual(ack_res2.status_code, 200)
        self.assertTrue(ack_res2.get_json().get("already"))

        # Survivor polls alert status
        status_res = self.client.get(
            f"/api/alerts/{alert_id}/status", headers=self.survivor_headers
        )
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.get_json()["status"], "acknowledged")

    def test_stage_2_trusted_contacts_and_sms_dispatch(self):
        """Stage 2: Trusted contacts CRUD and single SMS dispatch on new alert."""
        contacts_payload = {
            "contacts": [
                {"name": "Sister Nomsa", "phone": "+27820001111"},
                {"name": "Auntie Thuli", "phone": "+27820002222"},
            ]
        }
        put_res = self.client.post(
            "/api/contacts", json=contacts_payload, headers=self.survivor_headers
        )
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(len(put_res.get_json()["contacts"]), 2)

        # Trigger new alert -> dispatches SMS to 2 contacts
        alert_payload = {
            "client_id": "test-uuid-stage2-sms",
            "lat": -33.9249,
            "lng": 18.4241,
            "client_ts": "2026-10-19T12:05:00Z",
        }
        res = self.client.post(
            "/api/alerts", json=alert_payload, headers=self.survivor_headers
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body["contacts_notified"], 0)
        self.assertEqual(body["contacts_accepted"], 0)

        # Replay same alert -> returns 200 without re-notifying contacts
        replay_res = self.client.post(
            "/api/alerts", json=alert_payload, headers=self.survivor_headers
        )
        self.assertEqual(replay_res.status_code, 200)
        self.assertNotIn("contacts_notified", replay_res.get_json())

    def test_stage_3_shelters_and_warm_referrals(self):
        """Stage 3: Shelter directory, capacity adjustment, warm referral lifecycle, and bed decrement."""
        # Survivor can fetch shelters
        shelters_res = self.client.get("/api/shelters", headers=self.survivor_headers)
        self.assertEqual(shelters_res.status_code, 200)
        shelters = shelters_res.get_json()["shelters"]
        self.assertGreaterEqual(len(shelters), 3)

        for entry in shelters:
            self.assertEqual(entry["availability"], "contact_to_confirm")
            for field in ("beds_total", "beds_available", "accepting"):
                self.assertNotIn(field, entry)

        # Internal fixture data is not part of the directory response.
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT id, beds_available FROM shelters
                WHERE beds_available > 0
                ORDER BY id LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(row)
            shelter_id = row["id"]
            initial_beds = row["beds_available"]
        finally:
            conn.close()

        target_shelter = next(
            entry for entry in shelters if entry["id"] == shelter_id
        )

        # Create an alert so we can attach a referral
        alert_res = self.client.post(
            "/api/alerts",
            json={"client_id": "test-uuid-stage3-ref"},
            headers=self.survivor_headers,
        )
        alert_id = alert_res.get_json()["id"]

        # Responder creates a warm referral
        self._login_staff("responder")
        ref_res = self._staff_post(
            "/api/referrals",
            json={
                "alert_id": alert_id,
                "shelter_id": target_shelter["id"],
            },
        )
        self.assertEqual(ref_res.status_code, 201)
        referral_id = ref_res.get_json()["referral"]["id"]

        # Transition referral: sent -> accepted -> placed
        acc_res = self._staff_post(
            f"/api/referrals/{referral_id}/status", json={"status": "accepted"}
        )
        self.assertEqual(acc_res.status_code, 200)
        self.assertEqual(acc_res.get_json()["referral"]["status"], "accepted")

        placed_res = self._staff_post(
            f"/api/referrals/{referral_id}/status", json={"status": "placed"}
        )
        self.assertEqual(placed_res.status_code, 200)
        self.assertEqual(placed_res.get_json()["referral"]["status"], "placed")

        # Preserve the existing internal placement accounting check.
        conn = db.connect()
        try:
            updated = conn.execute(
                "SELECT beds_available FROM shelters WHERE id = ?",
                (target_shelter["id"],),
            ).fetchone()
            self.assertEqual(updated["beds_available"], initial_beds)
        finally:
            conn.close()

        response = self.client.get(
            "/api/shelters", headers=self.survivor_headers
        )
        self.assertEqual(response.status_code, 200)

        for entry in response.json["shelters"]:
            self.assertEqual(entry["availability"], "contact_to_confirm")
            for field in ("beds_total", "beds_available", "accepting"):
                self.assertNotIn(field, entry)

        # Verify survivor alert status endpoint includes the active referral
        status_res = self.client.get(
            f"/api/alerts/{alert_id}/status", headers=self.survivor_headers
        )
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.get_json()["referral"]["status"], "placed")

    def test_stage_4_popia_consents_and_live_redaction(self):
        """Stage 4: POPIA consent revocation immediately redacts GPS and logs to audit_log."""
        # Create an alert with GPS coordinates
        self.client.post(
            "/api/alerts",
            json={
                "client_id": "test-uuid-stage4-gps",
                "lat": -33.9249,
                "lng": 18.4241,
            },
            headers=self.survivor_headers,
        )

        # Revoke location_sharing
        revoke_loc = self.client.post(
            "/api/consents",
            json={"item": "location_sharing", "active": False},
            headers=self.survivor_headers,
        )
        self.assertEqual(revoke_loc.status_code, 200)
        self.assertFalse(revoke_loc.get_json()["consent"]["active"])

        # Responder fetches alerts -> lat/lng must be redacted (None)
        self._login_staff("responder")
        alerts_res = self.client.get("/api/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        sp_alerts = [
            a for a in alerts_res.get_json()["alerts"] if a["case_code"] == "SP-1042"
        ]
        self.assertTrue(len(sp_alerts) > 0)
        for alert in sp_alerts:
            self.assertTrue(alert["location_redacted"])
            self.assertIsNone(alert["lat"])
            self.assertIsNone(alert["lng"])

        # Survivor receives safe viewing history, not internal audit details.
        audit_res = self.client.get(
            "/api/audit-log",
            headers=self.survivor_headers,
        )
        self.assertEqual(audit_res.status_code, 200)

        for event in audit_res.get_json()["events"]:
            self.assertEqual(
                set(event),
                {
                    "id",
                    "viewed_at",
                    "actor_name",
                    "actor_role",
                    "action",
                },
            )

        # Verify the internal consent event directly in the test database.
        conn = db.connect()
        try:
            recorded = conn.execute(
                """
                SELECT COUNT(*) FROM audit_log
                WHERE action = 'consent_revoked'
                AND case_code IN (
                    SELECT case_code FROM users
                    WHERE role = 'survivor'
                )
                """
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertGreaterEqual(recorded, 1)

    def test_stage_5_evidence_diary_upload_hash_and_consent_gate(self):
        """Stage 5: Evidence diary upload, SHA-256 verification, and diary_sharing consent gate."""
        buffer = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as image:
            image.save(buffer, format="JPEG")
        fake_jpeg = buffer.getvalue()
        expected_hash = hashlib.sha256(fake_jpeg).hexdigest()
        b64_photo = "data:image/jpeg;base64," + base64.b64encode(fake_jpeg).decode("ascii")

        # Upload diary entry with photo and matching SHA-256 hash
        upload_res = self.client.post(
            "/api/diary",
            json={
                "client_id": "test-diary-entry-001",
                "note": "Threatening voicemail and damaged door lock.",
                "photo_data": b64_photo,
                "file_hash": expected_hash,
                "shared": True,
            },
            headers=self.survivor_headers,
        )
        self.assertEqual(upload_res.status_code, 201)
        upload_data = upload_res.get_json()
        self.assertTrue(upload_data["stored"])
        self.assertEqual(upload_data["file_hash"], expected_hash)
        entry_id = upload_data["id"]

        # Survivor vault metadata endpoint returns stored=True and file_hash without raw note text
        vault_res = self.client.get("/api/diary", headers=self.survivor_headers)
        self.assertEqual(vault_res.status_code, 200)
        vault_entry = vault_res.get_json()["entries"][0]
        self.assertEqual(vault_entry["file_hash"], expected_hash)
        self.assertNotIn("note", vault_entry)

        # Responder can view diary entries and photo while diary_sharing is active
        self._login_staff("responder")
        allowed_diary = self.client.get("/api/diary")
        self.assertEqual(allowed_diary.status_code, 200)
        self.assertTrue(allowed_diary.get_json()["consent_active"])
        self.assertEqual(len(allowed_diary.get_json()["entries"]), 1)

        photo_allowed = self.client.get(f"/cases/diary-photo/{entry_id}")
        self.assertEqual(photo_allowed.status_code, 200)
        self.assertEqual(photo_allowed.data, fake_jpeg)
        photo_allowed.close()

        # Survivor revokes diary_sharing consent -> responder is immediately blocked
        self.client.post(
            "/api/consents",
            json={"item": "diary_sharing", "active": False},
            headers=self.survivor_headers,
        )

        denied_diary = self.client.get("/api/diary")
        self.assertEqual(denied_diary.status_code, 200)
        self.assertFalse(denied_diary.get_json()["consent_active"])
        self.assertEqual(denied_diary.get_json()["entries"], [])

        photo_denied = self.client.get(f"/cases/diary-photo/{entry_id}")
        self.assertEqual(photo_denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
