"""Create a separate empty dashboard runtime without deleting evaluation data."""
import argparse
import os
from pathlib import Path
import secrets
import shlex
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path.home()/'.local/share/avenra-dashboard')
    parser.add_argument('--source-db',type=Path,default=ROOT/'avenra.db')
    args=parser.parse_args()
    directory=args.directory.expanduser().resolve()
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    target=directory/'dashboard.sqlite3'
    runtime=directory/'runtime.fish'
    if runtime.exists() or target.exists():
        if not runtime.exists() or not target.exists():
            raise SystemExit('Incomplete runtime exists. Inspect it before proceeding; no files overwritten.')
        print('Existing dashboard runtime preserved. No records removed.')
        print('Source configuration: '+str(runtime))
        return
    source=args.source_db.expanduser().resolve()
    if source==target:
        raise SystemExit('Source and destination must differ')
    if source.exists():
        backups=directory/'backups'; backups.mkdir(mode=0o700,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=backups/('pre-dashboard-'+stamp+'.sqlite3')
        # SQLite backup API includes committed WAL records. Original is read-only.
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(backup) as dst:
                src.backup(dst)
        backup.chmod(0o600)
        print('Previous database backed up; original database and uploads retained.')
    uploads=directory/'uploads'; uploads.mkdir(mode=0o700,exist_ok=True)
    os.environ['DATABASE_PATH']=str(target)
    sys.path.insert(0,str(ROOT))
    import db
    db.DB_PATH=str(target)
    db.init_db()
    with db.connect() as conn:
        for table in ('users','alerts','contacts','shelters','referrals','diary_entries','consents','audit_log'):
            if conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:
                raise SystemExit('New runtime unexpectedly contains records; configuration not written.')
    values={'APP_ENV':'development','COOKIE_SECURE':'0','DATABASE_PATH':str(target),
            'UPLOADS_DIR':str(uploads),'SECRET_KEY':secrets.token_urlsafe(48),
            'AVENRA_WEBPUSH_ENABLED':'0','AVENRA_PUSH_SELF_TEST':'0','AVENRA_SMS_ENABLED':'0'}
    fd=os.open(runtime,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as fh:
        fh.write('# Private local dashboard configuration. Never commit or share.\n')
        for key,value in values.items():
            fh.write('set -gx '+key+' '+shlex.quote(value)+'\n')
    print('PASS: empty dashboard database created; no demo users or records seeded.')
    print('Source configuration: '+str(runtime))
    print('Local HTTP configuration only. Hosted deployment requires production mode, secure cookies and persistent hosted storage.')

if __name__=='__main__':
    main()
