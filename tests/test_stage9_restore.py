"""Encrypted, key-separated restore against brand-new isolated SQLite/storage targets."""
from contextlib import closing
import hashlib
import io
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from PIL import Image
import test_avenra as fixtures


class IsolatedRestoreTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def photo(self):
        import base64
        buffer=io.BytesIO(); Image.new('RGB',(24,24),(20,50,80)).save(buffer,format='JPEG')
        data={'client_id':'restore-fictional-photo','note':'Fictional restore note',
            'photo_data':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}
        response=self.client.post('/api/diary',json=data,headers=self.survivor_headers)
        self.assertEqual(response.status_code,201,response.text)
        return buffer.getvalue()

    def service(self):
        from avenra.services.backup_service import IsolatedBackupService
        return IsolatedBackupService()

    def test_encrypted_restore_preserves_exact_rows_times_and_local_media(self):
        raw=self.photo(); root=Path(self.tmp_dir.name)
        archive=root/'backups'/'snapshot.enc'; key=Fernet.generate_key()
        result=self.service().create(self.db_path,self.upload_dir,archive,key)
        self.assertNotIn(b'Fictional restore note',archive.read_bytes())
        self.assertEqual(result['media_files'],1)
        target=root/'isolated-restored'
        with patch('avenra.services.push_worker.PushWorker.run_once',side_effect=AssertionError('no dispatch')):
            restored=self.service().restore(archive,target,key)
        self.assertTrue((target/'ISOLATED_RESTORE_DO_NOT_DEPLOY').exists())
        self.assertNotEqual(Path(restored['database']).resolve(),Path(self.db_path).resolve())
        with closing(sqlite3.connect(self.db_path)) as source, closing(sqlite3.connect(restored['database'])) as clone:
            self.assertEqual(source.execute('SELECT * FROM diary_entries').fetchall(),clone.execute('SELECT * FROM diary_entries').fetchall())
            name=clone.execute('SELECT photo_path FROM diary_entries').fetchone()[0]
        self.assertEqual((target/'uploads'/name).read_bytes(),raw)
        self.assertEqual(hashlib.sha256((target/'uploads'/name).read_bytes()).hexdigest(),hashlib.sha256(raw).hexdigest())
        with patch.object(fixtures.db,'DB_PATH',restored['database']):
            with self.assertRaisesRegex(RuntimeError,'isolated'):
                fixtures.db.connect()

    @patch.dict('os.environ',{'DIARY_STORAGE_BACKEND':'database'})
    def test_transactional_database_media_is_included_without_public_object_urls(self):
        self.photo(); root=Path(self.tmp_dir.name); key=Fernet.generate_key(); archive=root/'snapshots'/'database.enc'
        self.service().create(self.db_path,self.upload_dir,archive,key)
        restored=self.service().restore(archive,root/'database-restore',key)
        with closing(sqlite3.connect(self.db_path)) as source, closing(sqlite3.connect(restored['database'])) as target:
            self.assertEqual(source.execute('SELECT * FROM diary_objects').fetchall(),target.execute('SELECT * FROM diary_objects').fetchall())
            self.assertEqual(target.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_wrong_key_and_existing_targets_fail_without_overwrite(self):
        self.photo(); root=Path(self.tmp_dir.name); key=Fernet.generate_key(); archive=root/'backups'/'snapshot.enc'
        self.service().create(self.db_path,self.upload_dir,archive,key)
        with self.assertRaises(ValueError): self.service().restore(archive,root/'wrong-key',Fernet.generate_key())
        self.assertFalse((root/'wrong-key').exists())
        target=root/'existing'; target.mkdir(); sentinel=target/'keep.txt'; sentinel.write_text('User work')
        with self.assertRaises(FileExistsError): self.service().restore(archive,target,key)
        self.assertEqual(sentinel.read_text(),'User work')
        with self.assertRaises(FileExistsError): self.service().create(self.db_path,self.upload_dir,archive,key)

    def test_missing_media_or_corrupt_archive_never_claims_restore_success(self):
        self.photo(); root=Path(self.tmp_dir.name); key=Fernet.generate_key(); archive=root/'backups'/'snapshot.enc'
        self.service().create(self.db_path,self.upload_dir,archive,key)
        corrupt=root/'corrupt.enc'; damaged=bytearray(archive.read_bytes()); damaged[-8]^=1; corrupt.write_bytes(damaged)
        with self.assertRaises(ValueError): self.service().restore(corrupt,root/'corrupt-restore',key)
        name=next(Path(self.upload_dir).glob('diary_*.jpg')); name.rename(name.with_suffix('.missing'))
        with self.assertRaises(OSError): self.service().create(self.db_path,self.upload_dir,root/'missing.enc',key)

    def test_cli_requires_separate_key_directory_and_explicit_isolation(self):
        from subprocess import run
        import sys
        root=Path(self.tmp_dir.name); backup=root/'backups'; backup.mkdir(); key=backup/'bad-key'; key.write_bytes(Fernet.generate_key()); key.chmod(0o600)
        result=run([sys.executable,'tools/isolated_backup.py','create','--source-sqlite',self.db_path,'--uploads',self.upload_dir,
                    '--archive',str(backup/'snapshot.enc'),'--key-file',str(key)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('separate',result.stderr.lower())
        self.assertNotIn(key.read_text(),result.stdout+result.stderr)

    def test_quarantined_retained_bytes_and_unknown_timestamps_survive_restore(self):
        raw=self.photo(); root=Path(self.tmp_dir.name); key=Fernet.generate_key(); archive=root/'backups'/'retained.enc'
        quarantine=Path(self.upload_dir)/'.quarantine'; quarantine.mkdir(); (quarantine/'diary_retained.jpg').write_bytes(raw)
        with closing(sqlite3.connect(self.db_path)) as conn,conn:
            uid=conn.execute('SELECT user_id FROM diary_entries LIMIT 1').fetchone()[0]
            conn.execute("INSERT INTO diary_entries(user_id,client_id,note,created_at,received_at) VALUES(?,'restore-unknown-time','Fictional legacy row','2010-01-01T00:00:00Z',NULL)",(uid,))
        result=self.service().create(self.db_path,self.upload_dir,archive,key)
        self.assertEqual(result['media_files'],2)
        restored=self.service().restore(archive,root/'retained-restore',key)
        self.assertEqual((root/'retained-restore'/'uploads'/'.quarantine'/'diary_retained.jpg').read_bytes(),raw)
        with closing(sqlite3.connect(restored['database'])) as conn:
            self.assertIsNone(conn.execute("SELECT received_at FROM diary_entries WHERE client_id='restore-unknown-time'").fetchone()[0])

    def test_authenticated_malformed_manifests_are_rejected_before_target_creation(self):
        import json,zipfile
        root=Path(self.tmp_dir.name); key=Fernet.generate_key()
        for index,manifest in enumerate(([],{'version':1,'engine':'sqlite','files':[]},
                {'version':1,'engine':'sqlite','files':{'database.sqlite3':[]}})):
            with self.subTest(index=index):
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w') as package:
                    package.writestr('manifest.json',json.dumps(manifest))
                    package.writestr('database.sqlite3',b'not a database')
                archive=root/f'malformed-{index}.enc'; archive.write_bytes(Fernet(key).encrypt(buffer.getvalue()))
                target=root/f'malformed-target-{index}'
                with self.assertRaises(ValueError): self.service().restore(archive,target,key)
                self.assertFalse(target.exists())
