"""Cross-account object authorization regressions.

A grant for one case must never authorise reads or actions on another case.
Administrators may read every case by policy, while destructive retention work
still requires an explicit assignment. Every fixture here is fictional.
"""
import base64
import io
import unittest
from contextlib import closing
from unittest.mock import patch

from PIL import Image

import test_avenra as fixtures
from avenra.config import Config
from avenra.repositories.case_access_repository import CaseAccessRepository


OTHER_CASE = "AV-S12-OTHER"
SHELTER_ID = 1


def jpeg_data_url():
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="JPEG")
    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(image.getvalue()).decode("ascii")
    )


class ObjectAuthorizationTests(unittest.TestCase):
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    _staff_post = fixtures.avenraStagesTestCase._staff_post

    def setUp(self):
        fixtures.avenraStagesTestCase.setUp(self)

        self.other = self._create_second_survivor()
        self.owner = self._row(
            "SELECT id, case_code FROM users WHERE email = ?",
            ("survivor@avenra.demo",),
        )
        self.contact_a = self._row(
            "SELECT id, sms_opt_in FROM contacts WHERE user_id = ? ORDER BY id",
            (self.owner["id"],),
        )

        self.alert_a = self._create_alert(
            self.survivor_headers, "stage12-owner-alert"
        )
        self.diary_a = self._create_diary(
            self.survivor_headers, "stage12-owner-diary", "OWNER DIARY"
        )

        # Consent must be active before the alert so its consented location is
        # stored for the administrator's nearby-services read.
        self._grant_other_consents()
        self.alert_b = self._create_other_alert()
        self.diary_b = self._create_other_diary()
        self.referral_b = self._create_other_referral()
        self.contact_b = self._create_other_contact()
        self._seed_other_audit_event()

    # ---------- fixtures ----------

    def _row(self, sql, params=()):
        with closing(fixtures.db.connect()) as conn:
            row = conn.execute(sql, params).fetchone()
        self.assertIsNotNone(row, sql)
        return dict(row)

    def _rows(self, sql, params=()):
        with closing(fixtures.db.connect()) as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def _create_second_survivor(self):
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO users (
                    role, name, email, case_code, is_active
                ) VALUES (
                    'survivor', 'Second Fictional Survivor',
                    'second.survivor@avenra.invalid', ?, 1
                )
                """,
                (OTHER_CASE,),
            )
        return self._row(
            "SELECT id, case_code FROM users WHERE email = ?",
            ("second.survivor@avenra.invalid",),
        )

    def _create_alert(self, headers, client_id):
        response = self.client.post(
            "/api/alerts",
            json={"client_id": client_id, "lat": -33.9249, "lng": 18.4241},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json["id"]

    def _create_diary(self, headers, client_id, note):
        response = self.client.post(
            "/api/diary",
            headers=headers,
            json={
                "client_id": client_id,
                "note": note,
                "shared": True,
                "photo_data": jpeg_data_url(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json["id"]

    def _as_other_survivor(self):
        return patch.object(Config, "DEMO_CASE_CODE", OTHER_CASE)

    def _create_other_alert(self):
        with self._as_other_survivor():
            return self._create_alert(
                self.survivor_headers, "stage12-other-alert"
            )

    def _create_other_diary(self):
        with self._as_other_survivor():
            return self._create_diary(
                self.survivor_headers,
                "stage12-other-diary",
                "SECOND SURVIVOR PRIVATE NOTE",
            )

    def _create_other_referral(self):
        with closing(fixtures.db.connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO referrals (alert_id, shelter_id, status)
                VALUES (?, ?, 'sent')
                """,
                (self.alert_b, SHELTER_ID),
            )
            return cursor.lastrowid

    def _create_other_contact(self):
        with self._as_other_survivor():
            response = self.client.post(
                "/api/contacts",
                headers=self.survivor_headers,
                json={
                    "name": "Second Survivor Contact",
                    "phone": "+27 82 123 4567",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json["contacts"][0]["id"]

    def _grant_other_consents(self):
        grants = (
            ("location_sharing", "Second Case Responder Hub"),
            ("diary_sharing", "Second Case Diary Partner"),
            ("shelter_referral_sharing", "Second Case Partner Shelters"),
        )
        with closing(fixtures.db.connect()) as conn, conn:
            for item, granted_to in grants:
                conn.execute(
                    """
                    INSERT INTO consents (user_id, item, granted_to)
                    VALUES (?, ?, ?)
                    """,
                    (self.other["id"], item, granted_to),
                )

    def _seed_other_audit_event(self):
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO audit_log (actor, action, case_code, detail)
                VALUES ('survivor AV-S12-OTHER', 'diary_viewed', ?,
                        'fictional second-case history')
                """,
                (OTHER_CASE,),
            )

    def _b_snapshot(self):
        with closing(fixtures.db.connect()) as conn:
            return {
                "alert": dict(conn.execute(
                    "SELECT status, acknowledged_by, acknowledged_at "
                    "FROM alerts WHERE id = ?",
                    (self.alert_b,),
                ).fetchone()),
                "workflow": [
                    dict(row) for row in conn.execute(
                        "SELECT * FROM alert_workflow WHERE alert_id = ?",
                        (self.alert_b,),
                    ).fetchall()
                ],
                "history": [
                    dict(row) for row in conn.execute(
                        "SELECT * FROM alert_history WHERE alert_id = ?",
                        (self.alert_b,),
                    ).fetchall()
                ],
                "referral": dict(conn.execute(
                    "SELECT * FROM referrals WHERE id = ?",
                    (self.referral_b,),
                ).fetchone()),
                "contact": dict(conn.execute(
                    "SELECT * FROM contacts WHERE id = ?",
                    (self.contact_b,),
                ).fetchone()),
                "audit": [
                    dict(row) for row in conn.execute(
                        "SELECT * FROM audit_log WHERE case_code = ? "
                        "ORDER BY id",
                        (OTHER_CASE,),
                    ).fetchall()
                ],
            }

    # ---------- staff object authorization ----------

    def test_grant_for_one_case_cannot_read_or_change_another_case(self):
        self._login_staff("responder")
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        before = self._b_snapshot()

        listing = self.client.get("/api/alerts")
        self.assertEqual(listing.status_code, 200)
        visible = {alert["id"] for alert in listing.json["alerts"]}
        self.assertIn(self.alert_a, visible)
        self.assertNotIn(self.alert_b, visible)

        self.assertEqual(
            self._staff_post(
                f"/api/alerts/{self.alert_b}/acknowledge"
            ).status_code,
            404,
        )
        self.assertEqual(
            self._staff_post(
                f"/api/alerts/{self.alert_b}/workflow",
                json={
                    "action": "escalate",
                    "revision": 0,
                    "reason": "Fictional cross-case attempt",
                },
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/alerts/{self.alert_b}/nearby-services"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/cases/{OTHER_CASE}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/diary", query_string={"case_code": OTHER_CASE}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/cases/diary-photo/{self.diary_b}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self._staff_post(
                "/api/referrals",
                json={"alert_id": self.alert_b, "shelter_id": SHELTER_ID},
            ).status_code,
            404,
        )
        self.assertEqual(
            self._staff_post(
                f"/api/referrals/{self.referral_b}/status",
                json={"status": "accepted"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/consents", query_string={"case_code": OTHER_CASE}
            ).status_code,
            404,
        )

        audit = self.client.get(
            "/api/audit-log", query_string={"case_code": OTHER_CASE}
        )
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json["total"], 0)
        self.assertNotIn(OTHER_CASE, audit.get_data(as_text=True))

        own_audit = self.client.get(
            "/api/audit-log",
            query_string={"case_code": self.owner["case_code"]},
        )
        self.assertEqual(own_audit.status_code, 200)
        self.assertGreaterEqual(own_audit.json["total"], 1)
        self.assertTrue(
            all(event["case_code"] == self.owner["case_code"]
                for event in own_audit.json["events"])
        )

        # The granted case stays usable, so the denials are object-specific.
        self.assertEqual(
            self.client.get(f"/cases/{self.owner['case_code']}").status_code,
            200,
        )
        with self.client.get(
            f"/cases/diary-photo/{self.diary_a}", buffered=True
        ) as photo:
            self.assertEqual(photo.status_code, 200)

        self.assertEqual(self._b_snapshot(), before)
        with closing(fixtures.db.connect()) as conn:
            self.assertFalse(
                CaseAccessRepository(conn).assigned(
                    staff_id, self.other["id"]
                )
            )

    def test_admin_reads_unassigned_cases_but_not_by_assignment_policy(self):
        self._login_staff("admin")
        with self.client.session_transaction() as session:
            admin_id = session["user_id"]

        listing = self.client.get("/api/alerts")
        self.assertEqual(listing.status_code, 200)
        visible = {alert["id"] for alert in listing.json["alerts"]}
        self.assertIn(self.alert_a, visible)
        self.assertIn(self.alert_b, visible)

        self.assertEqual(
            self.client.get(f"/cases/{OTHER_CASE}").status_code, 200
        )

        diary = self.client.get(
            "/api/diary", query_string={"case_code": OTHER_CASE}
        )
        self.assertEqual(diary.status_code, 200)
        self.assertTrue(
            any(entry["id"] == self.diary_b for entry in diary.json["entries"])
        )
        with self.client.get(
            f"/cases/diary-photo/{self.diary_b}", buffered=True
        ) as photo:
            self.assertEqual(photo.status_code, 200)

        consents = self.client.get(
            "/api/consents", query_string={"case_code": OTHER_CASE}
        )
        self.assertEqual(consents.status_code, 200)
        diary_consent = next(
            item for item in consents.json["consents"]
            if item["item"] == "diary_sharing"
        )
        self.assertTrue(diary_consent["active"])
        self.assertEqual(
            diary_consent["granted_to"], "Second Case Diary Partner"
        )

        nearby = self.client.get(
            f"/api/alerts/{self.alert_b}/nearby-services"
        )
        self.assertEqual(nearby.status_code, 200)

        audit = self.client.get(
            "/api/audit-log", query_string={"case_code": OTHER_CASE}
        )
        self.assertEqual(audit.status_code, 200)
        self.assertGreaterEqual(audit.json["total"], 1)
        self.assertTrue(
            all(event["case_code"] == OTHER_CASE
                for event in audit.json["events"])
        )

        with closing(fixtures.db.connect()) as conn:
            access = CaseAccessRepository(conn)
            self.assertTrue(access.allows(admin_id, self.other["id"]))
            self.assertFalse(access.assigned(admin_id, self.other["id"]))

    def test_multi_case_staff_selects_consents_per_case(self):
        self._login_staff("responder")
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute(
                "INSERT INTO case_access (staff_id, survivor_id) VALUES (?, ?)",
                (staff_id, self.other["id"]),
            )

        own = self.client.get(
            "/api/consents",
            query_string={"case_code": self.owner["case_code"]},
        )
        other = self.client.get(
            "/api/consents", query_string={"case_code": OTHER_CASE}
        )
        self.assertEqual(own.status_code, 200)
        self.assertEqual(other.status_code, 200)

        def diary_grant(body):
            return next(
                item["granted_to"] for item in body.json["consents"]
                if item["item"] == "diary_sharing"
            )

        self.assertEqual(
            diary_grant(own), "Assigned Social Worker (Nomsa D)"
        )
        self.assertEqual(diary_grant(other), "Second Case Diary Partner")

        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute(
                "DELETE FROM case_access WHERE staff_id = ? AND survivor_id = ?",
                (staff_id, self.other["id"]),
            )
        self.assertEqual(
            self.client.get(
                "/api/consents", query_string={"case_code": OTHER_CASE}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/consents",
                query_string={"case_code": self.owner["case_code"]},
            ).status_code,
            200,
        )

    # ---------- survivor object authorization ----------

    def test_survivor_cannot_change_another_survivors_contacts(self):
        with self._as_other_survivor():
            self.assertEqual(
                self.client.delete(
                    f"/api/contacts/{self.contact_a['id']}",
                    headers=self.survivor_headers,
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/contacts/{self.contact_a['id']}/sms",
                    headers=self.survivor_headers,
                    json={"enabled": True},
                ).status_code,
                404,
            )
            replace = self.client.post(
                "/api/contacts",
                headers=self.survivor_headers,
                json={
                    "contacts": [{
                        "id": self.contact_a["id"],
                        "name": "Hijacked Contact",
                        "phone": "+27 82 123 4568",
                    }]
                },
            )
            self.assertEqual(replace.status_code, 400)

        contact = self._row(
            "SELECT * FROM contacts WHERE id = ?", (self.contact_a["id"],)
        )
        self.assertEqual(contact["user_id"], self.owner["id"])
        self.assertEqual(contact["sms_opt_in"], self.contact_a["sms_opt_in"])
        self.assertNotEqual(contact["name"], "Hijacked Contact")


if __name__ == "__main__":
    unittest.main()
