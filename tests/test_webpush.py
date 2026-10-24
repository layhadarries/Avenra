"""Web Push contracts: isolated fixtures, fake transport, no external messages."""
import base64
from contextlib import closing, contextmanager
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_avenra
import db
from avenra.repositories.push_repository import PushRepository
from avenra.services.push_service import validate_subscription, PushError


@contextmanager
def connection():
    with closing(db.connect()) as conn:
        with conn:
            yield conn

def subscription(endpoint='https://fcm.googleapis.com/fcm/send/test-token'):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    public=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    encode=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    return {'endpoint':endpoint,'keys':{'p256dh':encode(public),'auth':encode(b'x'*16)}}

class SubscriptionTests(unittest.TestCase):
    def test_accepts_known_provider_and_valid_keys(self):
        self.assertEqual(validate_subscription(subscription())['endpoint'],'https://fcm.googleapis.com/fcm/send/test-token')
    def test_rejects_ssrf_endpoints(self):
        for url in ('http://fcm.googleapis.com/send/x','https://127.0.0.1/x','https://localhost/x',
                    'https://fcm.googleapis.com.evil.test/x','https://evil@fcm.googleapis.com/x',
                    'https://fcm.googleapis.com:8443/x','https://fcm.googleapis.com/x#fragment'):
            with self.subTest(url=url), self.assertRaises(PushError):validate_subscription(subscription(url))
    def test_rejects_invalid_keys(self):
        data=subscription();data['keys']['auth']='bad'
        with self.assertRaises(PushError):validate_subscription(data)
    def test_rejects_oversized_or_non_object_input(self):
        for value in (None,[],{'endpoint':'x'*4096}):
            with self.subTest(value=type(value)),self.assertRaises(PushError):validate_subscription(value)

class PushAPITests(unittest.TestCase):
    setUpFixture=test_avenra.avenraStagesTestCase.setUp
    tearDownFixture=test_avenra.avenraStagesTestCase.tearDown
    def setUp(self):
        self.setUpFixture()
        from avenra.services.push_service import generate_keys
        self.key_dir=Path(self.tmp_dir.name)/'push-keys';generate_keys(self.key_dir)
        self.env=patch.dict(os.environ,{'AVENRA_WEBPUSH_ENABLED':'1','WEBPUSH_KEY_DIR':str(self.key_dir),
            'WEBPUSH_SUBJECT':'mailto:developer@example.test','AVENRA_SMS_ENABLED':'0'})
        self.env.start()
        self.contacts=self.client.get('/api/contacts',headers=self.survivor_headers).json['contacts']
        self.contact_id=self.contacts[0]['id']
    def tearDown(self):self.env.stop();self.tearDownFixture()
    def csrf(self):
        response=self.client.get('/contact-push/')
        import re
        return re.search(r'name="csrf-token" content="([^"]+)"',response.text).group(1)
    def invite(self,contact_id=None):
        return self.client.post('/api/contacts/'+str(contact_id or self.contact_id)+'/push-invite',
            headers=self.survivor_headers,json={})
    def accept(self):
        invite=self.invite();self.assertEqual(invite.status_code,201,invite.text)
        token=invite.json['invite_token']
        result=self.client.post('/api/contact-push/accept',headers={'X-CSRFToken':self.csrf()},
            json={'invite_token':token,'subscription':subscription()})
        self.assertEqual(result.status_code,201,result.text)
        return token,result.json
    def test_invite_needs_device_authority(self):
        self.assertEqual(self.client.post('/api/contacts/1/push-invite',json={}).status_code,401)
    def test_unknown_contact_cannot_be_invited(self):
        self.assertEqual(self.invite(999999).status_code,404)
    def test_invite_is_hashed_expires_and_is_one_use(self):
        token,_=self.accept()
        with connection() as conn:
            row=conn.execute('SELECT * FROM push_invites').fetchone()
            self.assertNotIn(token,str(tuple(row)))
        self.assertEqual(self.client.post('/api/contact-push/accept',headers={'X-CSRFToken':self.csrf()},
            json={'invite_token':token,'subscription':subscription()}).status_code,404)
    def test_expired_invite_is_rejected(self):
        result=self.invite()
        with connection() as conn:conn.execute("UPDATE push_invites SET expires_at='2000-01-01T00:00:00Z'")
        self.assertEqual(self.client.post('/api/contact-push/accept',headers={'X-CSRFToken':self.csrf()},
            json={'invite_token':result.json['invite_token'],'subscription':subscription()}).status_code,404)
    def test_https_uses_secure_host_cookie_without_referrer(self):
        token=self.invite().json['invite_token']
        csrf=self.csrf()
        response=self.client.post('/api/contact-push/accept',base_url='https://localhost',
            headers={'X-CSRFToken':csrf,'Origin':'https://localhost'},
            json={'invite_token':token,'subscription':subscription()})
        self.assertEqual(response.status_code,201,response.text)
        cookie=response.headers.get('Set-Cookie','')
        self.assertIn('__Host-avenra_push_browser=',cookie)
        self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Strict',cookie)
    def test_https_rejects_missing_origin_even_with_valid_csrf(self):
        token=self.invite().json['invite_token']
        response=self.client.post('/api/contact-push/accept',base_url='https://localhost',
            headers={'X-CSRFToken':self.csrf()},json={'invite_token':token,'subscription':subscription()})
        self.assertEqual(response.status_code,403)

    def test_accept_requires_csrf(self):
        token=self.invite().json['invite_token']
        self.assertEqual(self.client.post('/api/contact-push/accept',json={'invite_token':token,'subscription':subscription()}).status_code,400)
    def test_cross_origin_accept_is_rejected(self):
        token=self.invite().json['invite_token']
        self.assertEqual(self.client.post('/api/contact-push/accept',headers={'X-CSRFToken':self.csrf(),'Origin':'https://evil.test'},
            json={'invite_token':token,'subscription':subscription()}).status_code,403)
    def test_subscription_is_encrypted_and_contact_channel_changes(self):
        self.accept()
        with connection() as conn:
            row=conn.execute('SELECT * FROM push_subscriptions').fetchone()
            self.assertNotIn('fcm.googleapis.com',row['encrypted_subscription'])
            self.assertEqual(conn.execute('SELECT channel FROM contacts WHERE id=?',(self.contact_id,)).fetchone()[0],'webpush')
        response=self.client.get('/api/contact-push/subscriptions')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('endpoint',response.text);self.assertNotIn('phone',response.text)
    def test_new_invite_replaces_old_link(self):
        old=self.invite().json['invite_token'];self.invite()
        response=self.client.post('/api/contact-push/accept',headers={'X-CSRFToken':self.csrf()},json={'invite_token':old,'subscription':subscription()})
        self.assertEqual(response.status_code,404)
    def test_other_browser_cannot_unsubscribe(self):
        _,body=self.accept()
        other=test_avenra.avenra_app.app.test_client()
        import re
        csrf=re.search(r'name="csrf-token" content="([^"]+)"',other.get('/contact-push/').text).group(1)
        response=other.post('/api/contact-push/unsubscribe',headers={'X-CSRFToken':csrf},json={'subscription_id':body['subscription_id']})
        self.assertEqual(response.status_code,404)
    def test_contact_can_revoke_subscription(self):
        _,body=self.accept()
        response=self.client.post('/api/contact-push/unsubscribe',headers={'X-CSRFToken':self.csrf()},json={'subscription_id':body['subscription_id']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/contact-push/subscriptions').json['subscriptions'],[])
    def test_contact_delete_cascades_subscription(self):
        self.accept()
        self.client.delete('/api/contacts/'+str(self.contact_id),headers=self.survivor_headers)
        with connection() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0],0)
    def test_invite_rate_limit(self):
        for _ in range(5):self.assertEqual(self.invite().status_code,201)
        self.assertEqual(self.invite().status_code,429)
    def test_pages_and_api_are_private_and_token_is_not_in_path(self):
        page=self.client.get('/contact-push/')
        self.assertIn('no-store',page.headers['Cache-Control'])
        self.assertEqual(page.headers['Referrer-Policy'],'no-referrer')
        self.assertIn('Content-Security-Policy',page.headers)
        self.assertNotIn('invite_token',page.text)
    def test_self_test_requires_opt_in_and_limits_repeat_sends(self):
        _,body=self.accept()
        with patch.dict(os.environ,{'AVENRA_PUSH_SELF_TEST':'1'}), patch('avenra.services.webpush_sender.WebPushSender.send',return_value={'outcome':'accepted','reason':'provider_accepted'}) as sender:
            response=self.client.post('/api/contact-push/test',headers={'X-CSRFToken':self.csrf()},json={'subscription_id':body['subscription_id']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json['outcome'],'accepted')
            again=self.client.post('/api/contact-push/test',headers={'X-CSRFToken':self.csrf()},json={'subscription_id':body['subscription_id']})
            self.assertEqual(again.status_code,429)
            sender.assert_called_once()

    def test_self_test_is_explicit_disabled_by_default(self):
        _,body=self.accept()
        with patch.dict(os.environ,{'AVENRA_PUSH_SELF_TEST':'0'}):
            response=self.client.post('/api/contact-push/test',headers={'X-CSRFToken':self.csrf()},json={'subscription_id':body['subscription_id']})
            self.assertEqual(response.status_code,404)

class PushDispatchTests(unittest.TestCase):
    setUpFixture=PushAPITests.setUpFixture
    tearDownFixture=PushAPITests.tearDownFixture
    setUp=PushAPITests.setUp
    tearDown=PushAPITests.tearDown
    csrf=PushAPITests.csrf
    invite=PushAPITests.invite
    accept=PushAPITests.accept
    def alert(self):
        response=self.client.post('/api/alerts',headers=self.survivor_headers,json={'client_id':'push-alert'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json['id']
    def test_push_mode_queues_only_accepted_contacts(self):
        self.accept();alert=self.alert()
        with connection() as conn:
            jobs=list(conn.execute('SELECT * FROM notification_outbox WHERE alert_id=?',(alert,)))
            self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['contact_id'],self.contact_id)
    def test_sending_is_not_done_during_alert_creation(self):
        self.accept()
        with patch('avenra.services.webpush_sender.WebPushSender.send') as sender:self.alert();sender.assert_not_called()
    def test_push_claim_does_not_steal_sms_jobs(self):
        self.accept();self.alert()
        from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
        with connection() as conn:
            self.assertIsNone(NotificationOutboxRepository(conn).claim_next(channel='sms'))
            self.assertIsNotNone(NotificationOutboxRepository(conn).claim_next(channel='webpush'))
    def test_evaluation_database_never_dispatches_alerts(self):
        self.accept();self.alert()
        from avenra.services.push_worker import PushWorker
        from avenra.services.push_service import PushSettings
        from unittest.mock import Mock
        with connection() as conn:
            conn.execute("INSERT OR REPLACE INTO app_metadata(key,value) VALUES('evaluation_fixture','1')");conn.commit()
            sender=Mock();worker=PushWorker(conn,sender,PushSettings(),evaluation_mode=False)
            self.assertFalse(worker.run_once());sender.send.assert_not_called()
    def test_worker_commits_before_network_and_ack_is_separate(self):
        self.accept();alert=self.alert()
        from avenra.services.push_worker import PushWorker
        from avenra.services.push_service import PushSettings
        import sqlite3
        owner=self
        class Sender:
            link=None
            def send(sender,subscription,url):
                self.assertFalse(conn.in_transaction)
                with connection() as other:self.assertEqual(other.execute("SELECT status FROM notification_outbox WHERE alert_id=?",(alert,)).fetchone()[0],'processing')
                sender.link=url
                return {'outcome':'accepted','reason':'provider_accepted'}
        sender=Sender()
        with connection() as conn:
            worker=PushWorker(conn,sender,PushSettings(),evaluation_mode=False)
            self.assertTrue(worker.run_once());self.assertFalse(worker.run_once())
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox WHERE alert_id=?',(alert,)).fetchone()[0],'accepted')
            self.assertIsNone(conn.execute('SELECT acknowledged_at FROM push_acknowledgements').fetchone()[0])
        response=self.client.post('/api/contact-push/acknowledge',headers={'X-CSRFToken':self.csrf()},json={'token':sender.link.split('=')[1]})
        self.assertEqual(response.status_code,200,response.text)
        with connection() as conn:
            self.assertIsNotNone(conn.execute('SELECT acknowledged_at FROM push_acknowledgements').fetchone()[0])
            self.assertEqual(conn.execute('SELECT status FROM alerts WHERE id=?',(alert,)).fetchone()[0],'new')
    def test_worker_timeout_becomes_unknown_without_retry(self):
        self.accept();self.alert()
        from avenra.services.push_worker import PushWorker
        from avenra.services.push_service import PushSettings
        from unittest.mock import Mock
        sender=Mock();sender.send.side_effect=TimeoutError('private-endpoint')
        with connection() as conn:
            worker=PushWorker(conn,sender,PushSettings(),evaluation_mode=False)
            self.assertTrue(worker.run_once());self.assertFalse(worker.run_once())
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'unknown')
        self.assertEqual(sender.send.call_count,1)
    def test_revoked_subscription_cannot_dispatch_or_ack(self):
        _,body=self.accept();self.alert()
        from avenra.services.push_worker import PushWorker
        from avenra.services.push_service import PushSettings
        from unittest.mock import Mock
        with connection() as conn:
            conn.execute('UPDATE push_subscriptions SET active=0');conn.commit()
            sender=Mock();worker=PushWorker(conn,sender,PushSettings(),evaluation_mode=False)
            self.assertTrue(worker.run_once());sender.send.assert_not_called()
            self.assertEqual(conn.execute('SELECT status FROM notification_outbox').fetchone()[0],'cancelled')
        response=self.client.post('/api/contact-push/acknowledge',headers={'X-CSRFToken':self.csrf()},json={'token':'x'*43})
        self.assertEqual(response.status_code,404)
    def test_neutral_sender_payload_and_acceptance_only(self):
        from avenra.services.webpush_sender import WebPushSender
        from avenra.services.push_service import PushSettings
        from unittest.mock import Mock
        transport=Mock(return_value=Mock(status_code=201))
        result=WebPushSender(PushSettings(),transport).send(subscription(),'/contact-push/')
        self.assertEqual(result['outcome'],'accepted')
        call=transport.call_args.kwargs
        body=json.loads(call['data'])
        self.assertEqual(body,{'title':'Notification','body':'You have a new notification.','url':'/contact-push/'})
        self.assertEqual(call['ttl'],300);self.assertEqual(call['timeout'],10)
        self.assertFalse(call['requests_session'].trust_env)
    def test_real_push_encryption_with_fake_network(self):
        from avenra.services.webpush_sender import WebPushSender
        from avenra.services.push_service import PushSettings
        from pywebpush import webpush
        from unittest.mock import Mock
        import requests
        network=Mock()
        response=requests.Response();response.status_code=201;response._content=b''
        network.post.return_value=response
        def transport(**kwargs):
            kwargs['requests_session']=network
            return webpush(**kwargs)
        result=WebPushSender(PushSettings(),transport).send(subscription())
        self.assertEqual(result['outcome'],'accepted')
        body=network.post.call_args.kwargs['data']
        self.assertIsInstance(body,bytes)
        self.assertNotIn(b'You have a new notification',body)
        self.assertIn('authorization',{k.lower():v for k,v in network.post.call_args.kwargs['headers'].items()})

    def test_sender_timeout_does_not_expose_endpoint(self):
        from avenra.services.webpush_sender import WebPushSender
        from avenra.services.push_service import PushSettings
        from unittest.mock import Mock
        result=WebPushSender(PushSettings(),Mock(side_effect=TimeoutError('private-endpoint'))).send(subscription())
        self.assertEqual(result,{'outcome':'unknown','reason':'transport_uncertain'})

if __name__=='__main__':unittest.main()
