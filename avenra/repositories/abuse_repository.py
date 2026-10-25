"""Bounded, persistent fixed-window counters; no raw identity/IP storage."""
from avenra.repositories.base import BaseRepository

SCHEMA = '''CREATE TABLE IF NOT EXISTS auth_attempts (
 bucket TEXT PRIMARY KEY, window_start INTEGER NOT NULL, attempts INTEGER NOT NULL
)'''


class AbuseRepository(BaseRepository):
    def allow(self, buckets, now, window=900, capacity=10000):
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            self.conn.execute('DELETE FROM auth_attempts WHERE window_start<=?', (now-window,))
            allowed = True
            for bucket, maximum in buckets:
                exists = self.conn.execute('SELECT 1 FROM auth_attempts WHERE bucket=?', (bucket,)).fetchone()
                if exists is None and self.conn.execute('SELECT COUNT(*) FROM auth_attempts').fetchone()[0] >= capacity:
                    return False
                self.conn.execute('''INSERT INTO auth_attempts(bucket,window_start,attempts) VALUES(?,?,1)
                    ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN auth_attempts.attempts<? THEN auth_attempts.attempts+1 ELSE auth_attempts.attempts END''',
                    (bucket, now, maximum+1))
                count = self.conn.execute('SELECT attempts FROM auth_attempts WHERE bucket=?', (bucket,)).fetchone()[0]
                allowed = allowed and count <= maximum
            return allowed
