"""Privately configure hosted dashboard and matching operator CLI environment."""
import getpass
import os
from pathlib import Path
import secrets
import shlex
import subprocess
from urllib.parse import urlsplit


def main():
    directory=Path.home()/'.local/share/avenra-hosted'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    target=directory/'runtime.fish'
    if target.exists():
        raise SystemExit('Hosted configuration already exists. Preserve its SECRET_KEY; do not overwrite it.')
    dburl=getpass.getpass('Supabase transaction pooler URI (hidden; same value as Vercel DATABASE_URL): ')
    parsed=urlsplit(dburl)
    if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or not parsed.hostname.endswith('.pooler.supabase.com') or not parsed.password:
        raise SystemExit('Expected a Supabase pooler PostgreSQL URI. Nothing saved.')
    values={'DATABASE_URL':dburl,'SECRET_KEY':secrets.token_urlsafe(48),
        'APP_ENV':'production','COOKIE_SECURE':'1',
        'AVENRA_WEBPUSH_ENABLED':'0','AVENRA_SMS_ENABLED':'0','AVENRA_PUSH_SELF_TEST':'0'}
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:
        for key,value in values.items(): out.write('set -gx '+key+' '+shlex.quote(value)+'\n')
    print('Saved private hosted CLI settings to '+str(target)+'. Never share this file.')
    for key,value in values.items():
        if key=='DATABASE_URL': continue # Already configured as a Vercel secret.
        result=subprocess.run(['npx','vercel@latest','env','add',key,'--environment','production','--type','secret'],
                              input=value,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if result.returncode:
            raise SystemExit('Could not add '+key+'. Private configuration is preserved. Review Vercel environment settings; do not regenerate SECRET_KEY.')
        print('Configured '+key)
    print('Environment configured. No email sent and no deployment started.')

if __name__=='__main__': main()
