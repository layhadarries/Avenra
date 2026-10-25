"""Queued writes must match the authenticated device account."""
import unittest

import test_avenra as fixtures
import test_hosted_pwa_contract as pairing


class QueueOwnershipTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    invite = pairing.HostedPWAContractTests.invite
    enroll = pairing.HostedPWAContractTests.enroll

    def paired_phone(self):
        phone, _ = self.enroll(self.invite())
        owner = phone.get("/api/device").get_json()["account_id"]
        return phone, owner

    def submit(self, phone, path, client_id, owner=None):
        headers = {"Origin": "http://localhost"}
        if owner is not None:
            headers["X-Queue-Owner"] = str(owner)

        payload = {"client_id": client_id}
        if path == "/api/diary":
            payload.update(
                note="Fictional queue ownership test",
                shared=False,
            )

        return phone.post(path, json=payload, headers=headers)

    def test_matching_owner_can_submit_alert(self):
        phone, owner = self.paired_phone()
        response = self.submit(
            phone, "/api/alerts", "matching-owner", owner
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_another_accounts_owner_is_rejected(self):
        first, first_owner = self.paired_phone()
        second, second_owner = self.paired_phone()
        self.assertNotEqual(first_owner, second_owner)

        for path in ("/api/alerts", "/api/diary"):
            with self.subTest(path=path):
                response = self.submit(
                    second, path, "foreign-owner", first_owner
                )
                self.assertEqual(response.status_code, 409)

    def test_unbound_queued_writes_are_rejected(self):
        phone, _ = self.paired_phone()

        for path in ("/api/alerts", "/api/diary"):
            with self.subTest(path=path):
                response = self.submit(
                    phone, path, "missing-owner"
                )
                self.assertEqual(response.status_code, 409)

    def test_malformed_owner_is_rejected(self):
        phone, _ = self.paired_phone()

        for owner in ("", "undefined", "-1", "1.0", "true"):
            with self.subTest(owner=owner):
                response = self.submit(
                    phone, "/api/alerts", "malformed-owner", owner
                )
                self.assertEqual(response.status_code, 409)

    def test_owner_header_is_not_authentication(self):
        anonymous = fixtures.avenra_app.app.test_client()
        response = self.submit(
            anonymous, "/api/alerts", "no-device-cookie", 1
        )
        self.assertEqual(response.status_code, 401)

    def test_rejected_write_creates_no_record(self):
        phone, owner = self.paired_phone()
        client_id = "must-not-be-stored"

        response = self.submit(
            phone, "/api/alerts", client_id, owner + 100000
        )
        self.assertEqual(response.status_code, 409)

        conn = fixtures.db.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE client_id=?",
                (client_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(count, 0)