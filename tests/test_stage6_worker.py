"""Hosted worker is explicit, authenticated, bounded and disabled by default."""
import os
import unittest
from unittest.mock import patch,Mock
import test_avenra as fixtures

class WorkerTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def test_public_cannot_invoke_worker(self):
        response=self.client.post('/api/worker/tick',json={})
        self.assertEqual(response.status_code,401)

    def test_disabled_worker_does_not_claim(self):
        with patch.dict(os.environ,AVENRA_WORKER_TOKEN='x'*43,AVENRA_WEBPUSH_ENABLED='0'):
            response=self.client.post('/api/worker/tick',json={},headers={'Authorization':'Bearer '+'x'*43})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['processed'],0)

    def test_invalid_token_does_not_invoke_worker(self):
        with patch.dict(os.environ,AVENRA_WORKER_TOKEN='x'*43):
            response=self.client.post('/api/worker/tick',json={},headers={'Authorization':'Bearer '+'y'*43})
        self.assertEqual(response.status_code,401)

    def test_get_cannot_process_jobs(self):
        self.assertEqual(self.client.get('/api/worker/tick').status_code,405)

    def test_enabled_worker_is_bounded_and_records_heartbeat(self):
        with patch.dict(os.environ,AVENRA_WORKER_TOKEN='x'*43,AVENRA_WEBPUSH_ENABLED='1'),patch.dict(fixtures.avenra_app.app.config,EVALUATION_MODE=False),patch('avenra.services.push_service.PushSettings'),patch('avenra.services.webpush_sender.WebPushSender'),patch('avenra.services.notification_worker.NotificationWorker'),patch('avenra.services.push_worker.PushWorker') as worker:
            worker.return_value.run_once.return_value=True
            response=self.client.post('/api/worker/tick',json={},headers={'Authorization':'Bearer '+'x'*43})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json['processed'],1)
            worker.return_value.run_once.assert_called_once_with()
        conn=fixtures.db.connect()
        try:self.assertEqual(conn.execute("SELECT processed FROM worker_state WHERE key='webpush'").fetchone()[0],1)
        finally:conn.close()

    def test_worker_dry_run_cannot_claim_jobs(self):
        with patch.dict(os.environ,AVENRA_WORKER_TOKEN='x'*43,AVENRA_WEBPUSH_ENABLED='1'),patch.dict(fixtures.avenra_app.app.config,EVALUATION_MODE=False),patch('avenra.services.push_service.PushSettings'),patch('avenra.services.push_worker.PushWorker') as worker:
            response=self.client.post('/api/worker/tick',json={'dry_run':True},headers={'Authorization':'Bearer '+'x'*43})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['processed'],0)
            worker.assert_not_called()

    def test_hosted_environment_push_keys_encrypt_without_network(self):
        import tempfile
        from pathlib import Path
        import requests
        import test_webpush as push_fixtures
        from avenra.services.push_service import generate_keys,PushSettings
        from avenra.services.webpush_sender import WebPushSender
        from pywebpush import webpush
        with tempfile.TemporaryDirectory() as directory:
            keys=Path(directory);generate_keys(keys)
            settings=PushSettings({'AVENRA_WEBPUSH_ENABLED':'1','WEBPUSH_PRIVATE_KEY_PEM':(keys/'vapid-private.pem').read_text(),'WEBPUSH_STORAGE_KEY':(keys/'subscription-storage.key').read_text(),'WEBPUSH_SUBJECT':'mailto:operator@example.test'})
            response=requests.Response();response.status_code=201;response._content=b''
            network=Mock();network.post.return_value=response
            def transport(**kwargs):
                kwargs['requests_session']=network
                return webpush(**kwargs)
            result=WebPushSender(settings,transport).send(push_fixtures.subscription())
            self.assertEqual(result['outcome'],'accepted')
            self.assertIsInstance(network.post.call_args.kwargs['data'],bytes)
            self.assertNotIn(b'You have a new notification',network.post.call_args.kwargs['data'])
