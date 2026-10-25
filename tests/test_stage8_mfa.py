"""Mandatory staff MFA and bounded identity recovery; fictional local accounts only."""
from contextlib import closing
import re
import unittest
from unittest.mock import patch

import test_avenra as fixtures


class StaffMFATests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def begin(self, client=None):
        client=client or self.client
        page=client.get('/login')
        csrf=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        response=client.post('/login',data={'email':'nomsa@avenra.demo','password':self.staff_password,'csrf_token':csrf})
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/mfa')
        return client.get('/mfa')

    def submit(self, code, client=None):
        client=client or self.client
        page=client.get('/mfa')
        csrf=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        return client.post('/mfa',data={'code':code,'csrf_token':csrf})

    def enroll(self):
        page=self.begin()
        secret=re.search(r'id="mfa-secret">([A-Z2-7]+)</code>',page.text).group(1)
        import pyotp
        response=self.submit(pyotp.TOTP(secret).now())
        self.assertEqual(response.status_code,200,response.text)
        codes=re.findall(r'data-recovery-code>([a-f0-9]{32})</code>',response.text)
        self.assertEqual(len(codes),10)
        return secret,codes

    def test_password_alone_never_authorizes_staff(self):
        self.begin()
        self.assertEqual(self.client.get('/api/session').status_code,401)
        self.assertEqual(self.client.get('/dashboard').status_code,302)

    def test_enrollment_requires_password_and_csrf(self):
        self.assertEqual(self.client.get('/mfa').status_code,302)
        self.begin()
        self.assertEqual(self.client.post('/mfa',data={'code':'000000'}).status_code,400)
        self.assertEqual(self.client.get('/api/alerts').status_code,401)

    def test_confirmed_totp_and_codes_are_not_plaintext_in_database_or_cookie(self):
        secret,codes=self.enroll()
        self.assertEqual(self.client.get('/api/session').status_code,200)
        self.assertIn('no-store',self.client.get('/mfa').headers['Cache-Control'])
        with closing(fixtures.db.connect()) as conn:
            dump='\n'.join(conn.iterdump())
        for raw in [secret,*codes]:
            self.assertNotIn(raw,dump)
        with self.client.session_transaction() as session:
            self.assertNotIn(secret,str(dict(session)))
            self.assertTrue(session['mfa_verified'])

    def test_replayed_totp_and_used_recovery_code_cannot_log_in(self):
        secret,codes=self.enroll()
        self.client=fixtures.avenra_app.app.test_client()
        self.begin()
        import pyotp
        with closing(fixtures.db.connect()) as conn:
            counter=conn.execute('SELECT last_counter FROM staff_mfa').fetchone()[0]
        self.assertEqual(self.submit(pyotp.TOTP(secret).at(counter*30)).status_code,401)
        self.assertEqual(self.submit(codes[0]).status_code,302)
        self.client=fixtures.avenra_app.app.test_client(); self.begin()
        self.assertEqual(self.submit(codes[0]).status_code,401)
        self.assertEqual(self.submit(codes[1]).status_code,302)

    def test_expired_or_suspended_challenge_cannot_enroll(self):
        self.begin()
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('UPDATE staff_mfa_challenges SET expires_at=0')
        self.assertEqual(self.client.get('/mfa').status_code,302)
        self.begin()
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE users SET is_active=0 WHERE email='nomsa@avenra.demo'")
        self.assertEqual(self.client.get('/mfa').status_code,302)

    def test_mfa_failures_are_persistently_limited(self):
        self.begin()
        for _ in range(8): self.assertEqual(self.submit('not-a-valid-code').status_code,401)
        self.assertEqual(self.submit('not-a-valid-code').status_code,429)
        self.client=fixtures.avenra_app.app.test_client(); self.begin()
        self.assertEqual(self.submit('not-a-valid-code').status_code,429)

    def test_password_abuse_is_generic_and_persistently_limited(self):
        for _ in range(10):
            page=self.client.get('/login')
            csrf=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
            response=self.client.post('/login',data={'email':'nomsa@avenra.demo','password':'incorrect','csrf_token':csrf})
            self.assertEqual(response.status_code,401)
        page=self.client.get('/login')
        csrf=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        self.assertEqual(self.client.post('/login',data={'email':'nomsa@avenra.demo','password':self.staff_password,'csrf_token':csrf}).status_code,429)

    def test_operator_reset_invalidates_sessions_and_requires_new_enrollment(self):
        self.enroll()
        runner=fixtures.avenra_app.app.test_cli_runner()
        result=runner.invoke(args=['staff-mfa-reset','--email','nomsa@avenra.demo','--verification-reference','fictional-reviewed-ticket','--confirm'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(self.client.get('/api/session').status_code,401)
        page=self.begin()
        self.assertIn('id="mfa-secret"',page.text)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='staff_mfa_reset'").fetchone()[0],1)

    def test_recovery_consumption_is_atomic(self):
        _,codes=self.enroll()
        from concurrent.futures import ThreadPoolExecutor
        from avenra.services.mfa_service import MFAService
        clients=[fixtures.avenra_app.app.test_client(),fixtures.avenra_app.app.test_client()]
        nonces=[]
        for client in clients:
            self.begin(client)
            with client.session_transaction() as session: nonces.append(session['mfa_challenge'])
        def verify(nonce):
            with fixtures.avenra_app.app.test_request_context('/mfa'):
                with closing(fixtures.db.connect()) as conn:
                    return MFAService(conn).verify(nonce,codes[0])[0] is not None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(verify,nonces))
        self.assertEqual(results.count(True),1)

    def test_audit_failure_rolls_back_enrollment(self):
        page=self.begin()
        secret=re.search(r'id="mfa-secret">([A-Z2-7]+)</code>',page.text).group(1)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("CREATE TRIGGER fail_mfa_audit BEFORE INSERT ON audit_log WHEN NEW.action='staff_mfa_enrolled' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        import pyotp
        self.assertEqual(self.submit(pyotp.TOTP(secret).now()).status_code,503)
        self.assertEqual(self.client.get('/api/session').status_code,401)

    def test_production_requires_separate_mfa_key_and_rejects_evaluation(self):
        from flask import Flask
        from avenra.application import AvenraApplication
        from avenra.config import Config
        class Production(Config):
            APP_ENV='production'
            EVALUATION_MODE=False
            SESSION_COOKIE_SECURE=True
        with patch.dict('os.environ',{'STAFF_MFA_ENCRYPTION_KEY':''}):
            with self.assertRaisesRegex(RuntimeError,'STAFF_MFA_ENCRYPTION_KEY'):
                AvenraApplication(Production)._configure_app(Flask('key-check'))
        from cryptography.fernet import Fernet
        with patch.dict('os.environ',{'STAFF_MFA_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            AvenraApplication(Production)._configure_app(Flask('valid-key-check'))
            class InvalidEvaluation(Production): EVALUATION_MODE=True
            with self.assertRaisesRegex(RuntimeError,'Evaluation'):
                AvenraApplication(InvalidEvaluation)._configure_app(Flask('evaluation-check'))

    def test_abuse_storage_capacity_counters_and_expiry_are_bounded(self):
        from avenra.repositories.abuse_repository import AbuseRepository
        with closing(fixtures.db.connect()) as conn:
            repo=AbuseRepository(conn)
            self.assertTrue(repo.allow([('synthetic-a',2)],100,capacity=2))
            self.assertTrue(repo.allow([('synthetic-b',2)],100,capacity=2))
            self.assertFalse(repo.allow([('synthetic-c',2)],100,capacity=2))
            for _ in range(20): repo.allow([('synthetic-a',2)],100,capacity=2)
            self.assertEqual(conn.execute("SELECT attempts FROM auth_attempts WHERE bucket='synthetic-a'").fetchone()[0],3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM auth_attempts').fetchone()[0],2)
            self.assertTrue(repo.allow([('synthetic-c',2)],1001,capacity=2))

    def test_consumed_challenge_cookie_cannot_be_replayed(self):
        page=self.begin()
        with self.client.session_transaction() as session: old_nonce=session['mfa_challenge']
        secret=re.search(r'id="mfa-secret">([A-Z2-7]+)</code>',page.text).group(1)
        import pyotp
        self.assertEqual(self.submit(pyotp.TOTP(secret).now()).status_code,200)
        from avenra.services.mfa_service import MFAService
        with fixtures.avenra_app.app.test_request_context('/mfa'), closing(fixtures.db.connect()) as conn:
            self.assertIsNone(MFAService(conn).pending(old_nonce))

    def test_reset_requires_operator_confirmation(self):
        self.enroll()
        result=fixtures.avenra_app.app.test_cli_runner().invoke(args=['staff-mfa-reset','--email','nomsa@avenra.demo','--verification-reference','fictional-reviewed-ticket'])
        self.assertNotEqual(result.exit_code,0)
        self.assertEqual(self.client.get('/api/session').status_code,200)

    def test_non_staff_role_cannot_retain_a_staff_session(self):
        self.enroll()
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE users SET role='survivor' WHERE email='nomsa@avenra.demo'")
        self.assertEqual(self.client.get('/api/session').status_code,401)
