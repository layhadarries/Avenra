"""SMS is explicit and owner-scoped; no real providers are invoked."""
import unittest
from contextlib import closing
from unittest.mock import patch
import test_avenra as fixtures

class SMSOptInTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def test_sms_permission_requires_boolean_and_device_auth(self):
        self.assertNotEqual(self.client.post('/api/contacts/1/sms',json={'enabled':True}).status_code,200)
        for value in ['true',1,None]:
            self.assertEqual(self.client.post('/api/contacts/1/sms',json={'enabled':value},headers=self.survivor_headers).status_code,400)

    def test_legacy_contacts_are_not_implicitly_opted_in(self):
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM contacts WHERE sms_opt_in<>0').fetchone()[0],0)

    def test_sms_and_webpush_flags_do_not_enable_unconsented_sms(self):
        from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
        with closing(fixtures.db.connect()) as conn:
            row=conn.execute("SELECT id FROM users WHERE role='survivor' ORDER BY id LIMIT 1").fetchone()
            uid=row['id']
            conn.execute("INSERT INTO alerts(user_id,case_code,client_id) SELECT id,case_code,'sms-opt-in-probe' FROM users WHERE id=?",(uid,))
            aid=conn.execute("SELECT id FROM alerts WHERE client_id='sms-opt-in-probe'").fetchone()[0]
            repo=NotificationOutboxRepository(conn)
            with patch.dict('os.environ',{'AVENRA_SMS_ENABLED':'1','AVENRA_WEBPUSH_ENABLED':'1'}):
                repo.enqueue_for_alert(aid)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM notification_outbox WHERE alert_id=?',(aid,)).fetchone()[0],0)
            conn.rollback()

    def test_sms_only_tick_uses_no_push_provider(self):
        import os
        from unittest.mock import Mock
        with patch.dict(os.environ,{'AVENRA_SMS_ENABLED':'1','AVENRA_WEBPUSH_ENABLED':'0','AVENRA_WORKER_TOKEN':'x'*43}), patch.dict(fixtures.avenra_app.app.config,EVALUATION_MODE=False), patch('avenra.services.sms_sender.TwilioSender'), patch('avenra.services.push_service.PushSettings') as push, patch('avenra.services.notification_worker.NotificationWorker') as worker:
            worker.return_value.run_once.return_value=True
            response=self.client.post('/api/worker/tick',json={},headers={'Authorization':'Bearer '+'x'*43})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json['processed'],1)
            push.assert_not_called()
            worker.return_value.run_once.assert_called_once()

    def test_revoked_sms_permission_cancels_without_sending(self):
        from avenra.services.notification_worker import NotificationWorker
        from unittest.mock import Mock
        response=self.client.post('/api/alerts',json={'client_id':'consent-cancel-probe'},headers=self.survivor_headers)
        self.assertEqual(response.status_code,201)
        with closing(fixtures.db.connect()) as conn:
            sender=Mock()
            NotificationWorker(conn,sender,evaluation_mode=False).run_once()
            sender.assert_not_called()

    def test_permission_change_is_owner_scoped_and_cancels_pending_history(self):
        contacts=self.client.get('/api/contacts',headers=self.survivor_headers).json['contacts']
        contact=contacts[0]['id']
        enabled=self.client.post(f'/api/contacts/{contact}/sms',json={'enabled':True},headers=self.survivor_headers)
        self.assertEqual(enabled.status_code,200)
        self.assertTrue(next(c for c in enabled.json['contacts'] if c['id']==contact)['sms_opt_in'])
        with patch.dict('os.environ',{'AVENRA_SMS_ENABLED':'1','AVENRA_WEBPUSH_ENABLED':'0'}):
            response=self.client.post('/api/alerts',json={'client_id':'permission-history-probe'},headers=self.survivor_headers)
        self.assertEqual(response.status_code,201)
        disabled=self.client.post(f'/api/contacts/{contact}/sms',json={'enabled':False},headers=self.survivor_headers)
        self.assertEqual(disabled.status_code,200)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notification_outbox WHERE contact_id=? AND status='pending'",(contact,)).fetchone()[0],0)
            other=conn.execute("INSERT INTO users(name,role,email,case_code,is_active) VALUES('Other fictional survivor','survivor','other-sms@example.test','TEST-SMS-OTHER',1) RETURNING id").fetchone()[0]
            foreign=conn.execute("INSERT INTO contacts(user_id,name,phone) VALUES(?,'Other contact','+27821234567') RETURNING id",(other,)).fetchone()[0]
            conn.commit()
        response=self.client.post(f'/api/contacts/{foreign}/sms',json={'enabled':True},headers=self.survivor_headers)
        self.assertEqual(response.status_code,404)
