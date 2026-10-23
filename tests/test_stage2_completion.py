"""Stage 2 boundary tests. All provider transport is mocked."""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock,patch
import test_avenra
from avenra.services.sms_sender import TwilioSender,SenderConfigurationError
from avenra.services.notification_worker import NotificationWorker
from avenra.services.notification_status_service import NotificationStatusService

class SenderTests(unittest.TestCase):
    def setUp(self):
        self.env={'AVENRA_SMS_ENABLED':'1','APP_ENV':'development',
            'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'test-only-secret',
            'TWILIO_FROM_NUMBER':'+15005550006'}
        self.opener=Mock()
    def send(self,payload):
        response=io.BytesIO(json.dumps(payload).encode());response.status=201
        self.opener.open.return_value=response
        return TwilioSender(self.env,self.opener)(name='Test',phone='+27821234567',message='Test only',case_code='TEST')
    def test_explicit_enablement_required(self):
        for env in ({},{**self.env,'AVENRA_SMS_ENABLED':'0'},{**self.env,'APP_ENV':'evaluation'}):
            with self.subTest(env=env):
                with self.assertRaises(SenderConfigurationError):TwilioSender(env,self.opener)
        self.opener.open.assert_not_called()
    def test_configuration_failure_does_not_use_network(self):
        with self.assertRaises(SenderConfigurationError):
            TwilioSender({**self.env,'TWILIO_AUTH_TOKEN':''},self.opener)
        self.opener.open.assert_not_called()
    def test_queue_acceptance_stores_sid_but_not_delivery(self):
        result=self.send({'sid':'SM'+'b'*32,'status':'queued'})
        self.assertEqual(result['outcome'],'accepted')
        self.assertEqual(result['provider_message_id'],'SM'+'b'*32)
        request=self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.twilio.com/2010-04-01/Accounts/AC'+'a'*32+'/Messages.json')
        self.assertEqual(request.method,'POST')
        self.assertEqual(self.opener.open.call_count,1)
    def test_timeout_has_no_retry_or_channel_fallback(self):
        self.opener.open.side_effect=TimeoutError('secret provider body')
        result=self.send({'sid':'SM'+'b'*32,'status':'queued'})
        self.assertEqual(result['outcome'],'unknown')
        self.assertNotIn('secret',str(result));self.opener.open.assert_called_once()
    def test_http_rejection_does_not_expose_body(self):
        self.opener.open.side_effect=urllib.error.HTTPError('https://api.twilio.com',401,'private-secret',{},io.BytesIO(b'private-secret'))
        result=self.send({})
        self.assertEqual(result['outcome'],'failed');self.assertNotIn('private-secret',str(result))
    def test_unrecognised_response_is_unknown(self):
        self.assertEqual(self.send({'sid':'bad','status':'queued'})['outcome'],'unknown')
    def test_invalid_recipient_is_not_sent(self):
        result=TwilioSender(self.env,self.opener)(name='X',phone='123',message='Test',case_code='TEST')
        self.assertEqual(result['outcome'],'failed');self.opener.open.assert_not_called()
    def test_repr_does_not_expose_credentials(self):
        self.assertNotIn(self.env['TWILIO_AUTH_TOKEN'],repr(TwilioSender(self.env,self.opener)))
    def test_default_runner_is_dry_run(self):
        from avenra.notification_runner import main
        with patch('avenra.notification_runner.TwilioSender') as factory:
            self.assertEqual(main([]),0);factory.assert_not_called()

    def test_redirect_handler_refuses_credentials_forwarding(self):
        from avenra.services.sms_sender import NoRedirects
        self.assertIsNone(NoRedirects().redirect_request(
            None,None,302,'Found',{},'https://different.example.test'))

    def test_oversized_provider_response_is_unknown(self):
        result=self.send({'sid':'SM'+'b'*32,'status':'queued','padding':'x'*70000})
        self.assertEqual(result['outcome'],'unknown')

class Stage2APITests(unittest.TestCase):
    setUp=test_avenra.avenraStagesTestCase.setUp
    tearDown=test_avenra.avenraStagesTestCase.tearDown
    _login_staff=test_avenra.avenraStagesTestCase._login_staff
    def alert(self,key,**extra):
        r=self.client.post('/api/alerts',json={'client_id':key,**extra},headers=self.survivor_headers)
        self.assertEqual(r.status_code,201);return r.json['id']
    def test_reads_mask_contacts_but_allow_id_based_preservation(self):
        r=self.client.post('/api/contacts',json={'contacts':[{'name':'One','phone':'0821234567'}]},headers=self.survivor_headers)
        self.assertEqual(r.status_code,200);row=r.json['contacts'][0]
        self.assertNotIn('phone',row);self.assertEqual(row['phone_masked'],'••••4567')
        r=self.client.post('/api/contacts',json={'contacts':[{'id':row['id'],'name':'Renamed'}]},headers=self.survivor_headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['contacts'][0]['id'],row['id'])
    def test_five_contacts_accepted_six_rejected(self):
        contacts=[{'name':str(i),'phone':f'+2782123456{i}'} for i in range(5)]
        self.assertEqual(self.client.post('/api/contacts',json={'contacts':contacts},headers=self.survivor_headers).status_code,200)
        self.assertEqual(self.client.post('/api/contacts',json={'contacts':contacts+[{'name':'six','phone':'+27832345678'}]},headers=self.survivor_headers).status_code,400)
    def test_unchanged_contact_keeps_queued_job(self):
        self.assertEqual(self.client.post('/api/contacts',json={'contacts':[
            {'name':'One','phone':'+27821234567'},
            {'name':'Two','phone':'+27832345678'},
        ]},headers=self.survivor_headers).status_code,200)
        aid=self.alert('preserve-contact-job')
        before=self.client.get('/api/contacts',headers=self.survivor_headers).json['contacts']
        conn=test_avenra.db.connect()
        try: ids=[r[0] for r in conn.execute('SELECT id FROM notification_outbox WHERE alert_id=?',(aid,))]
        finally:conn.close()
        self.assertEqual(self.client.post('/api/contacts',json={'contacts':[{'id':r['id'],'name':r['name']} for r in before]},headers=self.survivor_headers).status_code,200)
        conn=test_avenra.db.connect()
        try:self.assertEqual(ids,[r[0] for r in conn.execute('SELECT id FROM notification_outbox WHERE alert_id=?',(aid,))])
        finally:conn.close()
    def test_sixth_batch_skips_contacts_but_keeps_alert(self):
        ids=[self.alert('rate-'+str(i)) for i in range(6)]
        sender=Mock(return_value={'outcome':'accepted','provider_message_id':'SM'+'b'*32})
        conn=test_avenra.db.connect()
        try:
            worker=NotificationWorker(conn,sender,evaluation_mode=False)
            for _ in range(20):
                if not worker.run_once():break
            self.assertEqual(NotificationStatusService(conn).for_alert(ids[-1])['status'],'skipped')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],6)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0],5)
            self.assertEqual(sender.call_count,10) # two fixture contacts per permitted batch
        finally:conn.close()
    def test_provider_id_persisted_and_not_exposed_to_dashboard(self):
        aid=self.alert('provider-id')
        conn=test_avenra.db.connect()
        try:
            w=NotificationWorker(conn,Mock(return_value={'outcome':'accepted','provider_message_id':'SM'+'b'*32}),evaluation_mode=False)
            self.assertTrue(w.run_once())
            self.assertEqual(conn.execute("SELECT provider_message_id FROM notification_outbox WHERE status='accepted'").fetchone()[0],'SM'+'b'*32)
        finally:conn.close()
        self._login_staff()
        body=self.client.get('/api/alerts').json
        self.assertNotIn('SM'+'b'*32,json.dumps(body))
        self.assertIn('notification',body['alerts'][0])
    def test_no_timezone_is_not_invented_for_device_time(self):
        self.alert('naive-clock',client_ts='2026-10-23T12:00:00')
        self._login_staff()
        self.assertIsNone(self.client.get('/api/alerts').json['alerts'][0]['client_ts'])
    def test_future_device_clock_does_not_create_negative_delay(self):
        timing=NotificationStatusService.timing('2099-01-01T00:00:00Z','2026-10-23T12:00:00Z')
        self.assertIsNone(timing['delay_seconds']);self.assertTrue(timing['device_clock_ahead'])
    def test_failed_contact_write_rolls_back_previous_contacts(self):
        before=self.client.get('/api/contacts',headers=self.survivor_headers).json
        import sqlite3
        with patch('avenra.repositories.contact_repository.ContactRepository.replace_contacts',side_effect=sqlite3.OperationalError('private')):
            response=self.client.post('/api/contacts',json={'contacts':[]},headers=self.survivor_headers)
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.client.get('/api/contacts',headers=self.survivor_headers).json,before)

    def test_database_evaluation_marker_blocks_sender(self):
        aid=self.alert('evaluation-marker')
        conn=test_avenra.db.connect()
        try:
            conn.execute("INSERT OR REPLACE INTO app_metadata(key,value) VALUES('evaluation_fixture','test-only')")
            conn.commit()
            sender=Mock()
            self.assertFalse(NotificationWorker(conn,sender,evaluation_mode=False).run_once())
            sender.assert_not_called()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notification_outbox WHERE status='pending'").fetchone()[0],2)
        finally:conn.close()

    def test_existing_outbox_is_upgraded_without_losing_jobs(self):
        aid=self.alert('migration-preserves-jobs')
        conn=test_avenra.db.connect()
        try:
            before=[tuple(r) for r in conn.execute(
                'SELECT id,alert_id,contact_id,status FROM notification_outbox ORDER BY id')]
            conn.execute('ALTER TABLE notification_outbox RENAME TO old_test_outbox')
            conn.execute("""CREATE TABLE notification_outbox(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending',claim_token TEXT,claimed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                UNIQUE(alert_id,contact_id))""")
            conn.execute("""INSERT INTO notification_outbox(id,alert_id,contact_id,status)
                SELECT id,alert_id,contact_id,status FROM old_test_outbox""")
            conn.execute('DROP TABLE old_test_outbox')
            conn.commit()
        finally:conn.close()
        test_avenra.db.init_db()
        test_avenra.db.init_db()
        conn=test_avenra.db.connect()
        try:
            columns={r['name'] for r in conn.execute('PRAGMA table_info(notification_outbox)')}
            self.assertTrue({'provider_message_id','reason_code','completed_at'}<=columns)
            self.assertEqual(before,[tuple(r) for r in conn.execute(
                'SELECT id,alert_id,contact_id,status FROM notification_outbox ORDER BY id')])
        finally:conn.close()
