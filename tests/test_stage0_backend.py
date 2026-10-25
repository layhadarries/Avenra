"""Stage 0 backend gates. Every database is temporary and synthetic."""
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_avenra
import db
import seed

LEGACY_USERS = """CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, role TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
    password_hash TEXT, org TEXT, case_code TEXT UNIQUE, shelter_id INTEGER
);"""


class FoundationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(db, 'DB_PATH', str(Path(temporary.name) / 'nested' / 'data.sqlite3')))

    def test_suite_bootstrap_never_touches_a_preimported_database(self):
        import subprocess
        import sys
        target = str(Path(db.DB_PATH).parent / 'must-not-touch.sqlite3')
        env = dict(os.environ, DATABASE_PATH=target, APP_ENV='evaluation')
        code = "import sys; sys.path.insert(0, 'tests'); import db; import test_avenra; from pathlib import Path; assert not Path(" + repr(target) + ").exists()"
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_schema_contains_security_columns_and_core_tables(self):
        db.init_db()
        conn = db.connect()
        try:
            tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(set(test_avenra.avenra_app.COUNT_TABLES) <= tables)
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
            self.assertTrue({'is_active', 'auth_version'} <= columns)
            self.assertTrue(conn.execute('SELECT version FROM schema_migrations').fetchall())
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        finally:
            conn.close()
        if os.name == 'posix':
            self.assertEqual(Path(db.DB_PATH).stat().st_mode & 0o777, 0o600)

    def test_reinitialising_preserves_accounts_and_activation(self):
        Path(db.DB_PATH).parent.mkdir(parents=True)
        conn = sqlite3.connect(db.DB_PATH)
        conn.executescript(LEGACY_USERS)
        conn.execute("INSERT INTO users(name,role,email) VALUES ('Existing','admin','existing@example.test')")
        conn.commit(); conn.close()
        db.init_db()
        conn = db.connect()
        conn.execute('UPDATE users SET is_active=1,auth_version=7'); conn.commit(); conn.close()
        db.init_db()
        conn = db.connect()
        try:
            row = conn.execute('SELECT * FROM users').fetchone()
            self.assertEqual((row['name'], row['is_active'], row['auth_version']), ('Existing', 1, 7))
        finally:
            conn.close()

    def test_migration_cli_backs_up_before_changing_old_schema(self):
        import contextlib
        import io
        import migrate_staff_security
        Path(db.DB_PATH).parent.mkdir(parents=True)
        conn = sqlite3.connect(db.DB_PATH)
        conn.executescript(LEGACY_USERS)
        conn.execute("INSERT INTO users(name,role,email) VALUES ('Existing','admin','existing@example.test')")
        conn.commit(); conn.close()
        old_mask = os.umask(0o077)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                migrate_staff_security.main()
        finally:
            os.umask(old_mask)
        backups = list((Path(db.DB_PATH).parent / 'private-backups').glob('*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with contextlib.closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute('SELECT name FROM users').fetchone()[0], 'Existing')
            self.assertNotIn('is_active', {row[1] for row in backup.execute('PRAGMA table_info(users)')})
        with contextlib.closing(db.connect()) as upgraded:
            self.assertEqual(upgraded.execute('SELECT is_active FROM users').fetchone()[0], 0)

    def test_seed_is_idempotent_and_does_not_reactivate_staff(self):
        db.init_db()
        seed.prepare_evaluation_database()
        conn = db.connect()
        conn.execute("UPDATE users SET is_active=0 WHERE role='responder'")
        conn.commit(); conn.close()
        seed.prepare_evaluation_database()
        conn = db.connect()
        try:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT is_active FROM users WHERE role='responder'").fetchone()[0], 0)
            self.assertIsNone(conn.execute("SELECT password_hash FROM users WHERE role='survivor'").fetchone()[0])
        finally:
            conn.close()

    def test_evaluation_seed_refuses_an_existing_unmarked_database(self):
        db.init_db()
        conn = db.connect()
        conn.execute("INSERT INTO users(name,role,email) VALUES ('Existing','admin','existing@example.test')")
        conn.commit(); conn.close()
        with self.assertRaises(RuntimeError):
            seed.prepare_evaluation_database()


class EvaluationNotificationTests(unittest.TestCase):
    def test_evaluation_cannot_send_even_with_a_provider_configured(self):
        from flask import Flask
        import sms
        app = Flask(__name__)
        app.config['EVALUATION_MODE'] = True
        with app.app_context(), patch.dict(os.environ, {'SMS_WEBHOOK_URL': 'https://example.test/sms'}), patch('urllib.request.urlopen') as transport:
            result = sms.send_single('Fictional', '+27 00 000 0001', 'Test', 'SP-1042')
        transport.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertEqual(result['channel'], 'evaluation_disabled')


class EvaluationRoutesTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown

    def token(self):
        html = self.client.get('/login').get_data(as_text=True)
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)

    def test_health_does_not_expose_counts_in_normal_mode(self):
        self.assertEqual(self.client.get('/health').json, {'status': 'ok'})

    def test_evaluation_route_is_disabled_by_default(self):
        response = self.client.post('/evaluation/login/responder', data={'csrf_token': self.token()})
        self.assertEqual(response.status_code, 404)

    def test_evaluation_mode_alone_cannot_open_existing_fixture_accounts(self):
        with patch.dict(test_avenra.avenra_app.app.config, {'EVALUATION_MODE': True}):
            response = self.client.post('/evaluation/login/responder', data={'csrf_token': self.token()})
            self.assertEqual(response.status_code, 403)

    def test_proven_synthetic_evaluation_allows_only_approved_roles_and_csrf(self):
        # Separate empty database; ordinary fixture databases must not be relabelled.
        with tempfile.TemporaryDirectory() as directory, patch.object(db, 'DB_PATH', str(Path(directory) / 'evaluation.sqlite3')):
            db.init_db()
            seed.prepare_evaluation_database()
            with patch.dict(test_avenra.avenra_app.app.config, {'EVALUATION_MODE': True}):
                self.assertEqual(self.client.post('/evaluation/login/responder').status_code, 400)
                self.assertEqual(self.client.post('/evaluation/login/responder', data={'csrf_token': self.token()}).status_code, 302)
                self.assertEqual(self.client.get('/api/alerts').status_code, 401)
                from mfa_fixture import complete_mfa
                complete_mfa(self)
                self.assertEqual(self.client.get('/api/alerts').status_code, 200)
                self.client = test_avenra.avenra_app.app.test_client()
                self.assertEqual(self.client.post('/evaluation/login/admin', data={'csrf_token': self.token()}).status_code, 404)
                self.assertEqual(self.client.get('/health').json['counts']['users'], 4)


if __name__ == '__main__':
    unittest.main()
