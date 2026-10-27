"""Service transactions must close on success, early return, and errors.

Leaving ``BEGIN IMMEDIATE`` open until request teardown holds write locks and
relies on connection cleanup instead of an explicit commit or rollback.
"""
import sqlite3
import unittest
from contextlib import closing

import test_avenra as fixtures
from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.referral_repository import ReferralRepository
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.repositories.user_repository import UserRepository
from avenra.services.referral_service import ReferralService
from avenra.services.shelter_service import ShelterService


class TransactionBoundaryTests(unittest.TestCase):
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def setUp(self):
        fixtures.avenraStagesTestCase.setUp(self)
        self.alert_one = self._create_alert("transaction-one")
        self.alert_two = self._create_alert("transaction-two")
        with closing(fixtures.db.connect()) as conn:
            self.shelter_id = conn.execute(
                "SELECT id FROM shelters ORDER BY id LIMIT 1"
            ).fetchone()[0]
            self.other_shelter_id = conn.execute(
                "SELECT id FROM shelters WHERE id != ? ORDER BY id LIMIT 1",
                (self.shelter_id,),
            ).fetchone()[0]

    def _create_alert(self, client_id):
        response = self.client.post(
            "/api/alerts",
            json={"client_id": client_id},
            headers=self.survivor_headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json["id"]

    def _connect(self):
        conn = fixtures.db.connect()
        self.addCleanup(conn.close)
        return conn

    def _referral_service(self, conn):
        return ReferralService(
            referral_repo=ReferralRepository(conn),
            alert_repo=AlertRepository(conn),
            shelter_repo=ShelterRepository(conn),
            consent_repo=ConsentRepository(conn),
            audit_repo=AuditRepository(conn),
        )

    def _shelter_service(self, conn):
        return ShelterService(
            shelter_repo=ShelterRepository(conn),
            audit_repo=AuditRepository(conn),
        )

    def _responder(self, conn):
        user = UserRepository(conn).get_by_email("nomsa@avenra.demo")
        self.assertIsNotNone(user)
        return user

    def _shelter_user(self, conn):
        user = UserRepository(conn).get_by_email("pieter@avenra.demo")
        self.assertIsNotNone(user)
        return user

    def test_referral_create_closes_on_success_and_every_rejection(self):
        conn = self._connect()
        service = self._referral_service(conn)
        user = self._responder(conn)

        created, status = service.create_referral(
            self.alert_one, self.shelter_id, user
        )
        self.assertEqual(status, 201)
        self.assertFalse(conn.in_transaction)

        retried, status = service.create_referral(
            self.alert_one, self.shelter_id, user
        )
        self.assertEqual(status, 200)
        self.assertTrue(retried["already"])
        self.assertFalse(conn.in_transaction)

        conflict, status = service.create_referral(
            self.alert_one, self.other_shelter_id, user
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"], "active_referral")
        self.assertFalse(conn.in_transaction)

        missing, status = service.create_referral(
            999999, self.shelter_id, user
        )
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "not_found")
        self.assertFalse(conn.in_transaction)

        referral_id = created["referral"]["id"]
        with closing(fixtures.db.connect()) as verifier:
            stored = verifier.execute(
                "SELECT status FROM referrals WHERE id = ?", (referral_id,)
            ).fetchone()
        self.assertEqual(stored["status"], "sent")

    def test_referral_create_rolls_back_on_database_error(self):
        conn = self._connect()
        service = self._referral_service(conn)
        user = self._responder(conn)

        conn.execute(
            """
            CREATE TRIGGER synthetic_referral_abort
            BEFORE INSERT ON referrals
            BEGIN
                SELECT RAISE(ABORT, 'synthetic');
            END
            """
        )
        conn.commit()

        with self.assertRaises(sqlite3.DatabaseError):
            service.create_referral(self.alert_two, self.shelter_id, user)
        self.assertFalse(conn.in_transaction)

        count = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE alert_id = ?",
            (self.alert_two,),
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_referral_status_closes_on_success_and_every_rejection(self):
        conn = self._connect()
        service = self._referral_service(conn)
        user = self._responder(conn)

        created, status = service.create_referral(
            self.alert_one, self.shelter_id, user
        )
        self.assertEqual(status, 201)
        referral_id = created["referral"]["id"]
        self.assertFalse(conn.in_transaction)

        invalid, status = service.update_status(
            referral_id, user, "placed"
        )
        self.assertEqual(status, 409)
        self.assertEqual(invalid["error"], "invalid_transition")
        self.assertFalse(conn.in_transaction)

        missing, status = service.update_status(999999, user, "accepted")
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "not_found")
        self.assertFalse(conn.in_transaction)

        accepted, status = service.update_status(
            referral_id, user, "accepted"
        )
        self.assertEqual(status, 200)
        self.assertEqual(accepted["referral"]["status"], "accepted")
        self.assertFalse(conn.in_transaction)

        repeated, status = service.update_status(
            referral_id, user, "accepted"
        )
        self.assertEqual(status, 200)
        self.assertTrue(repeated["already"])
        self.assertFalse(conn.in_transaction)

        placed, status = service.update_status(referral_id, user, "placed")
        self.assertEqual(status, 200)
        self.assertEqual(placed["referral"]["status"], "placed")
        self.assertFalse(conn.in_transaction)

        with closing(fixtures.db.connect()) as verifier:
            stored = verifier.execute(
                "SELECT status FROM referrals WHERE id = ?", (referral_id,)
            ).fetchone()
            alert = verifier.execute(
                "SELECT status FROM alerts WHERE id = ?", (self.alert_one,)
            ).fetchone()
        self.assertEqual(stored["status"], "placed")
        self.assertEqual(alert["status"], "resolved")

    def test_capacity_update_closes_on_success_and_every_rejection(self):
        conn = self._connect()
        service = self._shelter_service(conn)
        user = self._responder(conn)

        missing, status = service.update_capacity(999999, user, {"delta": 1})
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "not_found")
        self.assertFalse(conn.in_transaction)

        empty, status = service.update_capacity(self.shelter_id, user, {})
        self.assertEqual(status, 400)
        self.assertEqual(empty["error"], "invalid_capacity_update")
        self.assertFalse(conn.in_transaction)

        ambiguous, status = service.update_capacity(
            self.shelter_id,
            user,
            {"delta": 1, "beds_available": 2},
        )
        self.assertEqual(status, 400)
        self.assertEqual(ambiguous["error"], "ambiguous_capacity_update")
        self.assertFalse(conn.in_transaction)

        shelter_user = self._shelter_user(conn)
        forbidden, status = service.update_capacity(
            self.other_shelter_id, shelter_user, {"delta": 1}
        )
        self.assertEqual(status, 403)
        self.assertEqual(forbidden["error"], "forbidden")
        self.assertFalse(conn.in_transaction)

        before = conn.execute(
            "SELECT beds_available FROM shelters WHERE id = ?",
            (self.shelter_id,),
        ).fetchone()[0]
        updated, status = service.update_capacity(
            self.shelter_id, user, {"delta": 1}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            updated["shelter"]["beds_available"], before + 1
        )
        self.assertFalse(conn.in_transaction)

        with closing(fixtures.db.connect()) as verifier:
            stored = verifier.execute(
                "SELECT beds_available FROM shelters WHERE id = ?",
                (self.shelter_id,),
            ).fetchone()[0]
        self.assertEqual(stored, before + 1)


if __name__ == "__main__":
    unittest.main()
