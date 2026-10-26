"""Diary disclosure and truthful survivor access history."""
import base64
import io
import os
import unittest
from contextlib import closing

from PIL import Image
import test_avenra as fixtures


class DiaryAccessTests(unittest.TestCase):
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff

    def setUp(self):
        fixtures.avenraStagesTestCase.setUp(self)
        with closing(fixtures.db.connect()) as conn:
            self.owner = dict(conn.execute(
                """
                SELECT id, case_code FROM users
                WHERE role = 'survivor'
                ORDER BY id LIMIT 1
                """
            ).fetchone())

        self.set_consent(True)

    def set_consent(self, active):
        response = self.client.post(
            "/api/consents",
            json={"item": "diary_sharing", "active": active},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)

    def create_photo(self, *, shared=True):
        photo = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(photo, format="JPEG")
        encoded = base64.b64encode(photo.getvalue()).decode("ascii")

        response = self.client.post(
            "/api/diary",
            headers=self.survivor_headers,
            json={
                "client_id": "stage4-diary-access",
                "note": "PRIVATE-DIARY-TEXT",
                "shared": shared,
                "photo_data": "data:image/jpeg;base64," + encoded,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def viewing_events(self):
        with closing(fixtures.db.connect()) as conn:
            return [
                dict(row) for row in conn.execute(
                    """
                    SELECT id, action, case_code FROM audit_log
                    WHERE case_code = ?
                      AND action IN (
                          'diary_viewed', 'diary_photo_viewed'
                      )
                    ORDER BY id
                    """,
                    (self.owner["case_code"],),
                )
            ]

    def list_diary(self):
        return self.client.get(
            "/api/diary",
            query_string={"case_code": self.owner["case_code"]},
        )

    def test_successful_views_appear_in_safe_survivor_history(self):
        entry_id = self.create_photo()
        self._login_staff("responder")
        before = {event["id"] for event in self.viewing_events()}

        listing = self.list_diary()
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(
            entry["id"] == entry_id
            for entry in listing.json["entries"]
        ))

        with self.client.get(
            f"/cases/diary-photo/{entry_id}", buffered=True
        ) as photo:
            self.assertEqual(photo.status_code, 200)
            self.assertIn("no-store", photo.headers["Cache-Control"])

        added = [
            event for event in self.viewing_events()
            if event["id"] not in before
        ]
        self.assertEqual(
            [event["action"] for event in added],
            ["diary_viewed", "diary_photo_viewed"],
        )

        history = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
        )
        self.assertEqual(history.status_code, 200)
        visible_ids = {
            event["id"] for event in history.json["events"]
        }
        self.assertTrue(
            {event["id"] for event in added}.issubset(visible_ids)
        )
        self.assertNotIn(
            "PRIVATE-DIARY-TEXT", history.get_data(as_text=True)
        )
        self.assertNotIn(
            "photo_path", history.get_data(as_text=True)
        )

    def test_withdrawal_blocks_disclosure_without_recording_a_view(self):
        entry_id = self.create_photo()
        self.set_consent(False)
        self._login_staff("responder")
        before = self.viewing_events()

        listing = self.list_diary()
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            listing.json, {"entries": [], "consent_active": False}
        )
        self.assertEqual(
            self.client.get(
                f"/cases/diary-photo/{entry_id}"
            ).status_code,
            403,
        )
        self.assertEqual(self.viewing_events(), before)

    def test_unshared_photo_is_not_disclosed_or_logged_as_viewed(self):
        entry_id = self.create_photo(shared=False)
        self._login_staff("responder")
        before = self.viewing_events()

        listing = self.list_diary()
        self.assertEqual(listing.status_code, 200)
        self.assertFalse(any(
            entry["id"] == entry_id
            for entry in listing.json["entries"]
        ))
        self.assertEqual(
            self.client.get(
                f"/cases/diary-photo/{entry_id}"
            ).status_code,
            404,
        )
        # Other shared entries may legitimately appear in the listing.
        self.assertFalse(any(
            event["action"] == "diary_photo_viewed"
            and event["id"] not in {row["id"] for row in before}
            for event in self.viewing_events()
        ))

    def test_revoked_case_assignment_blocks_listing_and_photo(self):
        entry_id = self.create_photo()
        self._login_staff("responder")
        with self.client.session_transaction() as session:
            staff_id = session["user_id"]

        with closing(fixtures.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    DELETE FROM case_access
                    WHERE staff_id = ? AND survivor_id = ?
                    """,
                    (staff_id, self.owner["id"]),
                )

        before = self.viewing_events()
        self.assertEqual(self.list_diary().status_code, 404)
        self.assertEqual(
            self.client.get(
                f"/cases/diary-photo/{entry_id}"
            ).status_code,
            404,
        )
        self.assertEqual(self.viewing_events(), before)

    def test_missing_photo_file_does_not_record_a_view(self):
        from avenra.controllers.diary_controller import get_uploads_dir

        entry_id = self.create_photo()
        with closing(fixtures.db.connect()) as conn:
            filename = conn.execute(
                "SELECT photo_path FROM diary_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()["photo_path"]

        with self.client.application.app_context():
            os.unlink(os.path.join(get_uploads_dir(), filename))

        self._login_staff("responder")
        before = self.viewing_events()
        self.assertEqual(
            self.client.get(
                f"/cases/diary-photo/{entry_id}"
            ).status_code,
            404,
        )
        self.assertEqual(self.viewing_events(), before)

    def _ensure_second_survivor(self):
        with closing(fixtures.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        role, name, email, case_code, is_active
                    ) VALUES (
                        'survivor', 'Survivor Two', 'survivor2@avenra.local', 'AV-S5-OTHER', 1
                    )
                    """
                )

    def test_survivor_own_entry_detail_photo_and_cross_owner_isolation(self):
        from unittest.mock import patch
        from avenra.config import Config

        entry_id = self.create_photo(shared=False)
        self._ensure_second_survivor()

        own_detail = self.client.get(
            f"/api/diary/{entry_id}",
            headers=self.survivor_headers,
        )
        self.assertEqual(own_detail.status_code, 200)
        self.assertEqual(
            own_detail.headers.get("Cache-Control"), "private, no-store"
        )
        entry_body = own_detail.json["entry"]
        self.assertEqual(entry_body["id"], entry_id)
        self.assertEqual(entry_body["note"], "PRIVATE-DIARY-TEXT")
        self.assertEqual(
            entry_body["photo_url"], f"/api/diary/{entry_id}/photo"
        )

        with self.client.get(
            f"/api/diary/{entry_id}/photo",
            headers=self.survivor_headers,
            buffered=True,
        ) as own_photo:
            self.assertEqual(own_photo.status_code, 200)
            self.assertEqual(
                own_photo.headers.get("Cache-Control"), "private, no-store"
            )

        with patch.object(Config, "DEMO_CASE_CODE", "AV-S5-OTHER"):
            from vault_fixture import unlock_test_vault
            unlock_test_vault(self.client,self.survivor_headers)
            self.assertEqual(
                self.client.get(
                    f"/api/diary/{entry_id}", headers=self.survivor_headers
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    f"/api/diary/{entry_id}/photo", headers=self.survivor_headers
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/diary/{entry_id}/share",
                    headers=self.survivor_headers,
                    json={"shared": True},
                ).status_code,
                404,
            )

    def test_survivor_paginated_listing_and_cursor_binding(self):
        from unittest.mock import patch
        from avenra.config import Config

        self._ensure_second_survivor()
        for idx in range(3):
            res = self.client.post(
                "/api/diary",
                headers=self.survivor_headers,
                json={
                    "client_id": f"stage5-page-{idx}",
                    "note": f"Page entry {idx}",
                    "shared": False,
                },
            )
            self.assertEqual(res.status_code, 201)

        page1 = self.client.get(
            "/api/diary?limit=2", headers=self.survivor_headers
        )
        self.assertEqual(page1.status_code, 200)
        self.assertEqual(
            page1.headers.get("Cache-Control"), "private, no-store"
        )
        self.assertEqual(len(page1.json["entries"]), 2)
        self.assertIsNotNone(page1.json["next_cursor"])
        for receipt in page1.json["entries"]:
            self.assertNotIn("note", receipt)

        cursor = page1.json["next_cursor"]
        page2 = self.client.get(
            f"/api/diary?limit=2&cursor={cursor}",
            headers=self.survivor_headers,
        )
        self.assertEqual(page2.status_code, 200)
        self.assertGreaterEqual(len(page2.json["entries"]), 1)

        with patch.object(Config, "DEMO_CASE_CODE", "AV-S5-OTHER"):
            from vault_fixture import unlock_test_vault
            unlock_test_vault(self.client,self.survivor_headers)
            cross_cursor = self.client.get(
                f"/api/diary?limit=2&cursor={cursor}",
                headers=self.survivor_headers,
            )
            self.assertEqual(cross_cursor.status_code, 400)
            self.assertEqual(cross_cursor.json["error"], "invalid_diary_cursor")

        unlock_test_vault(self.client,self.survivor_headers)

        bad_limit = self.client.get(
            "/api/diary?limit=99", headers=self.survivor_headers
        )
        self.assertEqual(bad_limit.status_code, 400)
        self.assertEqual(bad_limit.json["error"], "invalid_diary_limit")

        bad_param = self.client.get(
            "/api/diary?extra=1", headers=self.survivor_headers
        )
        self.assertEqual(bad_param.status_code, 400)
        self.assertEqual(bad_param.json["error"], "invalid_diary_parameters")

    def test_per_entry_share_toggle_and_global_consent_interaction(self):
        entry_a = self.create_photo(shared=True)
        res_b = self.client.post(
            "/api/diary",
            headers=self.survivor_headers,
            json={
                "client_id": "stage5-share-b",
                "note": "Entry B note",
                "shared": True,
            },
        )
        self.assertEqual(res_b.status_code, 201)
        entry_b = res_b.json["id"]

        unshare_a = self.client.post(
            f"/api/diary/{entry_a}/share",
            headers=self.survivor_headers,
            json={"shared": False},
        )
        self.assertEqual(unshare_a.status_code, 200)
        self.assertFalse(unshare_a.json["entry"]["shared"])
        self.assertTrue(unshare_a.json["global_diary_consent_active"])

        self._login_staff("responder")
        listing = self.list_diary()
        self.assertEqual(listing.status_code, 200)
        visible_ids = {e["id"] for e in listing.json["entries"]}
        self.assertNotIn(entry_a, visible_ids)
        self.assertIn(entry_b, visible_ids)
        self.assertEqual(
            self.client.get(f"/cases/diary-photo/{entry_a}").status_code,
            404,
        )

        # Global withdrawal hides all entries even if shared=True
        self.set_consent(False)
        withdrawn_list = self.list_diary()
        self.assertEqual(
            withdrawn_list.json, {"entries": [], "consent_active": False}
        )

        # Global re-grant restores only entries still marked shared=True
        self.set_consent(True)
        restored_list = self.list_diary()
        restored_ids = {e["id"] for e in restored_list.json["entries"]}
        self.assertNotIn(entry_a, restored_ids)
        self.assertIn(entry_b, restored_ids)

    def test_staff_role_matrix_for_diary_access(self):
        entry_id = self.create_photo(shared=True)

        # Shelter user is forbidden
        self._login_staff("shelter")
        self.assertEqual(self.list_diary().status_code, 403)
        self.assertEqual(
            self.client.get(f"/cases/diary-photo/{entry_id}").status_code,
            403,
        )

        # Admin without case assignment receives 404
        self._login_staff("admin")
        with self.client.session_transaction() as session:
            admin_id = session["user_id"]
        with closing(fixtures.db.connect()) as conn:
            with conn:
                conn.execute(
                    "DELETE FROM case_access WHERE staff_id = ? AND survivor_id = ?",
                    (admin_id, self.owner["id"]),
                )
        self.assertEqual(self.list_diary().status_code, 404)
        self.assertEqual(
            self.client.get(f"/cases/diary-photo/{entry_id}").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
