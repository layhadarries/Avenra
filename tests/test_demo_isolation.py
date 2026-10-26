"""Production rejects fixture databases rather than filtering/relabeling history."""
from contextlib import closing
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import test_avenra as fixtures
from avenra.services.notification_worker import NotificationWorker
from avenra.services.push_worker import PushWorker


class DemoIsolationTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff

    def test_production_reporting_rejects_unmarked_legacy_demo_database(self):
        self._login_staff('responder')
        app = fixtures.avenra_app.app
        with patch.dict(app.config, APP_ENV='production', EVALUATION_MODE=False):
            for path in ('/api/alerts','/cases','/api/audit-log','/referrals','/api/diary'):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503, path)
                self.assertNotIn('SP-1042', response.text)
                self.assertIn('no-store', response.headers['Cache-Control'])

    def test_production_workers_cannot_claim_or_send_legacy_demo_jobs(self):
        response = self.client.post('/api/alerts', json={'client_id':'fictional-demo-delivery'}, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 201)
        with closing(fixtures.db.connect()) as conn:
            before = [tuple(r) for r in conn.execute('SELECT * FROM notification_outbox')]
            sender = Mock()
            with patch.dict(os.environ, APP_ENV='production'):
                self.assertFalse(NotificationWorker(conn, sender, evaluation_mode=False).run_once())
                self.assertFalse(PushWorker(conn, sender, Mock(), evaluation_mode=False).run_once())
            sender.assert_not_called()
            sender.send.assert_not_called()
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM notification_outbox')], before)

    def test_production_seed_refuses_without_mutating_database(self):
        with closing(fixtures.db.connect()) as conn:
            before = [tuple(r) for r in conn.execute('SELECT * FROM users')]
        with patch.dict(os.environ, APP_ENV='production'):
            with self.assertRaises(RuntimeError):
                fixtures.seed.seed()
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM users')], before)

    def test_production_startup_refuses_fixture_database(self):
        from cryptography.fernet import Fernet
        from avenra.application import AvenraApplication
        from avenra.config import Config
        class Production(Config):
            APP_ENV = 'production'
            EVALUATION_MODE = False
            SESSION_COOKIE_SECURE = True
        with patch.dict(os.environ, STAFF_MFA_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            with self.assertRaisesRegex(RuntimeError, 'refuses a demo database'):
                AvenraApplication(Production).create_app()

    def test_separate_operational_database_still_reports_and_delivers_to_fake_sender(self):
        from avenra.services.environment_isolation_service import EnvironmentIsolationService
        from avenra.services.portal_service import PortalService
        from avenra.repositories.portal_repository import PortalRepository
        from avenra.repositories.user_repository import UserRepository
        path = str(Path(self.tmp_dir.name)/'separate-operational.sqlite3')
        with patch.object(fixtures.db, 'DB_PATH', path):
            fixtures.db.init_db()
            with closing(fixtures.db.connect()) as conn:
                with conn:
                    conn.execute("INSERT INTO users(id,name,role,email,case_code,is_active) VALUES(1,'Fictional operational survivor','survivor','operational@example.invalid','TEST-OP-1',1)")
                    conn.execute("INSERT INTO users(id,name,role,email,is_active) VALUES(2,'Fictional operational staff','responder','staff@example.invalid',1)")
                    conn.execute('INSERT INTO case_access(staff_id,survivor_id) VALUES(2,1)')
                    conn.execute("INSERT INTO contacts(id,user_id,name,phone,channel) VALUES(1,1,'Fictional contact','+27000000001','sms')")
                    conn.execute("INSERT INTO alerts(id,user_id,case_code,client_id) VALUES(1,1,'TEST-OP-1','isolated-operational-alert')")
                    conn.execute('INSERT INTO notification_outbox(alert_id,contact_id) VALUES(1,1)')
                sender = Mock(return_value={'outcome':'accepted'})
                with patch.dict(os.environ, APP_ENV='production'):
                    self.assertTrue(EnvironmentIsolationService(conn).compatible())
                    actor = UserRepository(conn).get_by_id(2)
                    result, status = PortalService(PortalRepository(conn)).list_alerts(actor, {})
                    self.assertEqual(status, 200)
                    self.assertEqual([a['case_code'] for a in result['alerts']], ['TEST-OP-1'])
                    self.assertTrue(NotificationWorker(conn, sender, evaluation_mode=False).run_once())
                sender.assert_called_once()
