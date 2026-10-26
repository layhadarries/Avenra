"""A paired cookie alone must not expose diary evidence before vault unlock."""
from contextlib import closing
import unittest
import test_avenra as fixtures
import test_hosted_pwa_contract as pairing


class VaultAccessTests(unittest.TestCase):
    requires_locked_vault=True
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown
    _login_staff=fixtures.avenraStagesTestCase._login_staff
    invite=pairing.HostedPWAContractTests.invite
    enroll=pairing.HostedPWAContractTests.enroll
    phrase='Cedar! private river vault 826'

    def phone(self):
        phone,_=self.enroll(self.invite())
        return phone,phone.get('/api/device').json['account_id']

    def setup_vault(self,phone):
        response=phone.post('/api/vault/setup',json={'passphrase':self.phrase,'confirmation':self.phrase},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertNotIn('Set-Cookie',response.headers)
        phone.environ_base['HTTP_X_VAULT_UNLOCK']=response.json['unlock_token']

    def entry(self,phone,owner):
        response=phone.post('/api/diary',json={'client_id':'vault-access-fictional','note':'Fictional private text'},
            headers={'Origin':'http://localhost','X-Queue-Owner':str(owner)})
        self.assertEqual(response.status_code,201,response.text)
        return response.json['id']

    def test_pairing_is_not_a_vault_unlock(self):
        phone,owner=self.phone(); entry=self.entry(phone,owner)
        for path in ('/api/diary',f'/api/diary/{entry}',f'/api/diary/{entry}/photo'):
            response=phone.get(path)
            self.assertEqual(response.status_code,423)
            self.assertNotIn('Fictional private text',response.text)
            self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.client.get('/api/vault').status_code,401)

    def test_setup_unlock_expiry_and_lock_are_server_verified(self):
        phone,owner=self.phone(); entry=self.entry(phone,owner)
        self.setup_vault(phone)
        self.assertEqual(phone.get(f'/api/diary/{entry}').status_code,200)
        self.assertEqual(phone.post('/api/vault/lock',json={},headers={'Origin':'http://localhost'}).status_code,200)
        self.assertEqual(phone.get(f'/api/diary/{entry}').status_code,423)
        for value,status in [('wrong passphrase',401),(self.phrase,200)]:
            response=phone.post('/api/vault/unlock',json={'passphrase':value},headers={'Origin':'http://localhost'})
            self.assertEqual(response.status_code,status)
            if status==200: phone.environ_base['HTTP_X_VAULT_UNLOCK']=response.json['unlock_token']
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('UPDATE evidence_unlocks SET expires_at=0')
        self.assertEqual(phone.get(f'/api/diary/{entry}').status_code,423)

    def test_cross_account_and_revoked_device_cannot_use_unlock(self):
        first,owner=self.phone(); entry=self.entry(first,owner); self.setup_vault(first)
        second,_=self.phone(); self.setup_vault(second)
        self.assertEqual(second.get(f'/api/diary/{entry}').status_code,404)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute('UPDATE survivor_devices SET revoked_at=1 WHERE user_id=?',(owner,))
        self.assertEqual(first.get(f'/api/diary/{entry}').status_code,401)

    def test_cookies_alone_and_foreign_grants_cannot_read_evidence(self):
        first,owner=self.phone(); entry=self.entry(first,owner); self.setup_vault(first)
        grant=first.environ_base.pop('HTTP_X_VAULT_UNLOCK')
        first.set_cookie('avenra_evidence_unlock',grant,path='/api/')
        self.assertEqual(first.get(f'/api/diary/{entry}').status_code,423)
        second,_=self.phone(); self.setup_vault(second)
        self.assertEqual(second.get('/api/diary',headers={'X-Vault-Unlock':grant}).status_code,423)
        self.assertEqual(first.get(f'/api/diary/{entry}',headers={'X-Vault-Unlock':grant}).status_code,200)

    def test_delayed_old_lock_does_not_revoke_new_grant(self):
        phone,owner=self.phone(); entry=self.entry(phone,owner); self.setup_vault(phone)
        old=phone.environ_base['HTTP_X_VAULT_UNLOCK']
        response=phone.post('/api/vault/unlock',json={'passphrase':self.phrase},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,200)
        new=response.json['unlock_token']
        phone.post('/api/vault/lock',json={},headers={'Origin':'http://localhost','X-Vault-Unlock':old})
        self.assertEqual(phone.get(f'/api/diary/{entry}',headers={'X-Vault-Unlock':old}).status_code,423)
        self.assertEqual(phone.get(f'/api/diary/{entry}',headers={'X-Vault-Unlock':new}).status_code,200)

    def test_setup_cannot_replace_existing_secret_and_enforces_strength_and_origin(self):
        phone,_=self.phone()
        self.assertEqual(phone.post('/api/vault/setup',json={'passphrase':'1234','confirmation':'1234'},headers={'Origin':'http://localhost'}).status_code,400)
        self.setup_vault(phone)
        self.assertEqual(phone.post('/api/vault/setup',json={'passphrase':self.phrase,'confirmation':self.phrase},headers={'Origin':'http://localhost'}).status_code,409)
        self.assertEqual(phone.post('/api/vault/unlock',json={'passphrase':self.phrase},headers={'Origin':'https://foreign.invalid'}).status_code,403)

    def test_vault_setup_audit_failure_is_atomic(self):
        phone,_=self.phone()
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("CREATE TRIGGER fail_vault_audit BEFORE INSERT ON audit_log WHEN NEW.action='vault_configured' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        response=phone.post('/api/vault/setup',json={'passphrase':self.phrase,'confirmation':self.phrase},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,503)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM survivor_vaults').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM evidence_unlocks').fetchone()[0],0)

    def legacy(self,phone,owner):
        from test_stage9_alert_sealing import AlertSealingTests
        payload={'client_id':'legacy-private-recovery','owner_id':owner,'note':'Fictional recovered private note','status':'queued'}
        value=AlertSealingTests.seal(self,owner,phone.get('/api/device').json['sealing_key'],payload,purpose='legacy-diary')
        return {'client_id':value['client_id'],'sealed_payload':value['sealed_alert']},payload

    def test_opaque_legacy_recovery_requires_unlock_and_never_creates_records(self):
        phone,owner=self.phone(); body,payload=self.legacy(phone,owner)
        headers={'Origin':'http://localhost'}
        self.assertEqual(phone.post('/api/vault/recover',json=body,headers=headers).status_code,423)
        self.setup_vault(phone)
        response=phone.post('/api/vault/recover',json=body,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json['record'],payload)
        self.assertIn('no-store',response.headers['Cache-Control'])
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],0)
            audit=conn.execute("SELECT detail FROM audit_log WHERE action='vault_legacy_recovered'").fetchone()[0]
            self.assertNotIn(payload['note'],audit)

    def test_cross_owner_and_unbound_legacy_envelopes_cannot_be_adopted(self):
        first,owner=self.phone(); body,_=self.legacy(first,owner)
        second,_=self.phone(); self.setup_vault(second)
        response=second.post('/api/vault/recover',json=body,headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('Fictional recovered private note',response.text)
        unbound,_=self.legacy(second,0)
        self.assertEqual(second.post('/api/vault/recover',json=unbound,headers={'Origin':'http://localhost'}).status_code,400)

    def test_multipart_legacy_recovery_and_audit_failure_are_private(self):
        import io,json,base64
        phone,owner=self.phone(); self.setup_vault(phone); body,payload=self.legacy(phone,owner)
        envelope=dict(body['sealed_payload']); cipher=base64.b64decode(envelope.pop('ciphertext'))
        response=phone.post('/api/vault/recover',data={'client_id':body['client_id'],'envelope':json.dumps(envelope),
            'payload':(io.BytesIO(cipher),'encrypted.bin')},headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json['record'],payload)
        with closing(fixtures.db.connect()) as conn,conn:
            conn.execute("CREATE TRIGGER fail_legacy_audit BEFORE INSERT ON audit_log WHEN NEW.action='vault_legacy_recovered' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        response=phone.post('/api/vault/recover',json=body,headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn(payload['note'],response.text)
