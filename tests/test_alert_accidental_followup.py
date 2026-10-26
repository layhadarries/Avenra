"""Accidental-alert annotations append history; they never cancel an alert."""
from contextlib import closing
import unittest
import re
import test_avenra as fixtures


class AccidentalFollowupTests(unittest.TestCase):
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    _staff_post = fixtures.avenraStagesTestCase._staff_post

    def setUp(self):
        fixtures.avenraStagesTestCase.setUp(self)
        response = self.client.post('/api/alerts', json={'client_id':'fictional-accidental'}, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 201)
        self.alert_id = response.json['id']
        self.url = f'/api/alerts/{self.alert_id}/workflow'
        self.body = {'action':'accidental', 'revision':0, 'reason':'Fictional verification follow-up; no dispatch cancellation.'}

    def snapshot(self):
        with closing(fixtures.db.connect()) as conn:
            return {table:[tuple(row) for row in conn.execute('SELECT * FROM '+table)]
                    for table in ('alerts','notification_outbox','alert_workflow','push_acknowledgements')}

    def test_annotation_is_audited_idempotent_and_preserves_delivery_and_lifecycle(self):
        self._login_staff('responder')
        before = self.snapshot()
        first = self._staff_post(self.url, json=self.body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self._staff_post(self.url, json=self.body)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json, second.json)
        self.assertEqual(self.snapshot(), before)
        with closing(fixtures.db.connect()) as conn:
            events = conn.execute("SELECT * FROM alert_history WHERE alert_id=? AND action='accidental'", (self.alert_id,)).fetchall()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event['detail'], self.body['reason'])
            self.assertTrue(event['created_at'])
            audit = conn.execute("SELECT * FROM audit_log WHERE action='alert_accidental'").fetchall()
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0]['actor'], f"user:{event['actor_id']}")
            self.assertIn(f'alert {self.alert_id}', audit[0]['detail'])
            self.assertIn(f"history {event['id']}", audit[0]['detail'])
        changed = dict(self.body, reason='Different retry must not rewrite history')
        self.assertEqual(self._staff_post(self.url, json=changed).status_code, 409)
        self.assertEqual(self._staff_post(f'/api/alerts/{self.alert_id}/acknowledge').status_code, 200)
        normal = self.client.post('/api/alerts', json={'client_id':'fictional-later-alert'}, headers=self.survivor_headers)
        self.assertEqual(normal.status_code, 201)

    def test_auth_assignment_revocation_and_invalid_identifiers(self):
        self.assertEqual(self.client.post(self.url, json=self.body).status_code, 400)  # Missing CSRF.
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', self.client.get('/login').text).group(1)
        self.assertEqual(self.client.post(self.url, json=self.body, headers={'X-CSRFToken':token}).status_code, 401)
        self._login_staff('shelter')
        self.assertEqual(self._staff_post(self.url, json=self.body).status_code, 403)
        self._login_staff('responder')
        self.assertEqual(self._staff_post(self.url, json=self.body).status_code, 200)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('DELETE FROM case_access')
        self.assertEqual(self._staff_post(self.url, json=self.body).status_code, 404)
        for selector in ('0','-1','9223372036854775808','invalid'):
            self.assertEqual(self._staff_post(f'/api/alerts/{selector}/workflow', json=self.body).status_code, 404)

    def test_reason_required_and_audit_failure_rolls_back_history(self):
        self._login_staff('responder')
        for reason in ('', ' ', 123, 'x'*501):
            self.assertEqual(self._staff_post(self.url, json={'action':'accidental','revision':0,'reason':reason}).status_code, 400)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("CREATE TRIGGER fail_followup BEFORE INSERT ON audit_log WHEN NEW.action='alert_accidental' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        self.assertEqual(self._staff_post(self.url, json=self.body).status_code, 503)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM alert_history WHERE action='accidental'").fetchone()[0], 0)

    def test_resolved_alert_history_and_prior_audit_are_immutable(self):
        self._login_staff('responder')
        self.assertEqual(self._staff_post(f'/api/alerts/{self.alert_id}/acknowledge').status_code, 200)
        revision = self.client.get('/api/alerts').json['alerts'][0]['revision']
        resolved = self._staff_post(self.url, json={'action':'resolve','revision':revision,'reason':'Fictional closure'})
        self.assertEqual(resolved.status_code, 200)
        with closing(fixtures.db.connect()) as conn:
            histories = [tuple(r) for r in conn.execute('SELECT * FROM alert_history ORDER BY id')]
            audits = [tuple(r) for r in conn.execute('SELECT * FROM audit_log ORDER BY id')]
        before = self.snapshot()
        self.assertEqual(self._staff_post(self.url, json=self.body).status_code, 200)
        self.assertEqual(self.snapshot(), before)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM alert_history ORDER BY id')][:-1], histories)
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM audit_log ORDER BY id')][:-1], audits)

    def test_concurrent_retries_append_exactly_one_followup(self):
        from concurrent.futures import ThreadPoolExecutor
        from avenra.repositories.portal_repository import PortalRepository
        from avenra.repositories.user_repository import UserRepository
        from avenra.services.portal_service import PortalService
        def submit(_):
            with closing(fixtures.db.connect()) as conn:
                actor_id = conn.execute("SELECT id FROM users WHERE role='responder' LIMIT 1").fetchone()[0]
                actor = UserRepository(conn).get_by_id(actor_id)
                return PortalService(PortalRepository(conn)).change_alert(self.alert_id, actor, self.body)
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(submit, range(4)))
        self.assertTrue(all(status == 200 for _, status in responses))
        self.assertTrue(all(body == responses[0][0] for body, _ in responses))
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM alert_history WHERE action='accidental'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='alert_accidental'").fetchone()[0], 1)
