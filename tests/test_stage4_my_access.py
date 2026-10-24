"""Survivor access history must be scoped and privacy-safe."""
import unittest
from contextlib import closing

import test_avenra
import time
from types import SimpleNamespace
from unittest.mock import patch


class MyAccessTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def seed_history(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                survivor = conn.execute(
                    """
                    SELECT case_code FROM users
                    WHERE role = 'survivor'
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()

                staff = conn.execute(
                    """
                    SELECT id, name, role FROM users
                    WHERE role = 'responder'
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()

                actor = f"user:{staff['id']}"

                def add(action, case_code, timestamp):
                    return conn.execute(
                        """
                        INSERT INTO audit_log
                            (actor, action, case_code, detail, ts)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            actor,
                            action,
                            case_code,
                            "PRIVATE-DETAIL-MUST-NOT-LEAK",
                            timestamp,
                        ),
                    ).lastrowid

                diary_id = add(
                    "diary_viewed",
                    survivor["case_code"],
                    "2026-10-24T08:00:00Z",
                )
                case_id = add(
                    "case_viewed",
                    survivor["case_code"],
                    "2026-10-24T09:00:00Z",
                )

                # These must not appear in this survivor's viewing history.
                add(
                    "consent_revoked",
                    survivor["case_code"],
                    "2026-10-24T09:30:00Z",
                )
                add(
                    "case_viewed",
                    "OTHER-CASE",
                    "2026-10-24T10:00:00Z",
                )

        return dict(staff), case_id, diary_id

    def test_signed_out_request_is_rejected(self):
        response = self.client.get("/api/my-access")
        self.assertEqual(response.status_code, 401)

    def test_staff_cookie_cannot_replace_survivor_authority(self):
        self._login_staff("responder")
        response = self.client.get("/api/my-access")
        self.assertEqual(response.status_code, 401)

    def test_returns_only_safe_own_case_viewing_events(self):
        staff, case_id, diary_id = self.seed_history()

        response = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])

        body = response.get_json()
        self.assertEqual(set(body), {"events", "next_cursor"})
        self.assertIsNone(body["next_cursor"])

        events = body["events"]
        self.assertEqual(
            [event["id"] for event in events],
            [case_id, diary_id],
        )
        self.assertEqual(
            [event["action"] for event in events],
            ["case_viewed", "diary_viewed"],
        )

        for event in events:
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
            self.assertEqual(event["actor_name"], staff["name"])
            self.assertEqual(event["actor_role"], staff["role"])

        self.assertEqual(
            events[0]["viewed_at"],
            "2026-10-24T09:00:00Z",
        )
        self.assertNotIn(
            "PRIVATE-DETAIL-MUST-NOT-LEAK",
            response.get_data(as_text=True),
        )
        self.assertNotIn(
            "OTHER-CASE",
            response.get_data(as_text=True),
        )

    def test_client_cannot_select_another_identity_or_case(self):
        for selector in ("case_code", "survivor_id", "staff_id"):
            with self.subTest(selector=selector):
                response = self.client.get(
                    "/api/my-access",
                    headers=self.survivor_headers,
                    query_string={selector: "OTHER"},
                )
                self.assertEqual(response.status_code, 400)

    def test_history_endpoint_does_not_accept_writes(self):
        response = self.client.post(
            "/api/my-access",
            headers=self.survivor_headers,
            json={},
        )
        self.assertEqual(response.status_code, 405)

    def test_pagination_returns_each_event_once(self):
        _, case_id, diary_id = self.seed_history()

        first = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"limit": 1},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            [event["id"] for event in first.json["events"]],
            [case_id],
        )
        cursor = first.json["next_cursor"]
        self.assertIsInstance(cursor, str)
        self.assertTrue(cursor)

        second = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"limit": 1, "cursor": cursor},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            [event["id"] for event in second.json["events"]],
            [diary_id],
        )
        self.assertIsNone(second.json["next_cursor"])

    def test_invalid_limits_are_rejected(self):
        for limit in ("0", "51", "-1", "abc", "", "1.5"):
            with self.subTest(limit=limit):
                response = self.client.get(
                    "/api/my-access",
                    headers=self.survivor_headers,
                    query_string={"limit": limit},
                )
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("events", response.json)

    def test_tampered_cursor_is_rejected(self):
        self.seed_history()

        first = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"limit": 1},
        )
        self.assertEqual(first.status_code, 200)
        cursor = first.json["next_cursor"]
        self.assertTrue(cursor)

        response = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"cursor": cursor + ".tampered"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("events", response.json)

    def test_missing_staff_identity_has_truthful_fallback(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                case_code = conn.execute(
                    """
                    SELECT case_code FROM users
                    WHERE role = 'survivor'
                    ORDER BY id LIMIT 1
                    """
                ).fetchone()["case_code"]

                event_id = conn.execute(
                    """
                    INSERT INTO audit_log
                        (actor, action, case_code, detail, ts)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "user:999999999",
                        "case_viewed",
                        case_code,
                        "PRIVATE-DETAIL-MUST-NOT-LEAK",
                        "2026-10-24T11:00:00Z",
                    ),
                ).lastrowid

        response = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)

        event = next(
            event for event in response.json["events"]
            if event["id"] == event_id
        )
        self.assertEqual(
            event["actor_name"],
            "Staff member (name unavailable)",
        )
        self.assertEqual(event["actor_role"], "staff")
        self.assertNotIn("999999999", response.get_data(as_text=True))

    def test_empty_history_has_explicit_empty_response(self):
        # Remove only viewing events in this temporary test database.
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    DELETE FROM audit_log
                    WHERE action IN ('case_viewed', 'diary_viewed')
                    """
                )

        response = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"events": [], "next_cursor": None},
        )

    def test_cursor_is_bound_to_the_authenticated_survivor(self):
        self.seed_history()

        first = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"limit": 1},
        )
        self.assertEqual(first.status_code, 200)
        cursor = first.json["next_cursor"]
        self.assertTrue(cursor)

        # Simulate another authenticated identity to isolate cursor binding.
        # This does not test or bypass production enrolment.
        other_survivor = SimpleNamespace(id=999999999)

        with patch(
            "avenra.controllers.access_history_controller.device_user",
            return_value=other_survivor,
        ):
            response = self.client.get(
                "/api/my-access",
                query_string={"cursor": cursor},
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("events", response.json)

    def test_expired_cursor_is_rejected(self):
        self.seed_history()
        expired_time = int(time.time()) - 901

        # Issue an old signed cursor without sleeping.
        with patch(
            "itsdangerous.timed.TimestampSigner.get_timestamp",
            return_value=expired_time,
        ):
            first = self.client.get(
                "/api/my-access",
                headers=self.survivor_headers,
                query_string={"limit": 1},
            )

        self.assertEqual(first.status_code, 200)
        cursor = first.json["next_cursor"]
        self.assertTrue(cursor)

        response = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"cursor": cursor},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("events", response.json)

    def test_equal_timestamps_do_not_skip_or_duplicate_events(self):
        _, case_id, diary_id = self.seed_history()

        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE audit_log SET ts = ?
                    WHERE id IN (?, ?)
                    """,
                    ("2026-10-24T09:00:00Z", case_id, diary_id),
                )

        first = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={"limit": 1},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            [event["id"] for event in first.json["events"]],
            [case_id],
        )
        self.assertTrue(first.json["next_cursor"])

        second = self.client.get(
            "/api/my-access",
            headers=self.survivor_headers,
            query_string={
                "limit": 1,
                "cursor": first.json["next_cursor"],
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            [event["id"] for event in second.json["events"]],
            [diary_id],
        )
        self.assertIsNone(second.json["next_cursor"])

if __name__ == "__main__":
    unittest.main()