"""Fictional CLI restore, compatible-code rollback and adversarial boundaries.

Not a hosted/provider disaster-recovery, penetration-test or deployment drill.
"""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import unittest
from cryptography.fernet import Fernet
import test_avenra as fixtures


class AcceptanceTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def test_real_cli_backup_restore_keeps_key_separate_and_target_isolated(self):
        root=Path(self.tmp_dir.name); keyfile=root/'custody'/'backup.key'; keyfile.parent.mkdir(mode=0o700)
        archive=root/'archives'/'fictional.enc'; target=root/'isolated-drill'
        def cli(*args):
            result=subprocess.run([sys.executable,'tools/isolated_backup.py',*args],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,'Isolated fixture CLI failed; private output withheld')
            return result.stdout
        cli('generate-key','--key-file',str(keyfile))
        key=keyfile.read_bytes().strip()
        created=cli('create','--source-sqlite',self.db_path,'--uploads',self.upload_dir,'--archive',str(archive),'--key-file',str(keyfile))
        self.assertEqual(json.loads(created)['engine'],'sqlite')
        restored=json.loads(cli('restore','--archive',str(archive),'--key-file',str(keyfile),'--target',str(target),'--isolated'))
        self.assertTrue(restored['isolated'])
        self.assertEqual(restored['integrity'],'verified')
        self.assertFalse((target/'RESTORE_INCOMPLETE').exists())
        self.assertTrue((target/'ISOLATED_RESTORE_DO_NOT_DEPLOY').exists())
        import zipfile
        with zipfile.ZipFile(io.BytesIO(Fernet(key).decrypt(archive.read_bytes()))) as package:
            self.assertEqual(set(package.namelist()),{'database.sqlite3','manifest.json'})
        self.assertNotIn(key.decode(),created)
        with closing(sqlite3.connect(self.db_path)) as source,closing(sqlite3.connect(target/'database.sqlite3')) as copy:
            for table in ('users','consents','audit_log','survivor_vaults','evidence_unlocks'):
                self.assertEqual(source.execute('SELECT * FROM '+table).fetchall(),copy.execute('SELECT * FROM '+table).fetchall())

    def test_previous_stage11_code_preserves_grants_and_retention_on_fixture_copy(self):
        from avenra.services.retention_service import RetentionService
        from avenra.repositories.user_repository import UserRepository
        entry={'client_id':'stage12-fictional-removed','note':'Fictional rollback note'}
        response=self.client.post('/api/diary',json=entry,headers=self.survivor_headers)
        self.assertEqual(response.status_code,201)
        with closing(fixtures.db.connect()) as conn:
            actor=UserRepository(conn).get_by_id(conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()[0])
            service=RetentionService(conn,self.upload_dir)
            plan=service.preview(actor,'SP-1042','diary',entry_ids=[response.json['id']])
            service.apply(actor,'SP-1042','diary',plan['plan'],'FICTIONAL-ROLLBACK-TICKET',entry_ids=[response.json['id']])
        root=Path(self.tmp_dir.name); previous=root/'previous-stage11'; previous.mkdir()
        archive=subprocess.check_output(['git','archive','stage-11-complete'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as package: package.extractall(previous,filter='data')
        clone=root/'rollback-fixture.sqlite3'
        with closing(sqlite3.connect(self.db_path)) as source,closing(sqlite3.connect(clone)) as copy: source.backup(copy)
        env=os.environ.copy()
        for key in ('DATABASE_URL','PUBLIC_BASE_URL','VERCEL','SMTP_HOST','SMTP_PASSWORD','AVENRA_WORKER_TOKEN'):
            env.pop(key,None)
        env.update(DATABASE_PATH=str(clone),UPLOADS_DIR=str(root/'rollback-uploads'),APP_ENV='development',COOKIE_SECURE='0',
            AVENRA_WEBPUSH_ENABLED='0',AVENRA_SMS_ENABLED='0',PYTHONPATH=str(previous))
        code="""
import json,sys
import app
sys.path.insert(0,'tests')
from vault_fixture import unlock_test_vault
client=app.app.test_client(); headers={'X-Device-Token':'demo-device'}
locked=client.get('/api/diary',headers=headers).status_code
unlock_test_vault(client,headers)
unlocked=client.get('/api/diary',headers=headers).status_code
removed=client.post('/api/diary',json={'client_id':'stage12-fictional-removed','note':'Fictional rollback note'},headers=headers).status_code
csp='script-src-attr' in client.get('/login').headers.get('Content-Security-Policy','')
print(json.dumps({'locked':locked,'unlocked':unlocked,'removed':removed,'csp':csp}))
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=previous,env=env,capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,'Previous-code fixture failed; private runtime output withheld')
        self.assertEqual(json.loads(result.stdout),{'locked':423,'unlocked':200,'removed':410,'csp':True})
        with closing(sqlite3.connect(self.db_path)) as source,closing(sqlite3.connect(clone)) as copy:
            self.assertEqual(source.execute('SELECT * FROM deletion_tombstones').fetchall(),copy.execute('SELECT * FROM deletion_tombstones').fetchall())

    def test_hostile_authority_and_malformed_payloads_leave_records_unchanged(self):
        with closing(fixtures.db.connect()) as conn:
            before=[conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('alerts','diary_entries','notification_outbox')]
        for body in ([],{'client_id':'fictional','owner_id':999}, {'client_id':"'; DROP TABLE users;--",'note':123}, {'client_id':'x'*1000}):
            response=self.client.post('/api/diary',json=body,headers=self.survivor_headers)
            self.assertIn(response.status_code,(400,403))
        for selector in ('9223372036854775808','-1','1%20OR%201=1','%3Cscript%3E'):
            response=self.client.get('/api/diary/'+selector,headers=self.survivor_headers)
            self.assertEqual(response.status_code,404)
            self.assertNotIn('Fictional rollback note',response.text)
        with closing(fixtures.db.connect()) as conn:
            after=[conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('alerts','diary_entries','notification_outbox')]
        self.assertEqual(before,after)
