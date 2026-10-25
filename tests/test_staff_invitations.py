from unittest.mock import patch
"""Staff invitation acceptance and security contracts; no real email."""
import re
import unittest
from contextlib import closing
from unittest.mock import Mock
import test_avenra as fixtures

class StaffInvitationTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def invite(self):
        from avenra.services.staff_invitation_service import issue_invitation
        sender = Mock()
        with closing(fixtures.db.connect()) as conn:
            issue_invitation(conn, email='invited@example.test', name='Invited colleague',
                             role='responder', org='Test organisation', base_url='https://avenra.example',
                             sender=sender)
        body = sender.call_args.args[2]
        return body.split('#')[1].split()[0]

    def csrf(self):
        page = self.client.get('/activate')
        self.assertEqual(page.status_code, 200)
        self.assertIn('no-store', page.headers['Cache-Control'])
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text).group(1)

    def activate(self, token, password='Q7!fern-River-Cloud-29'):
        return self.client.post('/activate', data={'token':token, 'password':password,
            'confirm_password':password, 'csrf_token':self.csrf()})

    def test_invitation_is_hashed_and_get_does_not_consume_it(self):
        token = self.invite()
        self.csrf(); self.csrf()
        with closing(fixtures.db.connect()) as conn:
            row = conn.execute('SELECT * FROM staff_invitations').fetchone()
            self.assertNotEqual(row['token_hash'], token)
            self.assertIsNone(row['used_at'])
            self.assertFalse(conn.execute("SELECT is_active FROM users WHERE email='invited@example.test'").fetchone()[0])

    def test_activation_signs_in_and_link_cannot_be_reused(self):
        token = self.invite()
        response = self.activate(token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/dashboard')
        with self.client.session_transaction() as session:
            self.assertIsInstance(session['user_id'], int)
        self.assertEqual(self.activate(token).status_code, 400)

    def test_resending_invalidates_previous_link(self):
        first = self.invite(); second = self.invite()
        self.assertEqual(self.activate(first).status_code, 400)
        self.assertEqual(self.activate(second).status_code, 302)

    def test_expired_or_tampered_token_cannot_activate(self):
        token = self.invite()
        with closing(fixtures.db.connect()) as conn:
            conn.execute('UPDATE staff_invitations SET expires_at=0'); conn.commit()
        for value in (token, token+'x', ''):
            self.assertEqual(self.activate(value).status_code, 400)

    def test_weak_password_does_not_consume_invitation(self):
        token = self.invite()
        self.assertEqual(self.activate(token, 'password').status_code, 400)
        self.assertEqual(self.activate(token).status_code, 302)

    def test_activation_requires_csrf_and_ignores_no_device_exemption(self):
        token = self.invite()
        r = self.client.post('/activate', data={'token':token,'password':'Q7!fern-River-Cloud-29'},
                             headers=self.survivor_headers)
        self.assertEqual(r.status_code, 400)

    def test_email_failure_revokes_new_invitation(self):
        from avenra.services.staff_invitation_service import issue_invitation
        with closing(fixtures.db.connect()) as conn:
            with self.assertRaises(RuntimeError):
                issue_invitation(conn,email='failed@example.test', name='Colleague',role='responder',
                    org='Test',base_url='https://avenra.example',sender=Mock(side_effect=OSError('private-smtp-error')))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM staff_invitations WHERE used_at IS NULL AND revoked_at IS NULL').fetchone()[0],0)

    def test_activated_account_can_use_normal_login(self):
        token = self.invite()
        self.assertEqual(self.activate(token).status_code, 302)
        self.client = fixtures.avenra_app.app.test_client()
        page = self.client.get('/login')
        csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text).group(1)
        response = self.client.post('/login',data={'email':'invited@example.test',
            'password':'Q7!fern-River-Cloud-29','csrf_token':csrf})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/dashboard').status_code,200)

    def test_concurrent_activation_consumes_token_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from avenra.services.staff_invitation_service import activate
        token = self.invite()
        def accept(_):
            with closing(fixtures.db.connect()) as conn:
                return activate(conn,token,'Q7!fern-River-Cloud-29','Q7!fern-River-Cloud-29')[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(accept, range(2)))
        self.assertEqual(sum(uid is not None for uid in ids),1)

    def test_audit_failure_rolls_back_activation(self):
        from avenra.services.staff_invitation_service import activate
        import sqlite3
        token = self.invite()
        with closing(fixtures.db.connect()) as conn:
            conn.execute("CREATE TRIGGER fail_activation_audit BEFORE INSERT ON audit_log WHEN NEW.action='staff_activated' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            conn.commit()
            with self.assertRaises(sqlite3.Error):
                activate(conn,token,'Q7!fern-River-Cloud-29','Q7!fern-River-Cloud-29')
            self.assertFalse(conn.execute("SELECT is_active FROM users WHERE email='invited@example.test'").fetchone()[0])
            self.assertIsNone(conn.execute('SELECT used_at FROM staff_invitations').fetchone()[0])

    def test_active_account_cannot_be_overwritten_by_invitation(self):
        from avenra.services.staff_invitation_service import issue_invitation
        token = self.invite(); self.activate(token)
        sender = Mock()
        with closing(fixtures.db.connect()) as conn:
            with self.assertRaises(ValueError):
                issue_invitation(conn,email='invited@example.test', name='Invited colleague',role='admin',
                    org='Test organisation',base_url='https://avenra.example',sender=sender)
        sender.assert_not_called()

    def test_invitee_cannot_choose_role_or_case_access(self):
        token = self.invite()
        response = self.client.post('/activate',data={'token':token,'password':'Q7!fern-River-Cloud-29',
            'confirm_password':'Q7!fern-River-Cloud-29','role':'admin','case_code':'SP-1042','csrf_token':self.csrf()})
        self.assertEqual(response.status_code,302)
        with closing(fixtures.db.connect()) as conn:
            user=conn.execute("SELECT id,role FROM users WHERE email='invited@example.test'").fetchone()
            self.assertEqual(user['role'],'responder')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM case_access WHERE staff_id=?',(user['id'],)).fetchone()[0],0)

    def test_deactivation_invalidates_pending_invitation_version(self):
        token = self.invite()
        with closing(fixtures.db.connect()) as conn:
            conn.execute("UPDATE users SET auth_version=auth_version+1 WHERE email='invited@example.test'"); conn.commit()
        self.assertEqual(self.activate(token).status_code,400)

    def test_activation_rate_limit_is_persistent(self):
        token = self.invite()
        for _ in range(20):
            self.assertEqual(self.activate('wrong','password').status_code,400)
        self.assertEqual(self.activate(token).status_code,429)

    @patch.dict('os.environ', {'PUBLIC_BASE_URL': 'https://localhost'})
    def test_https_activation_without_referer_requires_same_origin_and_csrf(self):
        token=self.invite()
        page=self.client.get('/activate',base_url='https://localhost')
        csrf=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        data={'token':token,'password':'Q7!fern-River-Cloud-29','confirm_password':'Q7!fern-River-Cloud-29','csrf_token':csrf}
        self.assertEqual(self.client.post('/activate',base_url='https://localhost',data=data).status_code,403)
        self.assertEqual(self.client.post('/activate',base_url='https://localhost',data=data,headers={'Origin':'https://foreign.example'}).status_code,403)
        self.assertEqual(self.client.post('/activate',base_url='https://localhost',data=data,headers={'Origin':'https://localhost'}).status_code,302)

    def test_operator_disable_revokes_invitation(self):
        token=self.invite()
        runner=fixtures.avenra_app.app.test_cli_runner()
        result=runner.invoke(args=['staff-disable','--email','invited@example.test'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(self.activate(token).status_code,400)

    def test_admin_and_shelter_invitations_land_in_correct_workspace(self):
        from avenra.services.staff_invitation_service import issue_invitation
        for role, destination in [('admin','/dashboard'),('shelter','/shelters')]:
            with self.subTest(role=role):
                sender=Mock()
                with closing(fixtures.db.connect()) as conn:
                    shelter_id=conn.execute('SELECT id FROM shelters ORDER BY id LIMIT 1').fetchone()[0] if role=='shelter' else None
                    issue_invitation(conn,email=role+'-invite@example.test',name='Test '+role,role=role,
                        org='Test organisation',shelter_id=shelter_id,base_url='https://avenra.example',sender=sender)
                token=sender.call_args.args[2].split('#')[1].split()[0]
                response=self.activate(token)
                self.assertEqual(response.status_code,302)
                self.assertEqual(response.location,destination)

    def test_invitation_does_not_depend_on_sqlite_lastrowid(self):
        from avenra.services.staff_invitation_service import issue_invitation
        from types import SimpleNamespace
        sender=Mock()
        with closing(fixtures.db.connect()) as real:
            conn=Mock(wraps=real)
            def execute(sql,params=()):
                cursor=real.execute(sql,params)
                if sql.lstrip().upper().startswith('INSERT'):
                    return SimpleNamespace(lastrowid=None)
                return cursor
            conn.execute.side_effect=execute
            uid=issue_invitation(conn,email='no-lastrowid@example.test',name='New colleague',role='admin',
                org='Test',base_url='https://avenra.example',sender=sender)
            self.assertEqual(real.execute('SELECT user_id FROM staff_invitations WHERE user_id=?',(uid,)).fetchone()['user_id'],uid)
            sender.assert_called_once()
