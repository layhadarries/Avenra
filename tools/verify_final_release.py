"""Local release checks with provider credentials removed. Never deploys or sends messages."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
BROWSERS=(
    'staff_invitation_browser.py','password_recovery_browser.py',
    'hosted_pwa_pairing_browser.py','hosted_alert_queue_browser.py',
    'hosted_diary_queue_browser.py','stage2_pwa_browser.py',
    'stage3_case_browser.py','stage4_audit_browser.py',
    'stage5_pwa_browser.py','stage9_vault_browser.py',
    'weather_tap_browser.py','followup_privacy_browser.py',
)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browsers',action='store_true',help='Require Chromium acceptance tests too.')
    args=parser.parse_args()
    blocked=('SMTP_','TWILIO_','WEBPUSH_','STAFF_MFA_','DATABASE_','AVENRA_','VERCEL')
    env={key:value for key,value in os.environ.items() if not key.startswith(blocked) and key not in {'SECRET_KEY','DEVICE_TOKEN','PUBLIC_BASE_URL','COOKIE_SECURE','APP_ENV','UPLOADS_DIR'}}
    env.update(APP_ENV='development',AVENRA_SMS_ENABLED='0',AVENRA_WEBPUSH_ENABLED='0',AVENRA_PUSH_SELF_TEST='0')
    def run(command):
        subprocess.run(command,cwd=ROOT,env=env,check=True)
    run([sys.executable,'-m','pip','check'])
    run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'])
    run(['node','--test',*[str(path.relative_to(ROOT)) for path in sorted((ROOT/'tests').glob('*.cjs'))]])
    with tempfile.TemporaryDirectory(prefix='avenra-security-') as temporary:
        report=Path(temporary)
        run([sys.executable,'tools/security_gate.py','--run-bandit',str(report/'bandit.json'),'--secret-scan'])
        run([sys.executable,'-m','pip_audit','-r','requirements-lock.txt','--no-deps','--disable-pip','--strict','-f','json','-o',str(report/'dependencies.json')])
        run([sys.executable,'tools/security_gate.py','--dependency-report',str(report/'dependencies.json')])
    if args.browsers:
        for script in BROWSERS:
            run([sys.executable,str(Path('tests')/script)])
    print('PASS: requested local checks completed. Hosted configuration, delivery, phones and independent review are not attested.')

if __name__=='__main__':main()
