"""Bounded case-scoped retention plans, holds and durable deletion tombstones."""
from avenra.repositories.base import BaseRepository

SCHEMA = '''
CREATE TABLE IF NOT EXISTS retention_holds (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), reference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deletion_tombstones (
 user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, client_id TEXT NOT NULL,
 deleted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 PRIMARY KEY(user_id,kind,client_id)
);
CREATE TABLE IF NOT EXISTS retention_runs (
 plan_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 removed INTEGER NOT NULL, reference TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS retention_media_jobs (
 user_id INTEGER NOT NULL REFERENCES users(id), object_name TEXT NOT NULL, expected_sha256 TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','failed','blocked','deleted')),
 reason_code TEXT, reference TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 PRIMARY KEY(user_id,object_name)
)
'''


class RetentionRepository(BaseRepository):
    def held(self, uid):
        return self.conn.execute('SELECT 1 FROM retention_holds WHERE user_id=?',(uid,)).fetchone() is not None

    def epoch(self, case):
        return self.conn.execute("SELECT MAX(id) FROM audit_log WHERE case_code=? AND action IN ('retention_hold_set','retention_hold_released')",(case,)).fetchone()[0]

    def rows(self, uid, kind, before, entry_ids):
        if kind=='diary':
            query='''SELECT id,user_id,client_id,received_at,photo_path,file_hash,note_sha256,
                photo_sha256,entry_fingerprint,shared FROM diary_entries WHERE user_id=?'''
            column='received_at'
        elif kind=='alert-location':
            query='''SELECT id,user_id,client_id,created_at,status,lat,lng,location_accuracy,location_recorded_at
                FROM alerts WHERE user_id=? AND status='resolved' AND (lat IS NOT NULL OR lng IS NOT NULL)
                AND NOT EXISTS(SELECT 1 FROM notification_outbox n WHERE n.alert_id=alerts.id AND n.status IN ('pending','processing'))'''
            column='created_at'
        else:
            raise ValueError('unsupported_retention_kind')
        params=[uid]
        if entry_ids is not None:
            query+=' AND id IN ('+','.join('?' for _ in entry_ids)+')'
            params.extend(entry_ids)
        else:
            # Column names are from the fixed branches above, never user input.
            query+=' AND '+column+' IS NOT NULL AND '+column+'<?'
            params.append(before)
        return [dict(row) for row in self.conn.execute(query+' ORDER BY id LIMIT 101',params)]

    def unknown_times(self, uid):
        return self.conn.execute('SELECT COUNT(*) FROM diary_entries WHERE user_id=? AND received_at IS NULL',(uid,)).fetchone()[0]

    def was_deleted(self, uid, kind, client_id):
        return self.conn.execute('SELECT 1 FROM deletion_tombstones WHERE user_id=? AND kind=? AND client_id=?',
            (uid,kind,client_id)).fetchone() is not None

    def record_tombstone(self, uid, kind, client_id):
        if client_id is not None:
            self.conn.execute('INSERT INTO deletion_tombstones(user_id,kind,client_id) VALUES(?,?,?) ON CONFLICT DO NOTHING',(uid,kind,client_id))

    def remove(self, uid, kind, row, reference):
        self.record_tombstone(uid,kind,row['client_id'])
        if kind=='diary':
            if row['photo_path']:
                self.conn.execute('''INSERT INTO retention_media_jobs(user_id,object_name,expected_sha256,reference)
                    VALUES(?,?,?,?) ON CONFLICT DO NOTHING''',(uid,row['photo_path'],row['photo_sha256'] or row['file_hash'],reference))
            cursor=self.conn.execute('DELETE FROM diary_entries WHERE id=? AND user_id=?',(row['id'],uid))
        else:
            cursor=self.conn.execute('UPDATE alerts SET lat=NULL,lng=NULL,location_accuracy=NULL,location_recorded_at=NULL WHERE id=? AND user_id=?',(row['id'],uid))
        if cursor.rowcount!=1: raise RuntimeError('retention_scope_changed')

    def run(self, plan):
        return self.conn.execute('SELECT user_id,kind,removed FROM retention_runs WHERE plan_hash=?',(plan,)).fetchone()

    def record_run(self, uid, kind, plan, removed, reference):
        self.conn.execute('INSERT INTO retention_runs(plan_hash,user_id,kind,removed,reference) VALUES(?,?,?,?,?)',(plan,uid,kind,removed,reference))

    def media_pending(self, uid):
        return self.conn.execute("SELECT COUNT(*) FROM retention_media_jobs WHERE user_id=? AND status!='deleted'",(uid,)).fetchone()[0]

    def media_jobs(self, uid):
        return [dict(row) for row in self.conn.execute("SELECT * FROM retention_media_jobs WHERE user_id=? AND status!='deleted' ORDER BY created_at,object_name LIMIT 10",(uid,))]

    def media_blocked(self, name):
        referenced=self.conn.execute('SELECT 1 FROM diary_entries WHERE photo_path=?',(name,)).fetchone()
        held=self.conn.execute("SELECT 1 FROM retention_media_jobs j JOIN retention_holds h ON h.user_id=j.user_id WHERE j.object_name=? AND j.status!='deleted'",(name,)).fetchone()
        return bool(referenced or held)

    def finish_media(self, uid, name, status, reason):
        self.conn.execute('UPDATE retention_media_jobs SET status=?,reason_code=? WHERE user_id=? AND object_name=?',(status,reason,uid,name))
