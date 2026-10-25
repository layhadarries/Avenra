"""Private transactional photo storage for the bounded hosted demonstration.

Objects live in the same private database transaction as entry metadata and audit.
This is not a general large-file store or a real-data encryption certification.
"""
import hashlib
import os
import re
from avenra.services.diary_service import DiaryStorageBackend, LEGACY_MAX_PHOTO_BYTES

class DatabaseDiaryStorage(DiaryStorageBackend):
    database_backed = True

    def __init__(self, connection, limit=None):
        self.conn = connection
        self.limit = int(limit if limit is not None else os.environ.get('DIARY_STORAGE_LIMIT_BYTES', 80 * 1024 * 1024))
        if not 1 <= self.limit <= 100 * 1024 * 1024:
            raise ValueError('Diary storage limit must be between 1 byte and 100 MiB')

    def _name(self, name):
        if not isinstance(name,str) or not re.fullmatch(r'diary_[A-Za-z0-9_-]+\.jpg',name):
            raise OSError('Invalid private object name')
        return name

    def put_object(self, object_name, data, expected_sha256):
        name=self._name(object_name)
        if not self.conn.in_transaction:
            raise OSError('Photo storage requires the entry transaction')
        if not isinstance(data,bytes) or not 0 < len(data) <= LEGACY_MAX_PHOTO_BYTES:
            raise OSError('Invalid photo length')
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise OSError('Photo digest mismatch')
        used=self.conn.execute('SELECT COALESCE(SUM(byte_count),0) FROM diary_objects').fetchone()[0]
        if used + len(data) > self.limit:
            raise OSError('Private storage quota reached')
        self.conn.execute('INSERT INTO diary_objects(object_name,data,sha256,byte_count) VALUES(?,?,?,?)',
                          (name,data,expected_sha256,len(data)))

    def get_object(self, object_name, max_bytes=LEGACY_MAX_PHOTO_BYTES):
        name=self._name(object_name)
        row=self.conn.execute('SELECT data,sha256,byte_count FROM diary_objects WHERE object_name=?',(name,)).fetchone()
        if row is None or row['byte_count'] > max_bytes:
            raise OSError('Photo unavailable')
        raw=bytes(row['data'])
        if len(raw) != row['byte_count'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise OSError('Photo integrity unavailable')
        return raw

    def verify_object(self, object_name, expected_sha256, max_bytes=LEGACY_MAX_PHOTO_BYTES):
        try:return hashlib.sha256(self.get_object(object_name,max_bytes)).hexdigest() == expected_sha256
        except OSError:return False

    def delete_object(self, object_name):
        self.conn.execute('DELETE FROM diary_objects WHERE object_name=?',(self._name(object_name),))

    def reconcile_orphans(self, referenced_names):
        # Report only. Never erase evidence as part of a request or upgrade.
        return [r['object_name'] for r in self.conn.execute('SELECT object_name FROM diary_objects')
                if r['object_name'] not in referenced_names]
