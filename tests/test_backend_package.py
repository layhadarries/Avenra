"""Import/startup gates for the complete Avenra backend; no email or SMS sent."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BackendPackageTests(unittest.TestCase):
    def run_app(self, code, **settings):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, SECRET_KEY='test-only-package-key-never-deploy-0123456789',
                       APP_ENV='development', COOKIE_SECURE='0',
                       DATABASE_PATH=str(Path(directory)/'data.sqlite3'),
                       UPLOADS_DIR=str(Path(directory)/'uploads'))
            for key in ('SMS_WEBHOOK_URL','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID'):
                env.pop(key, None)
            env.update(settings)
            return subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                  env=env, capture_output=True, text=True, timeout=25)

    def assert_success(self, code, **settings):
        result = self.run_app(code, **settings)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_complete_package_starts_with_empty_database(self):
        self.assert_success("import app; assert app.app.test_client().get('/health').json == {'status':'ok'}")

    def test_normal_startup_does_not_create_demo_accounts(self):
        self.assert_success("import app,db; conn=db.connect(); assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0; conn.close()")

    def test_missing_secret_is_rejected(self):
        result = self.run_app('import app', SECRET_KEY='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Set SECRET_KEY', result.stderr)

    def test_production_rejects_insecure_cookies(self):
        result = self.run_app('import app', APP_ENV='production', COOKIE_SECURE='0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Production requires', result.stderr)

    def test_signed_out_staff_cannot_read_alerts_or_consents(self):
        self.assert_success("import app; c=app.app.test_client(); assert c.get('/api/alerts').status_code == 401; assert c.get('/api/consents').status_code == 401")

    def test_explicit_evaluation_initialises_only_fictional_accounts(self):
        self.assert_success("import app; c=app.app.test_client(); assert c.get('/health').json['counts']['users']==4; assert c.get('/evaluation').status_code==200", APP_ENV='evaluation')

if __name__ == '__main__':
    unittest.main()
