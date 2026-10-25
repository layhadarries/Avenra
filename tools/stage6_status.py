"""Record human phone acceptance without claiming an automated security certification."""
import argparse
import datetime
import json
import os
from pathlib import Path

CHECKS=[
 ('installed_phone','Installed Clear Sky from the hosted HTTPS URL on the target phone'),
 ('laptop_off','Powered off the development laptop and disconnected USB/ADB/tunnels'),
 ('mobile_data','Sent an alert over mobile data and saw it on an independently connected dashboard'),
 ('acknowledgement','Acknowledged on the dashboard and saw the phone status update'),
 ('offline_reopen','Saved offline, closed/reopened the app, reconnected and verified one durable server receipt'),
 ('diary_photo','Uploaded a fictional note/photo and viewed it again after reopening'),
 ('consent','Confirmed private/unshared evidence is hidden and consent withdrawal blocks assigned staff'),
 ('push','Opted in a consenting contact and physically confirmed hosted Web Push with the laptop off'),
 ('recovery','Recovered the original case on another browser and confirmed the old device lost access'),
 ('wifi','Repeated the core alert and diary flow over Wi-Fi'),
 ('quick_exit','Verified Quick Exit removes visible private content while committed pending entries remain'),
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-phone-checks',action='store_true',required=True)
    args=parser.parse_args()
    report={'scope':'Stage 6A fictional hosted demo','recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':{},'pilot_ready':False}
    for key,label in CHECKS:
        report['checks'][key]=input(label+' [yes/no]: ').strip().lower()=='yes'
    report['phone_acceptance_complete']=all(report['checks'].values())
    directory=Path.home()/'.local/share/avenra-hosted';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=directory/'stage6-phone-acceptance.json'
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as stream:json.dump(report,stream,indent=2)
    print('Phone acceptance complete.' if report['phone_acceptance_complete'] else 'Phone acceptance incomplete. Do not mark Stage 6 complete.')
    print('Real-survivor pilot approval remains separate. No incident details were requested or stored.')
    return 0 if report['phone_acceptance_complete'] else 1

if __name__=='__main__':raise SystemExit(main())
