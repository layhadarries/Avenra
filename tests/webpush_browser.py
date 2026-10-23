"""Browser opt-in contracts using fake browser push subscription; no network push."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from playwright.sync_api import expect
from stage0_browser import main


def check(page,context,base,env):
    phone=context.browser.new_context(viewport={'width':390,'height':844})
    errors=[];urls=[]
    script='''
    Object.defineProperty(Notification, 'requestPermission', {value: async () => 'granted'});
    PushManager.prototype.getSubscription = async () => null;
    PushManager.prototype.subscribe = async () => ({toJSON:()=>(SUBSCRIPTION)});
    '''.replace('SUBSCRIPTION',os.environ['AVENRA_FAKE_PUSH_SUBSCRIPTION'])
    phone.add_init_script(script)
    tab=phone.new_page()
    tab.on('pageerror',lambda error:errors.append(str(error)))
    tab.on('request',lambda req:urls.append(req.url))
    tab.goto(base+'/survivor/setup.html')
    tab.get_by_role('button',name='Invite for notifications').first.click()
    field=tab.get_by_label('Contact invitation link')
    expect(field).to_be_visible()
    link=field.input_value();assert '#invite=' in link
    token=link.split('#invite=')[1]
    tab.goto(link)
    expect(tab.get_by_role('button',name='Accept and enable notifications')).to_be_visible()
    assert tab.url==base+'/contact-push/'
    tab.get_by_role('button',name='Accept and enable notifications').click()
    expect(tab.locator('#status')).to_have_text('Notifications enabled for this contact invitation.')
    expect(tab.get_by_role('button',name='Stop notifications on this browser')).to_be_visible()
    assert not any(token in url for url in urls)
    assert tab.evaluate('localStorage.length')==0
    tab.get_by_role('button',name='Stop notifications on this browser').click()
    expect(tab.locator('#result')).to_have_text('Notifications stopped on this browser.')
    assert not errors,errors
    phone.close()
    print('PASS: invite UI, fragment stripped without network leakage, explicit permission, registration, encrypted server opt-in and browser revocation. Fake push only.')

if __name__=='__main__':
    python=os.environ.get('AVENRA_SERVER_PYTHON',sys.executable)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(__file__).resolve().parents[1]
        subprocess.run([python,str(root/'tools/webpush_keys.py'),directory],check=True,cwd=root)
        os.environ.update(AVENRA_WEBPUSH_ENABLED='1',WEBPUSH_KEY_DIR=directory,
            WEBPUSH_SUBJECT='mailto:developer@example.test',AVENRA_PUSH_SELF_TEST='0')
        code="""import base64,json
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
key=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
b=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
print(json.dumps({'endpoint':'https://fcm.googleapis.com/fcm/send/fictional-browser','keys':{'p256dh':b(key),'auth':b(b'x'*16)}}))
"""
        os.environ['AVENRA_FAKE_PUSH_SUBSCRIPTION']=subprocess.check_output([python,'-c',code],text=True).strip()
        main(staff_check=check)
