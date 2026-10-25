"""Hosted PWA acceptance contract. Synthetic database; missing routes are expected reds."""
import re
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch
import test_avenra as fixtures

class HostedPWAContractTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown
    _login_staff=fixtures.avenraStagesTestCase._login_staff

    def invite(self):
        self._login_staff('responder')
        page=self.client.get('/dashboard')
        csrf=re.search(r'name="csrf-token" content="([^"]+)"',page.text).group(1)
        response=self.client.post('/api/device-invites',json={},headers={'X-CSRFToken':csrf})
        self.assertEqual(response.status_code,201,response.text)
        url=response.json['enrollment_url']
        self.assertTrue(urlsplit(url).fragment)
        self.assertFalse(urlsplit(url).query)
        return urlsplit(url).fragment

    def enroll(self,token,client=None):
        client=client or fixtures.avenra_app.app.test_client()
        response=client.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,201,response.text)
        return client,response

    def test_install_page_is_public_and_neutral(self):
        r=self.client.get('/survivor/install.html')
        self.assertEqual(r.status_code,200)
        self.assertIn('Clear Sky',r.text)
        self.assertIn('manifest',r.text)
        self.assertNotIn('demo-device',r.text)
        r.close()

    def test_signed_out_cannot_create_enrollment(self):
        r=self.client.post('/api/device-invites',json={})
        self.assertIn(r.status_code,(400,401))
        self.assertNotEqual(r.status_code,404)

    def test_enrollment_is_one_use_and_token_not_returned_as_device_secret(self):
        token=self.invite()
        client,response=self.enroll(token)
        self.assertNotIn(token,response.text)
        for key in ('device_token','access_token','password'):
            self.assertNotIn(key,response.json)
        other=fixtures.avenra_app.app.test_client()
        self.assertEqual(other.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'}).status_code,400)
        self.assertEqual(client.get('/api/device').status_code,200)

    def test_staff_cookie_alone_does_not_authenticate_device(self):
        self._login_staff()
        self.assertEqual(self.client.get('/api/device').status_code,401)

    def test_device_cookie_is_httponly(self):
        _,response=self.enroll(self.invite())
        self.assertIn('HttpOnly',response.headers.get('Set-Cookie',''))
        self.assertIn('SameSite=Strict',response.headers.get('Set-Cookie',''))

    def test_own_alert_reaches_assigned_staff(self):
        phone, _ = self.enroll(self.invite())
        owner = phone.get("/api/device").get_json()["account_id"]

        response = phone.post(
            "/api/alerts",
            json={"client_id": "hosted-alert-one"},
            headers={
                "Origin": "http://localhost",
                "X-Queue-Owner": str(owner),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        listing = self.client.get("/api/alerts")
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(
            any(
                alert["id"] == response.get_json()["id"]
                for alert in listing.get_json()["alerts"]
            )
        )

    def test_two_devices_do_not_share_contacts(self):
        first,_=self.enroll(self.invite())
        second,_=self.enroll(self.invite())
        r=first.post('/api/contacts',json={'contacts':[{'name':'Synthetic contact','phone':'+27821234567'}]},headers={'Origin':'http://localhost'})
        self.assertEqual(r.status_code,200)
        self.assertNotIn('Synthetic contact',second.get('/api/contacts').text)

    def test_cross_origin_enrollment_is_rejected(self):
        token=self.invite()
        other=fixtures.avenra_app.app.test_client()
        r=other.post('/api/device/enroll',json={'token':token},headers={'Origin':'https://foreign.example'})
        self.assertEqual(r.status_code,403)

    def test_cross_origin_cookie_write_is_rejected(self):
        phone,_=self.enroll(self.invite())
        r=phone.post('/api/alerts',json={'client_id':'cross-origin'},headers={'Origin':'https://foreign.example'})
        self.assertEqual(r.status_code,403)

    def test_device_api_never_cached(self):
        self.assertIn('no-store',self.client.get('/api/device').headers.get('Cache-Control',''))

    @patch('avenra.config.Config.APP_ENV','production')
    def test_shared_demo_header_is_not_production_authority(self):
        r=self.client.get('/api/contacts',headers=self.survivor_headers)
        self.assertEqual(r.status_code,401)

    def test_enrollment_rejects_missing_origin(self):
        token=self.invite()
        client=fixtures.avenra_app.app.test_client()
        response=client.post('/api/device/enroll',json={'token':token})
        self.assertEqual(response.status_code,403)

    def test_enrollment_rejects_malformed_tokens(self):
        client=fixtures.avenra_app.app.test_client()
        for token in (None, True, 12, '', 'x'*129):
            with self.subTest(token=token):
                response=client.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'})
                self.assertEqual(response.status_code,400)

    def test_enrollment_cannot_select_identity(self):
        token=self.invite()
        client=fixtures.avenra_app.app.test_client()
        response=client.post('/api/device/enroll',json={'token':token,'survivor_id':1,'role':'admin'},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,400)

    def test_pairing_requires_staff_csrf(self):
        self._login_staff('responder')
        response=self.client.post('/api/device-invites',json={})
        self.assertEqual(response.status_code,400)

    def test_cookie_write_without_origin_is_rejected(self):
        client,_=self.enroll(self.invite())
        response=client.post('/api/alerts',json={'client_id':'missing-origin'})
        self.assertEqual(response.status_code,403)

    def test_enrollment_response_cannot_be_cached(self):
        _,response=self.enroll(self.invite())
        self.assertIn('no-store',response.headers.get('Cache-Control',''))

    def test_manifest_has_standalone_same_origin_scope(self):
        response=self.client.get('/survivor/manifest.json')
        self.assertEqual(response.status_code,200)
        manifest=response.get_json(force=True)
        response.close()
        self.assertEqual(manifest['display'],'standalone')
        self.assertEqual(manifest['scope'],'/survivor/')
        self.assertTrue(manifest['start_url'].startswith('/survivor/'))
        self.assertFalse(urlsplit(manifest['start_url']).netloc)

    def test_expired_invitation_cannot_be_used(self):
        token=self.invite()
        with fixtures.db.connect() as conn:
            conn.execute('UPDATE device_enrollments SET expires_at=0')
        phone=fixtures.avenra_app.app.test_client()
        self.assertEqual(phone.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'}).status_code,400)

    def test_raw_pairing_and_cookie_secrets_are_not_stored(self):
        token=self.invite()
        phone,response=self.enroll(token)
        cookie=phone.get_cookie('avenra_device').value
        conn=fixtures.db.connect()
        try:
            rows=[dict(row) for row in conn.execute('SELECT * FROM device_enrollments')]
            rows += [dict(row) for row in conn.execute('SELECT * FROM survivor_devices')]
        finally:
            conn.close()
        self.assertNotIn(token,str(rows))
        self.assertNotIn(cookie,str(rows))

    def test_revoked_cookie_does_not_fall_back_to_demo_token(self):
        phone,_=self.enroll(self.invite())
        with fixtures.db.connect() as conn:
            conn.execute('UPDATE survivor_devices SET revoked_at=1')
        self.assertEqual(phone.get('/api/contacts',headers=self.survivor_headers).status_code,401)

    def test_audit_failure_rolls_back_enrollment(self):
        token=self.invite()
        with fixtures.db.connect() as conn:
            conn.execute("CREATE TRIGGER fail_pairing BEFORE INSERT ON audit_log WHEN NEW.action='device_enrolled' BEGIN SELECT RAISE(ABORT, 'synthetic_failure'); END")
        phone=fixtures.avenra_app.app.test_client()
        response=phone.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('synthetic_failure',response.text)
        conn=fixtures.db.connect()
        try:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM survivor_devices').fetchone()[0],0)
            self.assertIsNone(conn.execute('SELECT consumed_at FROM device_enrollments').fetchone()[0])
        finally:
            conn.close()

    def test_already_paired_device_cannot_switch_owner(self):
        phone,_=self.enroll(self.invite())
        token=self.invite()
        response=phone.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,409)

    def test_secure_cookie_on_https(self):
        token=self.invite()
        with patch.dict(fixtures.avenra_app.app.config,SESSION_COOKIE_SECURE=True):
            phone=fixtures.avenra_app.app.test_client()
            response=phone.post('/api/device/enroll',base_url='https://localhost',json={'token':token},headers={'Origin':'https://localhost'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertIn('Secure',response.headers['Set-Cookie'])

    def test_pairing_attempts_are_rate_limited(self):
        phone=fixtures.avenra_app.app.test_client()
        statuses=[phone.post('/api/device/enroll',json={'token':'x'*43},headers={'Origin':'http://localhost'}).status_code for _ in range(21)]
        self.assertEqual(statuses[-1],429)

    def test_staff_can_open_pairing_controls(self):
        self._login_staff('responder')
        response=self.client.get('/devices')
        self.assertEqual(response.status_code,200)
        self.assertIn('id="create-device-invite"',response.text)
        response.close()

    def test_shelter_cannot_open_pairing_controls(self):
        self._login_staff('shelter')
        self.assertEqual(self.client.get('/devices').status_code,403)

    def test_concurrent_enrollment_consumes_link_once(self):
        from concurrent.futures import ThreadPoolExecutor
        token=self.invite()
        def attempt(_):
            phone=fixtures.avenra_app.app.test_client()
            return phone.post('/api/device/enroll',json={'token':token},headers={'Origin':'http://localhost'}).status_code
        with ThreadPoolExecutor(max_workers=2) as workers:
            statuses=list(workers.map(attempt,range(2)))
        self.assertEqual(sorted(statuses),[201,400])
        conn=fixtures.db.connect()
        try:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM survivor_devices').fetchone()[0],1)
        finally:
            conn.close()

    def test_operator_revocation_blocks_existing_cookie(self):
        phone,_=self.enroll(self.invite())
        owner=phone.get('/api/device').json['account_id']
        conn=fixtures.db.connect()
        try:
            case=conn.execute('SELECT case_code FROM users WHERE id=?',(owner,)).fetchone()[0]
        finally:
            conn.close()
        result=fixtures.avenra_app.app.test_cli_runner().invoke(args=['device-revoke','--case-code',case])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(phone.get('/api/device').status_code,401)
