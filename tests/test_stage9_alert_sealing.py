"""Hybrid offline encryption is owner/ID bound and does not change alert semantics."""
import base64
from contextlib import closing
import json
import os
import unittest
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import test_avenra as fixtures
import test_hosted_pwa_contract as pairing


class AlertSealingTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown
    _login_staff=fixtures.avenraStagesTestCase._login_staff
    invite=pairing.HostedPWAContractTests.invite
    enroll=pairing.HostedPWAContractTests.enroll

    def phone(self):
        phone,_=self.enroll(self.invite()); body=phone.get('/api/device').json
        self.assertIn('sealing_key',body)
        return phone,body['account_id'],body['sealing_key']

    def seal(self, owner, public, payload, purpose='alert'):
        key=os.urandom(32); nonce=os.urandom(12)
        aad=json.dumps([1,owner,payload['client_id'],purpose],separators=(',',':')).encode()
        rsa=serialization.load_der_public_key(base64.b64decode(public['spki']))
        wrapped=rsa.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        return {'client_id':payload['client_id'],'sealed_alert':{'version':1,'kid':public['kid'],'owner_id':owner,
            'iv':base64.b64encode(nonce).decode(),'wrapped_key':base64.b64encode(wrapped).decode(),
            'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,json.dumps(payload).encode(),aad)).decode()}}

    def post(self,phone,owner,body):
        return phone.post('/api/alerts',json=body,headers={'Origin':'http://localhost','X-Queue-Owner':str(owner)})

    def test_sealed_location_and_idempotency_keep_same_alert_and_outbox(self):
        phone,owner,public=self.phone()
        self.assertEqual(phone.post('/api/consents',json={'item':'location_sharing','active':True},headers={'Origin':'http://localhost'}).status_code,200)
        payload={'client_id':'sealed-fixture-alert','lat':-33.9,'lng':18.4,'location_accuracy':22,'client_ts':'2026-10-26T00:00:00Z'}
        envelope=self.seal(owner,public,payload)
        self.assertNotIn('lat',envelope)
        first=self.post(phone,owner,envelope)
        self.assertEqual(first.status_code,201,first.text)
        self.assertTrue(first.json['location_shared'])
        self.assertEqual(self.post(phone,owner,envelope).json['id'],first.json['id'])
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alerts WHERE client_id=?',(payload['client_id'],)).fetchone()[0],1)

    def test_owner_id_client_id_and_ciphertext_tampering_are_rejected(self):
        phone,owner,public=self.phone()
        envelope=self.seal(owner,public,{'client_id':'sealed-tamper-fixture'})
        for invalid in [dict(envelope,client_id='different-id'),
                        {'client_id':envelope['client_id'],'sealed_alert':dict(envelope['sealed_alert'],owner_id=owner+1)},
                        {'client_id':envelope['client_id'],'sealed_alert':dict(envelope['sealed_alert'],ciphertext='AAAA')}]:
            self.assertEqual(self.post(phone,owner,invalid).status_code,400)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],0)

    def test_current_consent_and_explicit_suppression_override_encrypted_location(self):
        phone,owner,public=self.phone()
        self.assertEqual(phone.post('/api/consents',json={'item':'location_sharing','active':True},headers={'Origin':'http://localhost'}).status_code,200)
        payload={'client_id':'sealed-suppressed-fixture','lat':-33.9,'lng':18.4}
        envelope=self.seal(owner,public,payload)
        envelope['suppress_location']=True
        self.assertFalse(self.post(phone,owner,envelope).json['location_shared'])
        self.assertEqual(phone.post('/api/consents',json={'item':'location_sharing','active':False},headers={'Origin':'http://localhost'}).status_code,200)
        payload['client_id']='sealed-revoked-fixture'
        self.assertFalse(self.post(phone,owner,self.seal(owner,public,payload)).json['location_shared'])

    def test_unavailable_old_key_is_retryable_not_a_fabricated_receipt(self):
        phone,owner,public=self.phone()
        envelope=self.seal(owner,public,{'client_id':'sealed-unavailable-key'})
        envelope['sealed_alert']['kid']='0'*64
        self.assertEqual(self.post(phone,owner,envelope).status_code,503)

    def test_retired_key_can_restore_an_old_pending_envelope(self):
        phone,owner,public=self.phone()
        payload={'client_id':'sealed-key-custody-fixture','client_ts':'2026-10-26T00:00:00Z'}
        envelope=self.seal(owner,public,payload)
        from avenra.services.queue_sealing_service import QueueSealingKeys
        from cryptography.hazmat.primitives.asymmetric import rsa
        new=rsa.generate_private_key(public_exponent=65537,key_size=3072).private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        replacement=QueueSealingKeys({'OFFLINE_QUEUE_PRIVATE_KEY_PEM':new},required=True)
        with self.assertRaises(RuntimeError): replacement.decrypt(owner,payload['client_id'],envelope['sealed_alert'])
        retained=QueueSealingKeys({'OFFLINE_QUEUE_PRIVATE_KEY_PEM':new,
            'OFFLINE_QUEUE_RETIRED_KEYS_JSON':json.dumps([os.environ['OFFLINE_QUEUE_PRIVATE_KEY_PEM']])},required=True)
        self.assertEqual(retained.decrypt(owner,payload['client_id'],envelope['sealed_alert']),payload)
        self.assertNotIn('PRIVATE KEY',repr(retained))

    def test_operator_key_generation_is_private_and_never_overwrites(self):
        from pathlib import Path
        from tools.queue_keys import generate
        path=Path(self.tmp_dir.name)/'separate-custody'/'queue.pem'
        identifier=generate(path)
        self.assertRegex(identifier,r'^[0-9a-f]{64}$')
        if os.name=='posix': self.assertEqual(path.stat().st_mode & 0o777,0o600)
        before=path.read_bytes()
        with self.assertRaises(FileExistsError): generate(path)
        self.assertEqual(path.read_bytes(),before)
