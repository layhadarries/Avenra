"""Hosted demo preparation. No real incident data is created or deleted.

--prepare: encrypted row snapshot, additive schema, synthetic rollback probe,
           private push keys and Vercel production configuration.
--verify: read-only public HTTP + authenticated worker dry run.
--schedule: enable a Vault-backed hosted minute scheduler after verification.
--disable-scheduler: pause only Avenra's worker schedule.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=Path.home()/'.local/share/avenra-hosted'
CONFIG=PRIVATE/'stage6.json'
RELEASE='stage6-demo-20261025'


def private_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.parent.chmod(0o700)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(data)


def load_config(create=False):
    if CONFIG.exists():
        if CONFIG.stat().st_mode & 0o077:raise RuntimeError('Private Stage 6 configuration permissions must be 600')
        return json.loads(CONFIG.read_text())
    if not create:raise RuntimeError('Run --prepare first')
    from avenra.services.push_service import generate_keys
    from email.utils import parseaddr
    existing=os.environ.get('WEBPUSH_KEY_DIR')
    directory=Path(existing).expanduser() if existing else PRIVATE/'webpush'
    if not directory.exists():generate_keys(directory)
    elif not (directory/'vapid-private.pem').is_file() or not (directory/'subscription-storage.key').is_file():
        raise RuntimeError('Existing push key directory is incomplete; keys were not replaced')
    subject=os.environ.get('WEBPUSH_SUBJECT')
    if not subject:
        address=parseaddr(os.environ.get('SMTP_FROM',''))[1]
        if not address:raise RuntimeError('Set WEBPUSH_SUBJECT to mailto:your-operator-email before preparation')
        subject='mailto:'+address
    values={'AVENRA_WORKER_TOKEN':secrets.token_urlsafe(48),
            'WEBPUSH_PRIVATE_KEY_PEM':(directory/'vapid-private.pem').read_text(),
            'WEBPUSH_STORAGE_KEY':(directory/'subscription-storage.key').read_text().strip(),
            'WEBPUSH_SUBJECT':subject,'AVENRA_WEBPUSH_ENABLED':'1',
            'AVENRA_SMS_ENABLED':'0','AVENRA_PUSH_SELF_TEST':'0',
            'APP_ENV':'production','COOKIE_SECURE':'1'}
    from avenra.services.push_service import PushSettings
    PushSettings(values)
    private_write(CONFIG,json.dumps(values).encode())
    return values


def connection():
    if not os.environ.get('DATABASE_URL'):raise RuntimeError('Source the private hosted runtime first')
    import db
    return db.connect()


def backup(conn):
    """Portable encrypted row snapshot; never include the database URI."""
    from cryptography.fernet import Fernet
    import datetime
    key=PRIVATE/'stage6-backup.key'
    if not key.exists():private_write(key,Fernet.generate_key())
    if key.stat().st_mode & 0o077:raise RuntimeError('Backup key permissions must be 600')
    rows=conn.raw.execute("SELECT tablename FROM pg_tables WHERE schemaname='avenra' ORDER BY tablename").fetchall()
    from psycopg import sql
    snapshot={'format':'avenra-private-rows-v1','tables':{}}
    conn.raw.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        for (name,) in rows:
            cursor=conn.raw.execute(sql.SQL('SELECT * FROM avenra.{}').format(sql.Identifier(name)))
            columns=[c.name for c in cursor.description]
            data=[]
            for row in cursor.fetchall():
                data.append({k:({'$bytes':base64.b64encode(bytes(v)).decode()} if isinstance(v,(bytes,bytearray,memoryview)) else str(v) if isinstance(v,(datetime.datetime,datetime.date)) else v) for k,v in zip(columns,row)})
            snapshot['tables'][name]=data
        conn.raw.commit()
    except Exception:
        conn.raw.rollback();raise
    raw=json.dumps(snapshot,sort_keys=True).encode()
    cipher=Fernet(key.read_bytes()).encrypt(raw)
    path=PRIVATE/'backups'/('stage6-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)+'.fernet')
    private_write(path,cipher)
    if Fernet(key.read_bytes()).decrypt(path.read_bytes()) != raw:raise RuntimeError('Backup verification failed')
    print('PASS: encrypted row snapshot and decrypt/readback verification:',path)
    print('Keep its private key separately backed up. A row snapshot is not a provider disaster-recovery backup.')


def synthetic_probe(conn):
    """Real PostgreSQL SQL translation/identity/blob/rollback test, never sends."""
    from avenra.repositories.diary_repository import DiaryRepository
    from avenra.services.database_diary_storage import DatabaseDiaryStorage
    case='CHECK-'+secrets.token_hex(12)
    photo=b'synthetic-rollback-probe'
    conn.execute('BEGIN IMMEDIATE')
    try:
        cursor=conn.execute("INSERT INTO users(name,role,email,case_code,is_active) VALUES(?,'survivor',?,?,1)",('Synthetic rollback probe',secrets.token_hex(16)+'@example.invalid',case))
        if not cursor.lastrowid:raise RuntimeError('Hosted generated ID check failed')
        storage=DatabaseDiaryStorage(conn)
        name='diary_'+secrets.token_hex(16)+'.jpg'
        storage.put_object(name,photo,hashlib.sha256(photo).hexdigest())
        if storage.get_object(name)!=photo:raise RuntimeError('Hosted storage roundtrip failed')
    finally:conn.rollback()
    if conn.execute('SELECT 1 FROM users WHERE case_code=?',(case,)).fetchone():raise RuntimeError('Hosted rollback check failed')
    print('PASS: verified-TLS connection, hosted generated IDs, transactional private blobs and rollback; no probe records retained.')


def configure_vercel(values):
    if not (ROOT/'.vercel/project.json').is_file():raise RuntimeError('Run npx vercel@65.2.0 link in the repository first')
    for key,value in values.items():
        result=subprocess.run(['npx','vercel@65.2.0','env','update',key,'production','--yes'],input=value,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=ROOT)
        if result.returncode:
            result=subprocess.run(['npx','vercel@65.2.0','env','add',key,'--environment','production','--type','secret'],input=value,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=ROOT)
        if result.returncode:raise RuntimeError('Could not configure '+key+'; no deployment was started')
        print('Configured',key,'(value hidden)')


def require_local_acceptance():
    path=PRIVATE/'stage6-local-check.json'
    if not path.is_file():raise RuntimeError('Run the updater with --verify --commit --push before hosted preparation')
    report=json.loads(path.read_text())
    if report.get('local_automated_checks') is not True:raise RuntimeError('Local release checks are incomplete')
    for name,digest in report.get('files',{}).items():
        target=(ROOT/name).resolve()
        if not target.is_relative_to(ROOT) or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Source changed since local acceptance: '+name)
    if not report.get('files'):raise RuntimeError('Local acceptance manifest is empty')


def base_url():
    value=os.environ.get('PUBLIC_BASE_URL','https://avenra-delta.vercel.app').rstrip('/')
    parsed=urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise RuntimeError('PUBLIC_BASE_URL must be a bare HTTPS origin')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def verify(values):
    require_local_acceptance()
    if subprocess.run(['git','diff','--quiet'],cwd=ROOT).returncode:raise RuntimeError('Commit the verified source before live verification')
    base=base_url(); opener=urllib.request.build_opener(NoRedirect())
    def fetch(path,data=None,token=None):
        headers={}
        if data is not None:headers['Content-Type']='application/json'
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:
            with opener.open(req,timeout=25) as response:return response.status,response.read(65536),response.headers
        except urllib.error.HTTPError as error:return error.code,error.read(65536),error.headers
    for path in ('/login','/survivor/','/survivor/install.html','/survivor/diary.html','/survivor/clear-sky-app-qr.png'):
        status,_,_=fetch(path)
        if status!=200:raise RuntimeError('Live public route failed: '+path+' ('+str(status)+')')
    for path in ('/api/device','/api/my-access','/api/diary'):
        status,_,headers=fetch(path)
        if status!=401 or 'no-store' not in headers.get('Cache-Control',''):raise RuntimeError('Live private boundary failed: '+path)
    status,_,_=fetch('/api/contacts',None,None)
    if status!=401:raise RuntimeError('Anonymous contacts boundary failed')
    status,body,_=fetch('/api/worker/tick',{'dry_run':True},values['AVENRA_WORKER_TOKEN'])
    if status!=200 or json.loads(body).get('release')!=RELEASE:raise RuntimeError('Live worker dry-run failed; deploy the prepared build before scheduling')
    expected_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if json.loads(body).get('commit')!=expected_commit:raise RuntimeError('Deployed source commit does not match the current verified checkout')
    report={'release':RELEASE,'commit':expected_commit,'public_and_private_http':True,'worker_dry_run':True,'phone_verified':False,'pilot_ready':False}
    target=PRIVATE/'stage6-hosted-check.json'
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(report,stream,indent=2)
    print('PASS: live HTTPS public routes, private unauthenticated boundaries, no-store and authenticated worker dry run. No notification sent.')


def scheduler(conn,values,disable=False):
    # Raw psycopg is used for extension/catalog SQL; request values stay bound.
    raw=conn.raw
    if disable:
        exists=raw.execute("SELECT 1 FROM pg_extension WHERE extname='pg_cron'").fetchone()
        if exists:
            for (jobid,) in raw.execute("SELECT jobid FROM cron.job WHERE jobname='avenra-worker-minute'").fetchall():raw.execute('SELECT cron.unschedule(%s)',(jobid,))
        print('Avenra worker schedule disabled.');return
    raw.execute('CREATE EXTENSION IF NOT EXISTS pg_cron')
    raw.execute('CREATE EXTENSION IF NOT EXISTS pg_net')
    raw.execute('REVOKE USAGE ON SCHEMA cron,net FROM PUBLIC,anon,authenticated')
    raw.execute('REVOKE SELECT ON vault.decrypted_secrets FROM PUBLIC,anon,authenticated')
    for name,value in (('avenra_worker_token',values['AVENRA_WORKER_TOKEN']),('avenra_worker_url',base_url()+'/api/worker/tick')):
        existing=raw.execute('SELECT id FROM vault.secrets WHERE name=%s',(name,)).fetchone()
        if existing:raw.execute('SELECT vault.update_secret(%s,%s)',(existing[0],value))
        else:raw.execute('SELECT vault.create_secret(%s,%s)',(value,name))
    command="""SELECT net.http_post(
      url:=(SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='avenra_worker_url'),
      headers:=jsonb_build_object('Content-Type','application/json','Authorization','Bearer '||(SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='avenra_worker_token')),
      body:='{}'::jsonb,timeout_milliseconds:=20000);"""
    raw.execute('SELECT cron.schedule(%s,%s,%s)',('avenra-worker-minute','* * * * *',command))
    if not raw.execute("SELECT 1 FROM cron.job WHERE jobname='avenra-worker-minute' AND active").fetchone():raise RuntimeError('Worker schedule verification failed')
    print('PASS: hosted minute schedule installed; credentials are in Vault, not cron SQL. Only opted-in Web Push jobs can send. No SMS fallback.')


def verify_scheduler(conn, since=None):
    import datetime,time
    since=since or (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=120)).strftime('%Y-%m-%dT%H:%M:%SZ')
    print('Waiting for a real hosted scheduler heartbeat (up to 90 seconds)…',flush=True)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        row=conn.execute("SELECT last_seen_at,release FROM worker_state WHERE key='webpush'").fetchone()
        if row and row['last_seen_at']>=since and row['release']==RELEASE:
            print('PASS: deployed hosted worker heartbeat confirmed. Physical notification receipt still requires the phone test.')
            return
        time.sleep(2)
    raise RuntimeError('No fresh hosted worker heartbeat. Leave Stage 6 incomplete and inspect scheduler/runtime status without printing credentials')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    for flag in ('prepare','verify','schedule','disable-scheduler','verify-scheduler'):group.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.prepare:
        require_local_acceptance()
        values=load_config(create=True)
        values['PUBLIC_BASE_URL']=base_url()
        if subprocess.run(['git','diff','--quiet'],cwd=ROOT).returncode:
            raise RuntimeError('Commit the locally verified source before hosted preparation')
        values['AVENRA_RELEASE_COMMIT']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        # Vercel runtime derives its CA path from the bundled repository certificate.
        with connection() as conn:
            backup(conn)
            for name in ('002_device_enrollment.sql','003_stage6_private_diary.sql'):
                conn.raw.execute((ROOT/'sql'/name).read_text(),prepare=False)
            missing=conn.execute("SELECT COUNT(*) FROM diary_entries e LEFT JOIN diary_objects o ON o.object_name=e.photo_path WHERE e.photo_path IS NOT NULL AND o.object_name IS NULL").fetchone()[0]
            if missing:raise RuntimeError('Existing diary photos need an explicit verified import; no deployment was started')
            synthetic_probe(conn)
        configure_vercel(values)
        print('Prepared. Run the local acceptance command, push, then deploy. No schedule has been enabled.')
    elif args.verify:verify(load_config())
    else:
        values=load_config()
        if args.schedule:verify(values)
        with connection() as conn:
            if args.verify_scheduler:
                verify_scheduler(conn)
            else:
                import datetime
                since=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                scheduler(conn,values,disable=args.disable_scheduler)
                if args.schedule:verify_scheduler(conn,since)

if __name__=='__main__':
    try:main()
    except Exception as error:
        # Never print libpq URI diagnostics, SMTP data or provider secrets.
        safe=str(error) if isinstance(error,RuntimeError) else type(error).__name__
        print('STOP:',safe,file=sys.stderr)
        raise SystemExit(1)
