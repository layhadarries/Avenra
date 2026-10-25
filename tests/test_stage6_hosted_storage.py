"""Hosted private storage contract, using isolated SQLite blob transactions."""
import hashlib
import sqlite3
import unittest
import test_avenra as fixtures

class HostedStorageTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def storage(self,conn,limit=4096):
        from avenra.services.database_diary_storage import DatabaseDiaryStorage
        return DatabaseDiaryStorage(conn,limit=limit)

    def test_bytes_commit_and_reconnect(self):
        conn=fixtures.db.connect(); storage=self.storage(conn)
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            storage.put_object('diary_test.jpg',b'example',hashlib.sha256(b'example').hexdigest())
        conn.close()
        conn=fixtures.db.connect()
        try:self.assertEqual(self.storage(conn).get_object('diary_test.jpg'),b'example')
        finally:conn.close()

    def test_rollback_removes_object(self):
        conn=fixtures.db.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self.storage(conn).put_object('diary_test.jpg',b'example',hashlib.sha256(b'example').hexdigest())
            conn.rollback()
            self.assertFalse(self.storage(conn).verify_object('diary_test.jpg',hashlib.sha256(b'example').hexdigest()))
        finally:conn.close()

    def test_quota_failure_does_not_write(self):
        conn=fixtures.db.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            with self.assertRaises(OSError):self.storage(conn,limit=2).put_object('diary_test.jpg',b'example',hashlib.sha256(b'example').hexdigest())
            conn.rollback()
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_objects').fetchone()[0],0)
        finally:conn.close()

    def test_corruption_is_rejected(self):
        conn=fixtures.db.connect()
        try:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                self.storage(conn).put_object('diary_test.jpg',b'example',hashlib.sha256(b'example').hexdigest())
            with conn:conn.execute('UPDATE diary_objects SET data=?',(b'changed',))
            self.assertFalse(self.storage(conn).verify_object('diary_test.jpg',hashlib.sha256(b'example').hexdigest()))
        finally:conn.close()

    def test_unsafe_key_is_rejected(self):
        conn=fixtures.db.connect()
        try:
            with self.assertRaises(OSError):self.storage(conn).get_object('../private')
        finally:conn.close()

    def test_api_photo_is_private_and_survives_new_request(self):
        import io,base64,os
        from PIL import Image
        from unittest.mock import patch
        buffer=io.BytesIO();Image.new('RGB',(8,8),'white').save(buffer,format='JPEG')
        photo=buffer.getvalue()
        payload={'client_id':'hosted-blob-api','note':'Fictional hosted photo',
                 'photo_data':'data:image/jpeg;base64,'+base64.b64encode(photo).decode()}
        with patch.dict(os.environ,DIARY_STORAGE_BACKEND='database'):
            response=self.client.post('/api/diary',json=payload,headers=self.survivor_headers)
            self.assertEqual(response.status_code,201,response.text)
            entry=response.json['id']
            image=self.client.get('/api/diary/'+str(entry)+'/photo',headers=self.survivor_headers)
            self.assertEqual(image.status_code,200)
            self.assertEqual(image.data,photo)
            self.assertIn('no-store',image.headers['Cache-Control'])
            anonymous=fixtures.avenra_app.app.test_client()
            self.assertEqual(anonymous.get('/api/diary/'+str(entry)+'/photo').status_code,401)
            replay=self.client.post('/api/diary',json=payload,headers=self.survivor_headers)
            self.assertEqual(replay.status_code,200)
            self.assertEqual(replay.json['id'],entry)

    def test_api_audit_failure_rolls_back_blob_and_entry(self):
        import io,base64,os
        from PIL import Image
        from unittest.mock import patch
        buffer=io.BytesIO();Image.new('RGB',(8,8),'white').save(buffer,format='JPEG')
        payload={'client_id':'hosted-blob-audit','note':'Fictional atomic rollback',
                 'photo_data':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}
        with patch.dict(os.environ,DIARY_STORAGE_BACKEND='database'),patch('avenra.repositories.audit_repository.AuditRepository.log',side_effect=sqlite3.OperationalError('synthetic')):
            response=self.client.post('/api/diary',json=payload,headers=self.survivor_headers)
        self.assertEqual(response.status_code,503)
        conn=fixtures.db.connect()
        try:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_objects').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],0)
        finally:conn.close()
