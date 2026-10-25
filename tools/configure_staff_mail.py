"""Configure SMTP privately; never echoes the password or sends a test message."""
import getpass
from pathlib import Path
import shlex
from urllib.parse import urlsplit


def main():
    runtime=Path.home()/'.local/share/avenra-hosted/runtime.fish'
    if not runtime.is_file():
        runtime=Path.home()/'.local/share/avenra-dashboard/runtime.fish'
    if not runtime.is_file():
        raise SystemExit('Run tools/prepare_dashboard.py first.')
    origin=input('Public dashboard HTTPS origin (for example https://staff.example.org): ').strip().rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit('A public HTTPS origin without a path is required. Nothing saved.')
    host=input('SMTP host: ').strip()
    port=input('SMTP port [587]: ').strip() or '587'
    mode=input('TLS mode: starttls or ssl [starttls]: ').strip() or 'starttls'
    username=input('SMTP username: ').strip()
    sender=input('Authorised sender email address: ').strip()
    password=getpass.getpass('SMTP password or app password (hidden): ')
    if not host or not port.isdecimal() or not 1<=int(port)<=65535 or mode not in ('starttls','ssl') or not username or not sender or not password:
        raise SystemExit('Incomplete configuration. Nothing saved.')
    values={'PUBLIC_BASE_URL':origin,'SMTP_HOST':host,'SMTP_PORT':port,'SMTP_TLS_MODE':mode,
            'SMTP_USERNAME':username,'SMTP_FROM':sender,'SMTP_PASSWORD':password}
    with runtime.open('a') as fh:
        fh.write('\n# Mail configuration; later settings replace earlier values.\n')
        for key,value in values.items():
            fh.write('set -gx '+key+' '+shlex.quote(value)+'\n')
    runtime.chmod(0o600)
    print('Mail configuration saved privately. Source runtime.fish again. No email sent.')

if __name__=='__main__':
    main()
