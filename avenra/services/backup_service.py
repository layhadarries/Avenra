"""Bounded encrypted SQLite/storage snapshots and strictly isolated restore drills.

This is not Supabase PITR, a PostgreSQL dump, or proof of provider disaster recovery.
Keys and runtime environment variables are never included in the archive.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zipfile
from cryptography.fernet import Fernet, InvalidToken
from avenra.services.diary_service import LocalDiaryStorage


class IsolatedBackupService:
    MAX_BYTES=128*1024*1024

    @staticmethod
    def _write(path, data):
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())

    @staticmethod
    def _cipher(key):
        try: return Fernet(key)
        except (ValueError,TypeError): raise ValueError('valid_separate_backup_key_required') from None

    def _inventory(self, database, uploads):
        files={}; storage=LocalDiaryStorage(str(uploads)); objects={}
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory=sqlite3.Row
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('database_integrity_failed')
            has_objects=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='diary_objects'").fetchone()
            if has_objects:
                for row in conn.execute('SELECT object_name,data,sha256,byte_count FROM diary_objects'):
                    raw=bytes(row['data'])
                    if len(raw)!=row['byte_count'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
                        raise ValueError('database_photo_integrity_failed')
                    objects[row['object_name']]=row['sha256']
            for row in conn.execute('SELECT photo_path,file_hash FROM diary_entries WHERE photo_path IS NOT NULL'):
                name=row['photo_path']
                if not isinstance(name,str) or not re.fullmatch(r'diary_[A-Za-z0-9_-]+\.jpg',name):
                    raise ValueError('unsafe_private_photo_name')
                if name in objects:
                    actual=objects[name]
                else:
                    raw=storage.get_object(name)
                    files['media/'+name]=raw
                    actual=hashlib.sha256(raw).hexdigest()
                if row['file_hash'] and actual!=row['file_hash']:
                    raise ValueError('photo_metadata_integrity_failed')
        # Preserve retained orphans/quarantine bytes too; a pending cleanup or
        # legal hold must not silently lose media merely because metadata was
        # logically removed. These hashes describe the snapshot, not capture time.
        uploads=Path(uploads)
        if uploads.exists():
            for folder,prefix in ((uploads,'media/'),(uploads/'.quarantine','quarantine/')):
                if folder.is_symlink(): raise OSError('unsafe_media_directory')
                if not folder.exists(): continue
                for path in folder.iterdir():
                    if folder==uploads and path.name=='.quarantine': continue
                    if not re.fullmatch(r'diary_[A-Za-z0-9_-]+\.jpg',path.name): raise OSError('unrecognized_private_storage_file')
                    if prefix+path.name not in files:
                        files[prefix+path.name]=LocalDiaryStorage(str(folder)).get_object(path.name)
                    if sum(map(len,files.values()))>self.MAX_BYTES: raise ValueError('backup_budget_exceeded')
        return files

    def create(self, source_sqlite, uploads, archive, key):
        cipher=self._cipher(key)
        source=Path(source_sqlite).resolve(); archive=Path(archive).resolve(); uploads=Path(uploads).resolve()
        if not source.is_file() or archive.is_relative_to(uploads): raise ValueError('invalid_backup_paths')
        if archive.exists(): raise FileExistsError('archive_exists')
        archive.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='avenra-snapshot-') as directory:
            snapshot=Path(directory)/'database.sqlite3'
            self._write(snapshot,b'')
            with closing(sqlite3.connect(source,timeout=10)) as guard:
                guard.execute('PRAGMA busy_timeout=10000')
                # The second read connection can back up while this reservation
                # excludes application upload/cleanup writers and stabilizes media.
                guard.execute('BEGIN IMMEDIATE')
                try:
                    with closing(sqlite3.connect(source)) as reader, closing(sqlite3.connect(snapshot)) as target:
                        reader.backup(target)
                    files=self._inventory(snapshot,uploads)
                    files['database.sqlite3']=snapshot.read_bytes()
                    if sum(map(len,files.values()))>self.MAX_BYTES: raise ValueError('backup_budget_exceeded')
                    manifest={'version':1,'engine':'sqlite','snapshot_at':datetime.now(timezone.utc).isoformat(),
                        'files':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in files.items()}}
                    buffer=io.BytesIO()
                    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as package:
                        for name,raw in files.items(): package.writestr(name,raw)
                        package.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
                    encrypted=cipher.encrypt(buffer.getvalue())
                finally:
                    guard.rollback()
            self._write(archive,encrypted)
        return {'engine':'sqlite','media_files':len(files)-1,
                'encrypted_bytes':len(encrypted),'archive_sha256':hashlib.sha256(encrypted).hexdigest()}

    def restore(self, archive, target, key):
        target=Path(target).resolve()
        if target.exists(): raise FileExistsError('restore_target_exists')
        archive=Path(archive)
        if archive.stat().st_size>self.MAX_BYTES*2: raise ValueError('restore_budget_exceeded')
        try: plaintext=self._cipher(key).decrypt(archive.read_bytes())
        except InvalidToken: raise ValueError('backup_authentication_failed') from None
        if len(plaintext)>self.MAX_BYTES+1024*1024: raise ValueError('restore_budget_exceeded')
        try:
            with zipfile.ZipFile(io.BytesIO(plaintext)) as package:
                names=package.namelist()
                if len(names)!=len(set(names)) or 'manifest.json' not in names or 'database.sqlite3' not in names:
                    raise ValueError('invalid_backup_manifest')
                if sum(info.file_size for info in package.infolist())>self.MAX_BYTES+1024*1024:
                    raise ValueError('restore_budget_exceeded')
                manifest=json.loads(package.read('manifest.json'))
                if not isinstance(manifest,dict) or type(manifest.get('version')) is not int or manifest['version']!=1 or manifest.get('engine')!='sqlite' or not isinstance(manifest.get('files'),dict) or set(manifest['files'])!=set(names)-{'manifest.json'}:
                    raise ValueError('invalid_backup_manifest')
                files={}
                for name,expected in manifest['files'].items():
                    if not isinstance(expected,dict) or set(expected)!={'bytes','sha256'} or type(expected['bytes']) is not int or not 0<=expected['bytes']<=self.MAX_BYTES or not isinstance(expected['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',expected['sha256']):
                        raise ValueError('invalid_backup_manifest')
                    if name!='database.sqlite3' and not re.fullmatch(r'(?:media|quarantine)/diary_[A-Za-z0-9_-]+\.jpg',name):
                        raise ValueError('unsafe_restore_path')
                    raw=package.read(name)
                    if len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:
                        raise ValueError('restore_checksum_failed')
                    files[name]=raw
        except (zipfile.BadZipFile,KeyError,TypeError,UnicodeError):
            raise ValueError('invalid_backup_archive') from None
        # mkdir is the no-overwrite reservation, including a race with another
        # operator. A failed copy retains an explicit incomplete marker.
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        target.mkdir(mode=0o700,exist_ok=False)
        self._write(target/'RESTORE_INCOMPLETE',b'Incomplete isolated restore; do not use.\n')
        uploads=target/'uploads'; uploads.mkdir(mode=0o700)
        for name,raw in files.items():
            if name=='database.sqlite3': path=target/'database.sqlite3'
            elif name.startswith('quarantine/'):
                (uploads/'.quarantine').mkdir(mode=0o700,exist_ok=True)
                path=uploads/'.quarantine'/name.removeprefix('quarantine/')
            else: path=uploads/name.removeprefix('media/')
            self._write(path,raw)
        self._inventory(target/'database.sqlite3',uploads)
        self._write(target/'ISOLATED_RESTORE_DO_NOT_DEPLOY',b'Isolated SQLite/storage verification only; no provider disaster-recovery claim.\n')
        (target/'RESTORE_INCOMPLETE').unlink()
        return {'engine':'sqlite','database':str(target/'database.sqlite3'),'media_files':len(files)-1,
                'integrity':'verified','isolated':True}
