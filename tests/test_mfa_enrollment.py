"""Private, password-bound enrollment rendering and safe failure diagnostics."""
from contextlib import closing
import re
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

import pyotp
import test_avenra as fixtures
import test_stage8_mfa as mfa_fixtures
from avenra.services.mfa_service import MFAService, encryption


class MFAEnrollmentTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    begin = mfa_fixtures.StaffMFATests.begin
    submit = mfa_fixtures.StaffMFATests.submit
    enroll = mfa_fixtures.StaffMFATests.enroll

    def test_qr_payload_and_manual_key_use_the_existing_stored_secret(self):
        import qrcode
        email = 'staff+qr & label@example.test'
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE users SET email=? WHERE email='nomsa@avenra.demo'", (email,))
        page = self.client.get('/login')
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)[1]
        self.client.post('/login', data={'email': email, 'password': self.staff_password, 'csrf_token': token})
        with patch('qrcode.make', wraps=qrcode.make) as render:
            page = self.client.get('/mfa')
            self.assertEqual(render.call_count, 1)
            uri = render.call_args.args[0]
        secret = re.search(r'id="mfa-secret">([A-Z2-7]+)</code>', page.text)[1]
        parsed = urlsplit(uri)
        self.assertEqual((parsed.scheme, parsed.netloc), ('otpauth', 'totp'))
        self.assertEqual(unquote(parsed.path), '/Avenra:' + email)
        self.assertEqual(parse_qs(parsed.query), {'secret': [secret], 'issuer': ['Avenra']})
        self.assertEqual(uri, pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name='Avenra'))
        with fixtures.avenra_app.app.app_context(), closing(fixtures.db.connect()) as conn:
            stored = conn.execute('SELECT encrypted_secret FROM staff_mfa').fetchone()[0]
            self.assertEqual(encryption().decrypt(stored.encode()).decode(), secret)
        with patch('pyotp.random_base32', side_effect=AssertionError('Refresh must reuse the enrollment')):
            refreshed = self.client.get('/mfa')
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn(secret, refreshed.text)
        self.assertIn('<svg', page.text)
        self.assertIn('Can’t scan? Enter setup key', page.text)
        self.assertIn('no-store', page.headers['Cache-Control'])
        self.assertNotIn('otpauth:', page.text)
        self.assertNotRegex(page.text, r'(?:src|href)="https?://')

    def test_anonymous_expired_and_version_changed_challenges_cannot_disclose(self):
        response = self.client.get('/mfa')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('<svg', response.text)
        for mutation in ('UPDATE staff_mfa_challenges SET expires_at=0',
                         'UPDATE users SET auth_version=auth_version+1'):
            self.begin()
            with closing(fixtures.db.connect()) as conn, conn:
                conn.execute(mutation)
            response = self.client.get('/mfa')
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('id="mfa-secret"', response.text)
            self.assertNotIn('<svg', response.text)
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_confirmed_accounts_never_render_enrollment_details(self):
        secret, _ = self.enroll()
        self.client = fixtures.avenra_app.app.test_client()
        page = self.begin()
        self.assertNotIn(secret, page.text)
        self.assertNotIn('<svg', page.text)
        self.assertNotIn('id="mfa-secret"', page.text)
        self.assertIn('Verify staff sign-in', page.text)
        self.assertIn('css/login.css', page.text)

    def test_caught_failures_log_only_category_sqlstate_and_request_id(self):
        from cryptography.fernet import InvalidToken
        self.begin()
        sensitive = 'synthetic-sensitive-value-do-not-log'
        for exception, category in ((InvalidToken(sensitive), 'secret_unreadable'),
                                    (RuntimeError(sensitive), 'state_unavailable'),
                                    (sqlite3.OperationalError(sensitive), 'database_unavailable')):
            with patch.object(MFAService, 'view', side_effect=exception), self.assertLogs('avenra', level='WARNING') as logged:
                response = self.client.get('/mfa', headers={'X-Request-ID': sensitive})
            self.assertEqual(response.status_code, 503)
            self.assertIn(category, '\n'.join(logged.output))
            self.assertNotIn(sensitive, '\n'.join(logged.output))
            self.assertNotIn(sensitive, response.text)
            self.assertRegex(response.headers['X-Request-ID'], r'^[a-f0-9]{32}$')
            self.assertIn(response.headers['X-Request-ID'], '\n'.join(logged.output))
            self.assertNotIn('<svg', response.text)
