"""Privately configure Twilio; no network request or message is sent."""
import getpass
import os
from pathlib import Path
import shlex
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from avenra.services.sms_sender import TwilioSender


def main():
    runtime=Path.home()/'.local/share/avenra-hosted/runtime.fish'
    if not runtime.is_file():
        runtime=Path.home()/'.local/share/avenra-dashboard/runtime.fish'
    if not runtime.is_file():
        raise SystemExit('Create the private operator runtime with tools/prepare_dashboard.py first.')
    values={'APP_ENV':'production','AVENRA_SMS_ENABLED':'1',
            'TWILIO_ACCOUNT_SID':input('Twilio Account SID: ').strip(),
            'TWILIO_AUTH_TOKEN':getpass.getpass('Twilio Auth Token (hidden): '),
            'TWILIO_FROM_NUMBER':input('Twilio SMS-capable sender number (+countrycode): ').strip()}
    TwilioSender(values)
    if input('Enable billable SMS for explicitly opted-in trusted contacts? Type ENABLE: ').strip()!='ENABLE':
        raise SystemExit('Cancelled. Nothing saved.')
    with runtime.open('a') as handle:
        handle.write('\n# Explicit Twilio configuration; no test message sent.\n')
        for key,value in values.items():
            if key!='APP_ENV':handle.write('set -gx '+key+' '+shlex.quote(value)+'\n')
    os.chmod(runtime,0o600)
    print('Saved privately. Source runtime.fish again. No message sent. Configure the hosted environment separately.')

if __name__=='__main__':main()
