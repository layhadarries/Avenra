"""Restore an encrypted row snapshot ONLY into an empty, migrated private schema.

Use a separate restore-test database. The source DATABASE_URL is never printed.
The existing schema must come from the reviewed sql/ migrations; this tool does
not drop a schema, erase a populated project, disable constraints or send jobs.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--key',type=Path,required=True)
    args=parser.parse_args()
    if not os.environ.get('DATABASE_URL'):raise RuntimeError('Configure the EMPTY restore-test database privately')
    if args.key.stat().st_mode & 0o077:raise RuntimeError('Backup key permissions must be 600')
    if args.snapshot.stat().st_size>256*1024*1024:raise RuntimeError('Snapshot exceeds bounded demo restore limit')
    from cryptography.fernet import Fernet
    document=json.loads(Fernet(args.key.read_bytes()).decrypt(args.snapshot.read_bytes()))
    if document.get('format')!='avenra-private-rows-v1' or not isinstance(document.get('tables'),dict):raise RuntimeError('Unsupported backup format')
    import db
    from psycopg import sql
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        raw=conn.raw
        known={row[0] for row in raw.execute("SELECT tablename FROM pg_tables WHERE schemaname='avenra'").fetchall()}
        if not set(document['tables'])<=known:raise RuntimeError('Apply the reviewed schema migrations to the restore-test database first')
        for name in known-{'schema_migrations','app_metadata'}:
            if raw.execute(sql.SQL('SELECT COUNT(*) FROM avenra.{}').format(sql.Identifier(name))).fetchone()[0]:raise RuntimeError('Restore refused: target contains application records')
        if raw.execute("SELECT COUNT(*) FROM avenra.app_metadata WHERE key<>'stage6_private_diary'").fetchone()[0]:raise RuntimeError('Restore refused: target has existing application metadata')
        dependencies={name:set() for name in document['tables']}
        rows=raw.execute("""SELECT child.relname,parent.relname FROM pg_constraint c
          JOIN pg_class child ON child.oid=c.conrelid JOIN pg_namespace n ON n.oid=child.relnamespace
          JOIN pg_class parent ON parent.oid=c.confrelid
          WHERE c.contype='f' AND n.nspname='avenra'""").fetchall()
        for child,parent in rows:
            if child in dependencies and parent in dependencies and child!=parent:dependencies[child].add(parent)
        order=[]
        while dependencies:
            ready=sorted(name for name,parents in dependencies.items() if not parents)
            if not ready:raise RuntimeError('Schema has cyclic dependencies; use reviewed provider restore tooling')
            order.extend(ready)
            for name in ready:del dependencies[name]
            for parents in dependencies.values():parents.difference_update(ready)
        for name in order:
            records=document['tables'][name]
            columns={row[0] for row in raw.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='avenra' AND table_name=%s",(name,)).fetchall()}
            for record in records:
                if not isinstance(record,dict) or not set(record)<=columns:raise RuntimeError('Snapshot columns do not match reviewed schema')
                names=list(record)
                values=[]
                for value in record.values():
                    if isinstance(value,dict):
                        if set(value)!={'$bytes'}:raise RuntimeError('Invalid encoded backup value')
                        value=base64.b64decode(value['$bytes'],validate=True)
                    values.append(value)
                query=sql.SQL('INSERT INTO avenra.{} ({}) VALUES ({})').format(sql.Identifier(name),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names))
                if name in {'schema_migrations','app_metadata'}:query+=sql.SQL(' ON CONFLICT DO NOTHING')
                raw.execute(query,values)
            if name not in {'schema_migrations','app_metadata'}:
                count=raw.execute(sql.SQL('SELECT COUNT(*) FROM avenra.{}').format(sql.Identifier(name))).fetchone()[0]
                if count!=len(records):raise RuntimeError('Restore count verification failed')
            if 'id' in columns:
                sequence=raw.execute("SELECT pg_get_serial_sequence(%s,'id')",('avenra.'+name,)).fetchone()[0]
                highest=raw.execute(sql.SQL('SELECT MAX(id) FROM avenra.{}').format(sql.Identifier(name))).fetchone()[0]
                if sequence and highest:raw.execute('SELECT setval(%s,%s,true)',(sequence,highest))
        from avenra.services.database_diary_storage import DatabaseDiaryStorage
        storage=DatabaseDiaryStorage(conn)
        for name,digest in raw.execute('SELECT object_name,sha256 FROM avenra.diary_objects').fetchall():
            if not storage.verify_object(name,digest):raise RuntimeError('Restored photo digest verification failed')
    print('PASS: empty-target restore, dependency-safe inserts, row counts, identity sequences and photo digests verified. No notification worker was invoked.')

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('STOP:',str(error) if isinstance(error,RuntimeError) else type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
