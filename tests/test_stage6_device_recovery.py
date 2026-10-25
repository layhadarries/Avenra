"""Recovery retains the original case and requires its explicit staff grant."""
import re
import unittest
import test_avenra as fixtures
import test_hosted_pwa_contract as pairing

class RecoveryTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown
    _login_staff=fixtures.avenraStagesTestCase._login_staff
    invite=pairing.HostedPWAContractTests.invite
    enroll=pairing.HostedPWAContractTests.enroll

    def recovery(self,case):
        csrf=re.search(r'name="csrf-token" content="([^"]+)"',self.client.get('/devices').text).group(1)
        return self.client.post('/api/device-invites',json={'case_code':case},headers={'X-CSRFToken':csrf})

    def test_recovery_keeps_owner_and_revokes_old_device(self):
        from urllib.parse import urlsplit
        phone,_=self.enroll(self.invite())
        owner=phone.get('/api/device').json['account_id']
        conn=fixtures.db.connect()
        try:case=conn.execute('SELECT case_code FROM users WHERE id=?',(owner,)).fetchone()[0]
        finally:conn.close()
        response=self.recovery(case)
        self.assertEqual(response.status_code,201,response.text)
        recovered,_=self.enroll(urlsplit(response.json['enrollment_url']).fragment)
        self.assertEqual(recovered.get('/api/device').json['account_id'],owner)
        self.assertEqual(phone.get('/api/device').status_code,401)

    def test_unassigned_case_cannot_be_recovered(self):
        self._login_staff('responder')
        self.assertEqual(self.recovery('AV-NOT-ASSIGNED').status_code,404)

    def test_revoked_assignment_invalidates_recovery_link(self):
        from urllib.parse import urlsplit
        phone,_=self.enroll(self.invite())
        owner=phone.get('/api/device').json['account_id']
        with fixtures.db.connect() as conn:
            case=conn.execute('SELECT case_code FROM users WHERE id=?',(owner,)).fetchone()[0]
        response=self.recovery(case)
        self.assertEqual(response.status_code,201)
        with fixtures.db.connect() as conn:conn.execute('DELETE FROM case_access WHERE survivor_id=?',(owner,))
        anonymous=fixtures.avenra_app.app.test_client()
        self.assertEqual(anonymous.post('/api/device/enroll',json={'token':urlsplit(response.json['enrollment_url']).fragment},headers={'Origin':'http://localhost'}).status_code,400)

    def test_existing_sqlite_pairing_table_is_upgraded_without_loss(self):
        with fixtures.db.connect() as conn:
            staff=conn.execute("SELECT id FROM users WHERE role='responder' LIMIT 1").fetchone()[0]
            conn.execute('DROP TABLE device_enrollments')
            conn.execute('CREATE TABLE device_enrollments(token_hash TEXT PRIMARY KEY,staff_id INTEGER NOT NULL REFERENCES users(id),expires_at INTEGER NOT NULL,consumed_at INTEGER)')
            conn.execute('INSERT INTO device_enrollments(token_hash,staff_id,expires_at) VALUES(?,?,?)',('synthetic-existing-hash',staff,2000000000))
        fixtures.db.init_db()
        with fixtures.db.connect() as conn:
            row=conn.execute('SELECT * FROM device_enrollments WHERE token_hash=?',('synthetic-existing-hash',)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn('user_id',row.keys())
            self.assertIsNone(row['user_id'])

    def test_staff_session_revocation_invalidates_device_invitation(self):
        token=self.invite()
        with fixtures.db.connect() as conn:
            conn.execute("UPDATE users SET auth_version=auth_version+1 WHERE role IN ('responder','admin')")
        phone=fixtures.avenra_app.app.test_client()
        response=phone.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,400)
