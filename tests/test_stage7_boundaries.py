"""Stage 7: hostile inputs cross actual HTTP/storage/SQL trust boundaries."""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_avenra as fixtures
from avenra.repositories.portal_repository import PortalRepository
from avenra.repositories.user_repository import UserRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.services.diary_service import LocalDiaryStorage
from avenra.models.user import User


class SecurityBoundaryTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    _staff_post = fixtures.avenraStagesTestCase._staff_post

    def test_alert_pagination_and_filter_ids_are_bounded(self):
        self._login_staff()
        for query in ('page='+str(10**100), 'snapshot='+str(2**63), 'assignee='+str(2**63)):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/alerts?'+query).status_code,400)

    def test_audit_pagination_is_bounded(self):
        self._login_staff()
        self.assertEqual(self.client.get('/api/audit-log?page='+str(10**100)).status_code,400)

    def test_oversized_route_ids_do_not_reach_database(self):
        for path in ('/api/diary/{}/photo','/api/diary/{}','/api/alerts/{}/status'):
            with self.subTest(path=path):
                response=self.client.get(path.format(2**100),headers=self.survivor_headers)
                self.assertEqual(response.status_code,404)
                self.assertIn('no-store',response.headers['Cache-Control'])

    def test_referral_ids_are_json_integers_not_coercible_selectors(self):
        self._login_staff()
        for value in (True,1.2,'1',float('inf'),2**100):
            with self.subTest(value=value):
                response=self._staff_post('/api/referrals',json={'alert_id':value,'shelter_id':1})
                self.assertEqual(response.status_code,400)

    def test_local_media_does_not_follow_symlinks_or_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); vault=root/'vault'; vault.mkdir()
            private=root/'private'; private.write_bytes(b'fictional private bytes')
            (vault/'diary_link.jpg').symlink_to(private)
            with self.assertRaises(OSError): LocalDiaryStorage(str(vault)).get_object('diary_link.jpg')

    def test_dynamic_count_identifiers_are_allowlisted(self):
        with closing(fixtures.db.connect()) as conn:
            with patch('avenra.config.Config.COUNT_TABLES',['sqlite_master']):
                with self.assertRaises(ValueError): AuditRepository(conn).table_counts()

    def test_body_identifiers_cannot_overflow_repositories(self):
        from avenra.repositories.push_repository import PushRepository
        with closing(fixtures.db.connect()) as conn:
            self.assertIsNone(PushRepository(conn).owned(2**100,'x'*43))
        self._login_staff('admin')
        for value in (True,2**100):
            self.assertEqual(self._staff_post('/api/cases/SP-1042/access',
                json={'action':'grant','staff_id':value}).status_code,400)

    def test_injection_payloads_stay_bound_across_repository_filters(self):
        attack="' OR 1=1; DROP TABLE users; --"
        with closing(fixtures.db.connect()) as real:
            conn=Mock(wraps=real)
            self.assertIsNone(UserRepository(conn).get_by_email(attack))
            staff=User.from_row(real.execute("SELECT * FROM users WHERE role='responder' LIMIT 1").fetchone())
            owner=real.execute("SELECT survivor_id FROM case_access WHERE staff_id=? LIMIT 1",(staff.id,)).fetchone()[0]
            real.execute("INSERT INTO alerts(user_id,case_code,client_id) SELECT id,case_code,'stage7-injection-fixture' FROM users WHERE id=?",(owner,))
            repo=PortalRepository(conn)
            self.assertEqual(repo.alert_page(staff.id,{'per_page':25,'page':1})[1],1)
            rows,total=repo.alert_page(staff.id,{'q':attack,'per_page':25,'page':1})
            self.assertEqual((rows,total),([],0))
            self.assertEqual(repo.audit_page(staff,{'q':attack,'case_code':attack})['events'],[])
            for call in conn.execute.call_args_list:
                sql=call.args[0]
                self.assertNotIn(attack,sql)
                if len(call.args)>1:
                    from avenra.postgres import translate
                    self.assertNotIn(attack,translate(sql))
            self.assertGreater(real.execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
            self.assertTrue(any(attack in call.args[1] for call in conn.execute.call_args_list if len(call.args)>1))

    def test_revoked_assignment_blocks_case_and_staff_api(self):
        self._login_staff()
        with self.client.session_transaction() as session: uid=session['user_id']
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('DELETE FROM case_access WHERE staff_id=?',(uid,))
        self.assertEqual(self.client.get('/cases/SP-1042').status_code,404)
        self.assertEqual(self.client.get('/api/alerts').json['alerts'],[])
        self.assertEqual(self.client.get('/api/diary?case_code=SP-1042').status_code,404)

    def test_shelter_cannot_query_staff_alerts_or_audit(self):
        self._login_staff('shelter')
        for path in ('/api/alerts','/api/audit-log','/cases/SP-1042'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,403)
            self.assertIn('no-store',response.headers['Cache-Control'])

    def test_template_escapes_untrusted_staff_and_case_text(self):
        self._login_staff()
        attack='<img src=x onerror=alert(1)>'
        with self.client.session_transaction() as session: uid=session['user_id']
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('UPDATE users SET name=? WHERE id=?',(attack,uid))
        page=self.client.get('/dashboard')
        self.assertNotIn(attack,page.text)
        self.assertIn('&lt;img',page.text)

    def test_pairing_invite_rate_limit_survives_requests(self):
        self._login_staff()
        for _ in range(10):
            self.assertEqual(self._staff_post('/api/device-invites',json={}).status_code,201)
        self.assertEqual(self._staff_post('/api/device-invites',json={}).status_code,429)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT attempts FROM device_pairing_attempts WHERE bucket LIKE 'staff:%'").fetchone()[0],11)

    def test_missing_worker_credentials_never_dispatch(self):
        with patch('avenra.services.push_worker.PushWorker.run_once',side_effect=AssertionError('must not dispatch')):
            self.assertEqual(self.client.post('/api/worker/tick',json={}).status_code,401)
