"""A late emergency fix must not recreate an alert, escape consent, or change workflow."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import test_avenra as fixtures
import test_hosted_pwa_contract as pairing


class AlertLocationUpdateTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    invite = pairing.HostedPWAContractTests.invite
    enroll = pairing.HostedPWAContractTests.enroll

    def phone(self):
        phone, _ = self.enroll(self.invite())
        owner = phone.get('/api/device').json['account_id']
        return phone, owner

    def consent(self, phone, active):
        response = phone.post('/api/consents', json={'item':'location_sharing','active':active}, headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,200,response.text)

    def permission(self, phone):
        response = phone.get('/api/alerts/location-permission')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('no-store',response.headers.get('Cache-Control',''))
        return response.json

    def create(self, phone, owner, client_id='tap-location-fixture', **extra):
        response = phone.post('/api/alerts',json={'client_id':client_id, **extra},headers={'Origin':'http://localhost','X-Queue-Owner':str(owner)})
        self.assertEqual(response.status_code,201,response.text)
        return response.json

    def fix(self, token, seconds=-5):
        return {'lat':-33.9249,'lng':18.4241,'location_accuracy':24.5,
                'location_recorded_at':(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='microseconds'),
                'location_consent_token':token}

    def update(self, phone, owner, payload, client_id='tap-location-fixture'):
        return phone.post('/api/alerts/by-client/'+client_id+'/location',json=payload,
                          headers={'Origin':'http://localhost','X-Queue-Owner':str(owner)})

    def state(self, alert_id):
        with fixtures.db.connect() as conn:
            alert = dict(conn.execute('SELECT * FROM alerts WHERE id=?',(alert_id,)).fetchone())
            jobs = [dict(row) for row in conn.execute('SELECT * FROM notification_outbox WHERE alert_id=?',(alert_id,))]
            count = conn.execute('SELECT COUNT(*) FROM alerts').fetchone()[0]
        return alert, jobs, count

    def test_authorised_late_fix_preserves_receipt_outbox_and_acknowledgement(self):
        phone, owner = self.phone(); self.consent(phone,True)
        self.assertEqual(phone.post('/api/contacts',json={'name':'Fictional contact','phone':'0821234567'},headers={'Origin':'http://localhost'}).status_code,201)
        receipt = self.create(phone,owner)
        with fixtures.db.connect() as conn:
            conn.execute("UPDATE alerts SET status='acknowledged',acknowledged_by='Fictional responder',acknowledged_at='2026-01-01T12:00:00Z' WHERE id=?",(receipt['id'],))
        before, jobs, count = self.state(receipt['id'])
        permission = self.permission(phone)
        response = self.update(phone,owner,self.fix(permission['token']))
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json['updated'])
        after, after_jobs, after_count = self.state(receipt['id'])
        self.assertAlmostEqual(after['lat'],-33.9249)
        self.assertEqual(after['location_accuracy'],24.5)
        for field in ('id','client_id','created_at','status','acknowledged_at','acknowledged_by'):
            self.assertEqual(after[field],before[field],field)
        self.assertEqual(after_jobs,jobs)
        self.assertEqual(after_count,count)

    def test_repeat_is_idempotent_and_older_or_conflicting_fixes_are_rejected(self):
        phone, owner = self.phone(); self.consent(phone,True); self.create(phone,owner)
        payload = self.fix(self.permission(phone)['token'])
        self.assertTrue(self.update(phone,owner,payload).json['updated'])
        replay = self.update(phone,owner,payload)
        self.assertEqual(replay.status_code,200)
        self.assertFalse(replay.json['updated'])
        self.assertEqual(self.update(phone,owner,self.fix(payload['location_consent_token'],-10)).status_code,409)
        self.assertEqual(self.update(phone,owner,dict(payload,lat=-34)).status_code,409)
        with fixtures.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='alert_location_updated'").fetchone()[0],1)

    def test_withdrawal_and_regrant_invalidate_prior_permission(self):
        phone, owner = self.phone(); self.consent(phone,True); self.create(phone,owner)
        old = self.permission(phone)
        self.consent(phone,False)
        self.assertFalse(self.permission(phone)['allowed'])
        self.assertEqual(self.update(phone,owner,self.fix(old['token'])).status_code,403)
        self.consent(phone,True)
        self.assertEqual(self.update(phone,owner,self.fix(old['token'])).status_code,403)
        self.assertNotEqual(self.permission(phone)['grant'],old['grant'])

    def test_cross_account_and_revoked_device_are_rejected(self):
        first, owner = self.phone(); self.consent(first,True); receipt=self.create(first,owner)
        token = self.permission(first)['token']
        second, other = self.phone(); self.consent(second,True)
        self.assertEqual(self.update(second,other,self.fix(self.permission(second)['token'])).status_code,404)
        self.assertEqual(self.update(second,owner,self.fix(token)).status_code,409)
        with fixtures.db.connect() as conn:
            conn.execute('UPDATE survivor_devices SET revoked_at=1 WHERE user_id=?',(owner,))
        self.assertEqual(self.update(first,owner,self.fix(token)).status_code,401)
        self.assertIsNone(self.state(receipt['id'])[0]['lat'])

    def test_malformed_stale_unknown_and_future_location_are_rejected(self):
        phone, owner = self.phone(); self.consent(phone,True); self.create(phone,owner)
        payload = self.fix(self.permission(phone)['token'])
        for invalid in [dict(payload,status='resolved'),dict(payload,lat=True),dict(payload,lat='-33'),
                        dict(payload,location_accuracy=-1),dict(payload,location_accuracy=1001),
                        dict(payload,location_accuracy=float('nan')),dict(payload,lat=91),
                        dict(payload,location_recorded_at='2026-01-01T12:00:00'),
                        self.fix(payload['location_consent_token'],-180),self.fix(payload['location_consent_token'],3600)]:
            with self.subTest(invalid=invalid): self.assertEqual(self.update(phone,owner,invalid).status_code,400)

    def test_expired_capability_and_wrong_origin_are_rejected(self):
        phone, owner = self.phone(); self.consent(phone,True); self.create(phone,owner)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=1):
            token=self.permission(phone)['token']
        self.assertEqual(self.update(phone,owner,self.fix(token)).status_code,403)
        response=phone.post('/api/alerts/by-client/tap-location-fixture/location',json=self.fix(token),
            headers={'Origin':'https://foreign.invalid','X-Queue-Owner':str(owner)})
        self.assertEqual(response.status_code,403)

    def test_permission_is_bound_to_actual_device_and_late_window(self):
        phone, owner = self.phone(); self.consent(phone,True)
        receipt = self.create(phone,owner)
        payload = self.fix(self.permission(phone)['token'])
        # A second enrolled device on the same account still cannot reuse tokens.
        import hashlib
        with fixtures.db.connect() as conn:
            row = conn.execute('SELECT * FROM survivor_devices WHERE user_id=?',(owner,)).fetchone()
            conn.execute('INSERT INTO survivor_devices(user_id,token_hash,expires_at) VALUES(?,?,?)',
                (owner,hashlib.sha256(b'fictional-second-device').hexdigest(),row['expires_at']))
        second = fixtures.avenra_app.app.test_client()
        second.set_cookie('avenra_device','fictional-second-device')
        self.assertEqual(self.update(second,owner,payload).status_code,403)
        with fixtures.db.connect() as conn:
            conn.execute("UPDATE alerts SET created_at='2020-01-01T00:00:00Z' WHERE id=?",(receipt['id'],))
        self.assertEqual(self.update(phone,owner,payload).status_code,409)

    def test_permission_route_requires_pairing_not_demo_header(self):
        self.assertEqual(self.client.get('/api/alerts/location-permission',headers=self.survivor_headers).status_code,401)

    def test_initial_tap_fix_requires_current_capability_but_alert_always_saves(self):
        phone, owner = self.phone(); self.consent(phone,True)
        token=self.permission(phone)['token']
        valid=self.create(phone,owner,**self.fix(token))
        self.assertTrue(valid['location_shared'])
        self.consent(phone,False); self.consent(phone,True)
        stale=self.create(phone,owner,client_id='tap-expired-grant',**self.fix(token))
        self.assertFalse(stale['location_shared'])
        missing=self.fix(token); del missing['location_consent_token']
        self.assertFalse(self.create(phone,owner,client_id='tap-no-capability',**missing)['location_shared'])
        oversized = self.fix(token); oversized['lat'] = 10 ** 400
        self.assertFalse(self.create(phone,owner,client_id='tap-oversized-coordinate',**oversized)['location_shared'])
