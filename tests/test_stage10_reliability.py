"""Crash/concurrency contracts using isolated databases and fake senders only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier, Lock
import sqlite3
import unittest
from unittest.mock import Mock
import test_avenra as fixtures
import test_notification_worker as notification_fixtures
import test_webpush as push_fixtures
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
from avenra.services.notification_worker import NotificationWorker


class WorkerFailureTests(unittest.TestCase):
    setUp=notification_fixtures.NotificationWorkerTests.setUp
    tearDown=notification_fixtures.NotificationWorkerTests.tearDown
    status=notification_fixtures.NotificationWorkerTests.status
    worker=notification_fixtures.NotificationWorkerTests.worker

    def stale(self):
        with self.conn:
            self.conn.execute("UPDATE notification_outbox SET claimed_at='2000-01-01T00:00:00Z' WHERE id=?",(self.job_id,))

    def test_missing_and_malformed_claim_times_become_unknown_never_pending(self):
        repo=NotificationOutboxRepository(self.conn)
        for timestamp in (None,'not-a-timestamp'):
            with self.subTest(timestamp=timestamp):
                with self.conn:
                    self.conn.execute("UPDATE notification_outbox SET status='processing',claim_token='fictional-claim',claimed_at=? WHERE id=?",(timestamp,self.job_id))
                sender=Mock()
                self.assertEqual(self.worker(sender).recover_stale(),1)
                self.assertEqual(self.status(),'unknown')
                self.assertFalse(self.worker(sender).run_once())
                sender.assert_not_called()
                self.assertFalse(repo.finish(self.job_id,'fictional-claim','accepted'))

    def test_recovery_is_bounded_per_tick_even_with_many_orphaned_claims(self):
        with self.conn:
            owner=self.conn.execute('SELECT user_id FROM alerts WHERE id=?',(self.alert_id,)).fetchone()[0]
            for index in range(110):
                contact=self.conn.execute('INSERT INTO contacts(user_id,name,phone) VALUES(?,?,?) RETURNING id',(owner,'Fictional capacity '+str(index),'+2782'+str(index).zfill(7))).fetchone()[0]
                self.conn.execute("INSERT INTO notification_outbox(alert_id,contact_id,status,claim_token,claimed_at) VALUES(?,?,'processing',?,'2000-01-01T00:00:00Z')",(self.alert_id,contact,'fictional-capacity-'+str(index)))
        worker=self.worker(Mock())
        self.assertEqual(worker.recover_stale(),100)
        self.assertEqual(worker.recover_stale(),10)
        self.assertEqual(worker.recover_stale(),0)

    def test_crash_after_claim_survives_reconnect_and_never_retries_unknown(self):
        with self.conn:
            job=NotificationOutboxRepository(self.conn).claim_next(channel='sms')
        self.conn.close(); self.conn=fixtures.db.connect()
        sender=Mock()
        self.assertFalse(self.worker(sender).run_once())
        self.assertEqual(self.worker(sender).recover_stale(),0)
        self.stale()
        self.assertEqual(self.worker(sender).recover_stale(),1)
        self.assertFalse(self.worker(sender).run_once())
        self.assertEqual(self.status(),'unknown')
        sender.assert_not_called()
        with self.conn:
            self.assertFalse(NotificationOutboxRepository(self.conn).finish(job['id'],job['claim_token'],'accepted'))

    def test_recovery_cursor_progresses_past_recent_claims_and_wraps(self):
        with self.conn:
            owner=self.conn.execute('SELECT user_id FROM alerts WHERE id=?',(self.alert_id,)).fetchone()[0]
            for index in range(101):
                contact=self.conn.execute('INSERT INTO contacts(user_id,name,phone) VALUES(?,?,?) RETURNING id',(owner,'Fictional recent '+str(index),'+2783'+str(index).zfill(7))).fetchone()[0]
                self.conn.execute("INSERT INTO notification_outbox(alert_id,contact_id,status,claim_token,claimed_at) VALUES(?,?,'processing',?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))",(self.alert_id,contact,'fictional-recent-'+str(index)))
            last=self.conn.execute("SELECT MAX(id) FROM notification_outbox WHERE status='processing'").fetchone()[0]
            self.conn.execute("UPDATE notification_outbox SET claimed_at='2000-01-01T00:00:00Z' WHERE id=?",(last,))
        worker=self.worker(Mock())
        self.assertEqual(worker.recover_stale(),0)
        self.assertEqual(worker.recover_stale(),1)
        self.assertEqual(worker.recover_stale(),0)
        with self.conn:
            self.conn.execute("UPDATE notification_outbox SET claimed_at='2000-01-01T00:00:00Z' WHERE status='processing'")
        self.assertEqual(worker.recover_stale(),100)

    def test_audit_failure_after_provider_acceptance_leaves_uncertain_claim_not_retry(self):
        with self.conn:
            self.conn.execute("CREATE TRIGGER fail_accept_audit BEFORE INSERT ON audit_log WHEN NEW.action='notification_accepted' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        sender=Mock(return_value={'outcome':'accepted','reason':'provider_accepted'})
        with self.assertRaises(sqlite3.Error): self.worker(sender).run_once()
        self.assertEqual(self.status(),'processing')
        sender.assert_called_once()
        self.stale()
        self.assertEqual(self.worker(sender).recover_stale(),1)
        self.assertFalse(self.worker(sender).run_once())
        self.assertEqual(self.status(),'unknown')
        sender.assert_called_once()

    def test_two_workers_send_single_job_once_and_reserve_one_batch(self):
        barrier=Barrier(2); guard=Lock(); calls=[]
        def send(**_):
            with guard: calls.append(True)
            return {'outcome':'accepted','reason':'provider_accepted'}
        def run():
            with closing(fixtures.db.connect()) as conn:
                barrier.wait(timeout=10)
                return NotificationWorker(conn,send,evaluation_mode=False).run_once()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run) for _ in range(2)]
            results=[future.result(timeout=30) for future in futures]
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(len(calls),1)
        self.assertEqual(self.status(),'accepted')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0],1)

    def test_contact_owner_change_blocks_dispatch_without_fallback(self):
        with self.conn:
            other=self.conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()[0]
            self.conn.execute('UPDATE contacts SET user_id=? WHERE id=(SELECT contact_id FROM notification_outbox WHERE id=?)',(other,self.job_id))
        sender=Mock()
        self.assertTrue(self.worker(sender).run_once())
        self.assertEqual(self.status(),'cancelled')
        sender.assert_not_called()

    def test_recovery_sql_keeps_postgres_parameters_typed_and_values_bound(self):
        from datetime import datetime,timezone
        from avenra.postgres import translate
        with self.conn:
            self.conn.execute("UPDATE notification_outbox SET status='processing',claim_token=NULL,claimed_at=NULL WHERE id=?",(self.job_id,))
        calls=[]; connection=self.conn
        class Capture:
            def execute(self,sql,params=()):
                calls.append((sql,params)); return connection.execute(sql,params)
        with self.conn:
            self.assertEqual(NotificationOutboxRepository(Capture()).mark_stale_unknown(datetime.now(timezone.utc)),1)
        update=next(sql for sql,_ in calls if sql.startswith('UPDATE notification_outbox'))
        postgres=translate(update)
        self.assertIn('avenra.notification_outbox',postgres)
        self.assertIn('CAST(%s AS TEXT) IS NULL',postgres)
        self.assertNotIn('julianday',postgres)
        self.assertTrue(any('LIMIT 100' in sql for sql,_ in calls))


class PushFailureTests(unittest.TestCase):
    setUp=push_fixtures.PushAPITests.setUp
    tearDown=push_fixtures.PushAPITests.tearDown
    setUpFixture=push_fixtures.PushAPITests.setUpFixture
    tearDownFixture=push_fixtures.PushAPITests.tearDownFixture
    csrf=push_fixtures.PushAPITests.csrf
    invite=push_fixtures.PushAPITests.invite
    accept=push_fixtures.PushAPITests.accept

    def prepare(self):
        self.accept()
        response=self.client.post('/api/alerts',json={'client_id':'stage10-fictional-push'},headers=self.survivor_headers)
        self.assertEqual(response.status_code,201)
        return response.json['id']

    def worker(self,conn,sender):
        from avenra.services.push_worker import PushWorker
        from avenra.services.push_service import PushSettings
        return PushWorker(conn,sender,PushSettings(),evaluation_mode=False)

    def test_push_provider_acceptance_with_failed_audit_is_never_resent(self):
        self.prepare(); sender=Mock(); sender.send.return_value={'outcome':'accepted','reason':'provider_accepted'}
        with closing(fixtures.db.connect()) as conn:
            with conn:
                conn.execute("CREATE TRIGGER fail_push_audit BEFORE INSERT ON audit_log WHEN NEW.action='push_accepted' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            with self.assertRaises(sqlite3.Error): self.worker(conn,sender).run_once()
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'processing')
            with conn: conn.execute("UPDATE notification_outbox SET claimed_at='2000-01-01T00:00:00Z'")
            self.assertEqual(NotificationWorker(conn,Mock(),evaluation_mode=False).recover_stale(),1)
            self.assertFalse(self.worker(conn,sender).run_once())
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'unknown')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM push_acknowledgements').fetchone()[0],1)
        sender.send.assert_called_once()

    def test_push_workers_racing_single_job_do_not_duplicate_send(self):
        self.prepare(); barrier=Barrier(2); sender=Mock()
        sender.send.return_value={'outcome':'accepted','reason':'provider_accepted'}
        def run():
            with closing(fixtures.db.connect()) as conn:
                worker=self.worker(conn,sender); barrier.wait(timeout=10)
                return worker.run_once()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run) for _ in range(2)]
            results=[future.result(timeout=30) for future in futures]
        self.assertEqual(sorted(results),[False,True]); sender.send.assert_called_once()

    def test_corrupt_subscription_fails_without_transport_or_secret_audit(self):
        self.prepare(); sender=Mock()
        with closing(fixtures.db.connect()) as conn:
            with conn: conn.execute("UPDATE push_subscriptions SET encrypted_subscription='fictional-corrupt-ciphertext'")
            self.assertTrue(self.worker(conn,sender).run_once()); sender.send.assert_not_called()
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'failed')
            details=' '.join(row[0] or '' for row in conn.execute('SELECT detail FROM audit_log'))
            self.assertNotIn('fictional-corrupt-ciphertext',details)

    def test_revocation_after_decrypt_is_rechecked_before_transport(self):
        from avenra.services.push_service import PushSettings
        from avenra.services.push_worker import PushWorker
        self.prepare(); sender=Mock()
        with closing(fixtures.db.connect()) as conn:
            settings=PushSettings(); original=settings.decrypt
            def decrypt(value):
                subscription=original(value)
                with conn: conn.execute('UPDATE push_subscriptions SET active=0')
                return subscription
            settings.decrypt=decrypt
            self.assertTrue(PushWorker(conn,sender,settings,evaluation_mode=False).run_once())
            sender.send.assert_not_called()
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'failed')


class AlertConcurrencyTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def test_simultaneous_same_client_id_creates_one_alert_and_one_outbox_set(self):
        barrier=Barrier(2)
        def send():
            client=fixtures.avenra_app.app.test_client()
            barrier.wait(timeout=10)
            response=client.post('/api/alerts',json={'client_id':'stage10-simultaneous-capture'},headers=self.survivor_headers)
            return response.status_code,response.json['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(send) for _ in range(2)]
            results=[future.result(timeout=30) for future in futures]
        self.assertEqual(sorted(code for code,_ in results),[200,201])
        self.assertEqual(len({identifier for _,identifier in results}),1)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],1)
            jobs=conn.execute('SELECT contact_id FROM notification_outbox').fetchall()
            self.assertGreater(len(jobs),0)
            self.assertEqual(len(jobs),len({row[0] for row in jobs}))
            self.assertTrue(all(row[0]=='pending' for row in conn.execute('SELECT status FROM notification_outbox')))
