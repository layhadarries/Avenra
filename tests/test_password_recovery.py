"""Password recovery preserves MFA and never sends real mail."""
import unittest
from contextlib import closing
from unittest.mock import Mock
import test_avenra as fixtures

class PasswordRecoveryTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def prepare(self):
        from avenra.services.staff_invitation_service import issue_invitation, activate
        sender=Mock()
        conn=fixtures.db.connect()
        issue_invitation(conn,email='recover@example.test',name='Staff',role='admin',org='Test',base_url='https://staff.example',sender=sender)
        token=sender.call_args.args[2].split('#')[1].split()[0]
        activate(conn,token,'Q7!fern-River-Cloud-29','Q7!fern-River-Cloud-29')
        return conn

    def test_reset_is_single_use_and_invalidates_sessions(self):
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            service=PasswordRecoveryService(conn); sender=Mock()
            uid=conn.execute("SELECT id FROM users WHERE email='recover@example.test'").fetchone()[0]
            conn.execute("INSERT INTO staff_mfa(user_id,encrypted_secret,confirmed_at,enrollment_expires_at) VALUES(?,'synthetic-encrypted-secret',1,0)",(uid,));conn.commit()
            before=conn.execute("SELECT auth_version FROM users WHERE email='recover@example.test'").fetchone()[0]
            service.request('recover@example.test','https://staff.example',sender)
            token=sender.call_args.args[2].split('#')[1].split()[0]
            self.assertIsNone(service.reset(token,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))
            self.assertIsNotNone(service.reset(token,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))
            self.assertEqual(conn.execute("SELECT auth_version FROM users WHERE email='recover@example.test'").fetchone()[0],before+1)
            self.assertEqual(conn.execute('SELECT encrypted_secret FROM staff_mfa WHERE user_id=?',(uid,)).fetchone()[0],'synthetic-encrypted-secret')
            from werkzeug.security import check_password_hash
            self.assertTrue(check_password_hash(conn.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone()[0],'J9!New-River-Cloud-47'))

    def test_unknown_account_sends_nothing(self):
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            sender=Mock(); PasswordRecoveryService(conn).request('absent@example.test','https://staff.example',sender)
            sender.assert_not_called()

    def test_weak_password_does_not_consume_and_invitation_cannot_reset(self):
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            service=PasswordRecoveryService(conn); sender=Mock()
            service.request('recover@example.test','https://staff.example',sender)
            token=sender.call_args.args[2].split('#')[1].split()[0]
            self.assertIsNotNone(service.reset(token,'weak','weak'))
            self.assertIsNotNone(service.reset('x'*43,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))
            self.assertIsNone(service.reset(token,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))

    def test_forgot_page_requires_csrf_and_is_private(self):
        page=self.client.get('/forgot-password')
        self.assertEqual(page.status_code,200)
        self.assertIn('no-store',page.headers['Cache-Control'])
        self.assertEqual(self.client.post('/forgot-password',data={'email':'absent@example.test'}).status_code,400)

    def test_expiry_resend_and_disabled_account(self):
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            service=PasswordRecoveryService(conn); sender=Mock()
            service.request('recover@example.test','https://staff.example',sender)
            first=sender.call_args.args[2].split('#')[1].split()[0]
            service.request('recover@example.test','https://staff.example',sender)
            second=sender.call_args.args[2].split('#')[1].split()[0]
            self.assertIsNotNone(service.reset(first,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))
            conn.execute('UPDATE staff_invitations SET expires_at=0');conn.commit()
            self.assertIsNotNone(service.reset(second,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))
            service.request('recover@example.test','https://staff.example',sender)
            third=sender.call_args.args[2].split('#')[1].split()[0]
            conn.execute("UPDATE users SET is_active=0 WHERE email='recover@example.test'");conn.commit()
            self.assertIsNotNone(service.reset(third,'J9!New-River-Cloud-47','J9!New-River-Cloud-47'))

    def test_failed_email_revokes_and_audit_failure_rolls_back(self):
        import sqlite3
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            service=PasswordRecoveryService(conn)
            with self.assertRaises(RuntimeError):
                service.request('recover@example.test','https://staff.example',Mock(side_effect=OSError('synthetic')))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM staff_invitations WHERE used_at IS NULL AND revoked_at IS NULL').fetchone()[0],0)
            sender=Mock();service.request('recover@example.test','https://staff.example',sender)
            token=sender.call_args.args[2].split('#')[1].split()[0]
            before=conn.execute("SELECT password_hash,auth_version FROM users WHERE email='recover@example.test'").fetchone()
            conn.execute("CREATE TRIGGER fail_reset_audit BEFORE INSERT ON audit_log WHEN NEW.action='staff_password_reset' BEGIN SELECT RAISE(ABORT,'synthetic'); END");conn.commit()
            with self.assertRaises(sqlite3.Error):
                service.reset(token,'J9!New-River-Cloud-47','J9!New-River-Cloud-47')
            after=conn.execute("SELECT password_hash,auth_version FROM users WHERE email='recover@example.test'").fetchone()
            self.assertEqual(tuple(before),tuple(after))

    def test_https_recovery_requires_exact_origin(self):
        import re
        from unittest.mock import patch
        with patch.dict('os.environ',{'PUBLIC_BASE_URL':'https://localhost'}):
            page=self.client.get('/forgot-password',base_url='https://localhost')
            csrf=re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)
            data={'email':'absent@example.test','csrf_token':csrf}
            self.assertEqual(self.client.post('/forgot-password',base_url='https://localhost',data=data).status_code,403)
            self.assertEqual(self.client.post('/forgot-password',base_url='https://localhost',data=data,headers={'Origin':'https://other.example'}).status_code,403)
            self.assertEqual(self.client.post('/forgot-password',base_url='https://localhost',data=data,headers={'Origin':'https://localhost'}).status_code,200)

    def test_concurrent_reset_consumes_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from avenra.services.password_recovery_service import PasswordRecoveryService
        with closing(self.prepare()) as conn:
            sender=Mock();PasswordRecoveryService(conn).request('recover@example.test','https://staff.example',sender)
            token=sender.call_args.args[2].split('#')[1].split()[0]
        def attempt(_):
            with closing(fixtures.db.connect()) as conn:
                return PasswordRecoveryService(conn).reset(token,'J9!New-River-Cloud-47','J9!New-River-Cloud-47')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(result is None for result in results),1)
