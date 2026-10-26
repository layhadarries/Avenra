"""Explicit, previewable, audited deletion never uses invented receipt times."""
from contextlib import closing
import io
import os
import unittest
from unittest.mock import patch
from PIL import Image
import test_avenra as fixtures
from avenra.repositories.user_repository import UserRepository


class RetentionTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def service(self,conn):
        from avenra.services.retention_service import RetentionService
        return RetentionService(conn,self.upload_dir)

    def actor(self,conn,role='admin'):
        return UserRepository(conn).get_by_id(conn.execute('SELECT id FROM users WHERE role=? LIMIT 1',(role,)).fetchone()[0])

    def entry(self,photo=False):
        body={'client_id':'retention-fictional-entry','note':'Fictional private retention note'}
        if photo:
            import base64
            buffer=io.BytesIO(); Image.new('RGB',(20,20)).save(buffer,format='JPEG')
            body['photo_data']='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()
        response=self.client.post('/api/diary',json=body,headers=self.survivor_headers)
        self.assertEqual(response.status_code,201,response.text)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE diary_entries SET received_at='2020-01-01T00:00:00Z' WHERE id=?",(response.json['id'],))
        return response.json['id'],body

    def preview(self,service,actor,**extra):
        return service.preview(actor,'SP-1042','diary',before='2021-01-01T00:00:00Z',**extra)

    def test_preview_is_read_only_private_and_legacy_unknown_time_is_not_invented(self):
        entry,_=self.entry()
        with closing(fixtures.db.connect()) as conn, conn:
            owner=conn.execute('SELECT user_id FROM diary_entries WHERE id=?',(entry,)).fetchone()[0]
            conn.execute("INSERT INTO diary_entries(user_id,client_id,note,created_at) VALUES(?,'legacy-unknown-retention','Fictional historical note','2010-01-01T00:00:00Z')",(owner,))
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); before=conn.total_changes
            plan=self.preview(service,self.actor(conn))
            self.assertEqual(plan['eligible'],1)
            self.assertEqual(plan['unknown_receipt_time'],1)
            self.assertEqual(conn.total_changes,before)
            self.assertNotIn('Fictional',str(plan))
            self.assertNotIn('retention-fictional-entry',str(plan))

    def test_apply_is_audited_idempotent_and_tombstone_prevents_resurrection(self):
        entry,body=self.entry()
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            result=service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET-1',before='2021-01-01T00:00:00Z')
            self.assertEqual(result['removed'],1)
            self.assertTrue(service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET-1',before='2021-01-01T00:00:00Z')['already_applied'])
            audit=conn.execute("SELECT actor,detail FROM audit_log WHERE action='retention_applied'").fetchall()
            self.assertEqual(len(audit),1)
            self.assertEqual(audit[0]['actor'],f'user:{actor.id}')
            self.assertNotIn(body['note'],audit[0]['detail'])
        self.assertEqual(self.client.get(f'/api/diary/{entry}',headers=self.survivor_headers).status_code,404)
        self.assertEqual(self.client.post('/api/diary',json=body,headers=self.survivor_headers).status_code,410)

    def test_hold_stale_plan_and_non_admin_block_changes(self):
        self.entry()
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            with self.assertRaises(PermissionError): self.preview(service,self.actor(conn,'responder'))
            service.set_hold(actor,'SP-1042',True,'LEGAL-HOLD-TICKET')
            with self.assertRaises(ValueError): service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            service.set_hold(actor,'SP-1042',False,'RELEASE-HOLD-TICKET')
            with conn: conn.execute("UPDATE diary_entries SET shared=1 WHERE client_id='retention-fictional-entry'")
            with self.assertRaises(ValueError): service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],1)

    def test_audit_failure_rolls_back_deletion_tombstones_and_jobs(self):
        self.entry(photo=True)
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            with conn:
                conn.execute("CREATE TRIGGER fail_retention_audit BEFORE INSERT ON audit_log WHEN NEW.action='retention_applied' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            import sqlite3
            with self.assertRaises(sqlite3.Error): service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM deletion_tombstones').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM retention_media_jobs').fetchone()[0],0)
        self.assertEqual(len(os.listdir(self.upload_dir)),1)

    def test_local_media_cleanup_is_explicit_bounded_and_retryable(self):
        self.entry(photo=True)
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            self.assertEqual(len(os.listdir(self.upload_dir)),1)
            self.assertEqual(service.cleanup_media(actor,'SP-1042',apply=False)['pending'],1)
            with patch('avenra.services.retention_service.os.unlink',side_effect=PermissionError('synthetic')):
                self.assertEqual(service.cleanup_media(actor,'SP-1042',apply=True,reference='CLEANUP-TICKET')['failed'],1)
            self.assertEqual(len(os.listdir(self.upload_dir)),1)
            self.assertEqual(service.cleanup_media(actor,'SP-1042',apply=True,reference='CLEANUP-TICKET')['deleted'],1)
            self.assertEqual(os.listdir(self.upload_dir),[])

    def test_resolved_location_purge_preserves_alert_jobs_workflow_and_security_epochs(self):
        self.assertEqual(self.client.post('/api/consents',json={'item':'location_sharing','active':True},headers=self.survivor_headers).status_code,200)
        response=self.client.post('/api/alerts',json={'client_id':'retention-location','lat':-33.9,'lng':18.4},headers=self.survivor_headers)
        self.assertEqual(response.status_code,201)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE alerts SET status='resolved',created_at='2020-01-01T00:00:00Z' WHERE id=?",(response.json['id'],))
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn)
            self.assertEqual(service.preview(actor,'SP-1042','alert-location',before='2021-01-01T00:00:00Z')['eligible'],0)
            with conn:
                conn.execute("UPDATE notification_outbox SET status='cancelled',reason_code='evaluation_disabled' WHERE alert_id=?",(response.json['id'],))
            alert=dict(conn.execute('SELECT * FROM alerts WHERE id=?',(response.json['id'],)).fetchone())
            jobs=[tuple(row) for row in conn.execute('SELECT * FROM notification_outbox')]
            security=[tuple(row) for row in conn.execute('SELECT * FROM consents')]
            plan=service.preview(actor,'SP-1042','alert-location',before='2021-01-01T00:00:00Z')
            self.assertEqual(plan['eligible'],1)
            service.apply(actor,'SP-1042','alert-location',plan['plan'],'LOCATION-PURGE-TICKET',before='2021-01-01T00:00:00Z')
            after=dict(conn.execute('SELECT * FROM alerts WHERE id=?',(alert['id'],)).fetchone())
            for key in alert:
                if key not in ('lat','lng','location_accuracy','location_recorded_at'): self.assertEqual(after[key],alert[key])
            self.assertIsNone(after['lat'])
            self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM consents')],security)
            self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM notification_outbox')],jobs)

    def test_unassigned_admin_and_foreign_exact_ids_cannot_delete(self):
        entry,_=self.entry()
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn)
            plan=service.preview(actor,'SP-1042','diary',entry_ids=[entry+1000])
            self.assertEqual(plan['eligible'],0)
            with self.assertRaises(ValueError): service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',entry_ids=[entry+1000])
            with conn: conn.execute('DELETE FROM case_access WHERE staff_id=?',(actor.id,))
            with self.assertRaises(PermissionError): self.preview(service,actor)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],1)

    @patch.dict('os.environ',{'DIARY_STORAGE_BACKEND':'database'})
    def test_database_photo_cleanup_and_audit_commit_together(self):
        self.entry(photo=True)
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            with conn:
                conn.execute("CREATE TRIGGER fail_media_audit BEFORE INSERT ON audit_log WHEN NEW.action='retention_media_deleted' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            import sqlite3
            with self.assertRaises(sqlite3.Error): service.cleanup_media(actor,'SP-1042',apply=True,reference='CLEANUP-TICKET')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_objects').fetchone()[0],1)
            with conn: conn.execute('DROP TRIGGER fail_media_audit')
            self.assertEqual(service.cleanup_media(actor,'SP-1042',apply=True,reference='CLEANUP-TICKET')['deleted'],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_objects').fetchone()[0],0)

    def test_shared_object_reference_prevents_physical_deletion(self):
        entry,_=self.entry(photo=True)
        with closing(fixtures.db.connect()) as conn, conn:
            row=conn.execute('SELECT * FROM diary_entries WHERE id=?',(entry,)).fetchone()
            conn.execute("INSERT INTO diary_entries(user_id,client_id,note,photo_path,file_hash) VALUES(?,'legacy-retained-reference','Fictional retained evidence',?,?)",(row['user_id'],row['photo_path'],row['file_hash']))
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            self.assertEqual(service.cleanup_media(actor,'SP-1042',apply=True,reference='CLEANUP-TICKET')['blocked'],1)
            self.assertEqual(len(os.listdir(self.upload_dir)),1)

    def test_cli_defaults_to_preview_and_requires_an_exact_confirmed_plan(self):
        self.entry()
        with closing(fixtures.db.connect()) as conn: actor=self.actor(conn)
        runner=fixtures.avenra_app.app.test_cli_runner()
        args=['retention','--actor-id',str(actor.id),'--case-code','SP-1042','--kind','diary','--before','2021-01-01T00:00:00Z']
        preview=runner.invoke(args=args)
        self.assertEqual(preview.exit_code,0,preview.output)
        import json
        plan=json.loads(preview.output)
        self.assertEqual(plan['eligible'],1)
        self.assertNotIn('Fictional',preview.output)
        rejected=runner.invoke(args=args+['--apply'])
        self.assertNotEqual(rejected.exit_code,0)
        with closing(fixtures.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],1)

    def test_ambiguous_or_offset_receipt_times_are_not_misclassified(self):
        entry,_=self.entry()
        with closing(fixtures.db.connect()) as conn, conn:
            uid=conn.execute('SELECT user_id FROM diary_entries WHERE id=?',(entry,)).fetchone()[0]
            conn.execute("INSERT INTO diary_entries(user_id,client_id,note,received_at) VALUES(?,'ambiguous-retention-time','Fictional legacy note','2010-01-01')",(uid,))
            conn.execute("INSERT INTO diary_entries(user_id,client_id,note,received_at) VALUES(?,'later-offset-retention-time','Fictional offset note','2020-12-31T23:30:00-01:00')",(uid,))
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn); plan=self.preview(service,actor)
            self.assertEqual(plan['eligible'],1)
            service.apply(actor,'SP-1042','diary',plan['plan'],'APPROVED-TICKET',before='2021-01-01T00:00:00Z')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM diary_entries').fetchone()[0],2)

    def test_location_tombstone_defeats_authorized_late_callback(self):
        import hashlib
        import secrets
        import time
        from datetime import datetime,timezone
        token=secrets.token_urlsafe(32)
        with closing(fixtures.db.connect()) as conn, conn:
            uid=conn.execute("SELECT id FROM users WHERE case_code='SP-1042'").fetchone()[0]
            conn.execute('UPDATE users SET is_active=1 WHERE id=?',(uid,))
            conn.execute('INSERT INTO survivor_devices(token_hash,user_id,expires_at) VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,int(time.time())+600))
        phone=fixtures.avenra_app.app.test_client(); phone.set_cookie('avenra_device',token)
        headers={'Origin':'http://localhost','X-Queue-Owner':str(uid)}
        self.assertEqual(phone.post('/api/consents',json={'item':'location_sharing','active':True},headers=headers).status_code,200)
        permission=phone.get('/api/alerts/location-permission').json['token']
        fix={'lat':-33.9,'lng':18.4,'location_accuracy':22,'location_recorded_at':datetime.now(timezone.utc).isoformat(), 'location_consent_token':permission}
        response=phone.post('/api/alerts',json={'client_id':'tap-retention-callback',**fix},headers=headers)
        self.assertEqual(response.status_code,201)
        with closing(fixtures.db.connect()) as conn, conn:
            conn.execute("UPDATE alerts SET status='resolved' WHERE id=?",(response.json['id'],))
            conn.execute("UPDATE notification_outbox SET status='cancelled' WHERE alert_id=?",(response.json['id'],))
        with closing(fixtures.db.connect()) as conn:
            service=self.service(conn); actor=self.actor(conn)
            plan=service.preview(actor,'SP-1042','alert-location',entry_ids=[response.json['id']])
            service.apply(actor,'SP-1042','alert-location',plan['plan'],'PURGE-CALLBACK-TICKET',entry_ids=[response.json['id']])
        self.assertEqual(phone.post('/api/alerts/by-client/tap-retention-callback/location',json=fix,headers=headers).status_code,410)
