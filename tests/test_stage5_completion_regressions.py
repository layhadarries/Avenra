"""Completion regressions use a temporary synthetic database only."""
import unittest
from contextlib import closing
import test_avenra as fixtures

class CompletionTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown

    def test_repeated_private_setting_does_not_add_audit_event(self):
        response = self.client.post('/api/diary', json={'client_id':'noop-share', 'note':'fictional'}, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 201)
        entry = response.json['id']
        with closing(fixtures.db.connect()) as conn:
            before = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
        for _ in range(2):
            response = self.client.post(f'/api/diary/{entry}/share', json={'shared':False}, headers=self.survivor_headers)
            self.assertEqual(response.status_code, 200)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0], before)

    def test_reconciliation_refuses_callers_active_transaction(self):
        from avenra.services.diary_service import DiaryService
        from avenra.repositories.diary_repository import DiaryRepository
        with closing(fixtures.db.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            service = DiaryService(diary_repo=DiaryRepository(conn))
            with self.assertRaises(RuntimeError):
                service.reconcile_orphans(self.upload_dir)
            self.assertTrue(conn.in_transaction)

    def test_upload_replay_after_unshare_does_not_restore_sharing(self):
        payload = {'client_id':'unshare-replay','note':'fictional','contract_version':2,'shared':True}
        response = self.client.post('/api/diary', json=payload, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 201)
        original = response.json
        response = self.client.post(f"/api/diary/{original['id']}/share", json={'shared':False}, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/api/diary', json=payload, headers=self.survivor_headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['shared'])
        self.assertEqual(response.json['entry_fingerprint'], original['entry_fingerprint'])

    def test_cleanup_waits_for_upload_commit_and_preserves_photo(self):
        import base64
        import io
        import os
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from PIL import Image
        from avenra.services.diary_service import DiaryService, LocalDiaryStorage
        from avenra.repositories.diary_repository import DiaryRepository
        stream = io.BytesIO()
        Image.new('RGB', (8,8), 'white').save(stream, 'JPEG')
        started = threading.Event()
        completed = threading.Event()
        original = LocalDiaryStorage.put_object
        def cleanup():
            with closing(fixtures.db.connect()) as conn:
                started.set()
                result = DiaryService(diary_repo=DiaryRepository(conn)).reconcile_orphans(self.upload_dir)
                completed.set()
                return result
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = []
            def put(storage, name, data, digest):
                original(storage, name, data, digest)
                future.append(pool.submit(cleanup))
                self.assertTrue(started.wait(5))
                self.assertFalse(completed.wait(.1), 'Cleanup must wait for the upload transaction')
            with patch.object(LocalDiaryStorage, 'put_object', put):
                response = self.client.post('/api/diary', headers=self.survivor_headers, json={
                    'client_id':'cleanup-race', 'note':'fictional',
                    'photo_data':'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(future[0].result(timeout=10), [])
        with closing(fixtures.db.connect()) as conn:
            name = conn.execute('SELECT photo_path FROM diary_entries WHERE id=?', (response.json['id'],)).fetchone()[0]
        self.assertTrue(os.path.isfile(os.path.join(self.upload_dir, name)))
