"""Public-key capture preserves offline emergency availability and stable receipts."""
import sqlite3
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async


def exercise(page, staff, base, env):
    context=staff.browser.new_context(service_workers='allow')
    try:
        phone=context.new_page(); phone.goto(base+'/survivor/cover.html')
        phone.evaluate('()=>CWQueue.ready')
        phone.wait_for_function('navigator.serviceWorker.controller !== null')
        owner=phone.evaluate('CWQueue.captureOwner()')
        assert context.request.post(base+'/api/consents',headers={'X-Device-Token':'demo-device'},data={'item':'location_sharing','active':True}).ok
        context.set_offline(True)
        phone.evaluate("owner=>CWQueue.queueAlert({client_id:'sealed-browser-fictional',owner_id:owner,client_ts:'2026-10-26T00:00:00Z',lat:-33.9,lng:18.4,location_accuracy:22})",owner)
        raw=phone.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-queue',1);r.onsuccess=()=>{const q=r.result.transaction('alerts').objectStore('alerts').getAll();q.onsuccess=()=>resolve(q.result);};})""")
        assert len(raw)==1 and 'sealed_alert' in raw[0], 'Offline alert payload must be encrypted before its durable commit'
        assert 'lat' not in raw[0] and 'client_ts' not in raw[0] and 'location_consent_token' not in raw[0]
        assert 'sealed_location' in raw[0] and 'lat' not in raw[0]['sealed_location']
        assert 'PRIVATE KEY' not in phone.evaluate('JSON.stringify(localStorage)')
        phone.close(); phone=context.new_page(); phone.goto(base+'/survivor/cover.html')
        assert phone.evaluate('CWQueue.queueSize()')==1
        context.set_offline(False); phone.evaluate('CWQueue.flushQueue()')
        wait_for_async(phone,'()=>CWQueue.queueSize().then(size=>size===0)')
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            rows=conn.execute('SELECT user_id,lat,lng FROM alerts WHERE client_id=?',('sealed-browser-fictional',)).fetchall()
        assert rows==[(owner,-33.9,18.4)]
        context.set_offline(True)
        phone.evaluate("owner=>CWQueue.queueAlert({client_id:'revoked-sealed-browser',owner_id:owner,lat:-33.9,lng:18.4})",owner)
        assert staff.request.post(base+'/api/consents',headers={'X-Device-Token':'demo-device'},data={'item':'location_sharing','active':False}).ok
        sent=[]
        phone.on('request',lambda request:sent.append(request.post_data_json) if request.method=='POST' and request.url==base+'/api/alerts' else None)
        context.set_offline(False); phone.evaluate('CWQueue.flushQueue()')
        wait_for_async(phone,'()=>CWQueue.queueSize().then(size=>size===0)')
        assert sent and 'sealed_location' not in sent[0] and sent[0]['suppress_location'] is True
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            assert conn.execute("SELECT lat,lng FROM alerts WHERE client_id='revoked-sealed-browser'").fetchone()==(None,None)
        # Missing cache must not block emergency capture or store unencrypted GPS.
        context.set_offline(True)
        phone.evaluate("localStorage.removeItem('clear-sky-alert-public-key-v1')")
        phone.close(); phone=context.new_page(); phone.goto(base+'/survivor/cover.html')
        phone.evaluate("owner=>CWQueue.queueAlert({client_id:'minimal-browser-fictional',owner_id:owner,client_ts:'2026-10-26T00:00:00Z',lat:-33.9,lng:18.4})",owner)
        raw=phone.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-queue',1);r.onsuccess=()=>{const q=r.result.transaction('alerts').objectStore('alerts').getAll();q.onsuccess=()=>resolve(q.result);};})""")
        assert len(raw)==1 and raw[0]['lat'] is None and raw[0]['client_ts'] is None
        context.set_offline(False); phone.evaluate('CWQueue.flushQueue()')
        wait_for_async(phone,'()=>CWQueue.queueSize().then(size=>size===0)')
        print('PASS: encrypted emergency queue survives offline close/reopen; receipt keeps original ID and consented GPS; missing key still saves a minimal GPS-free alert.')
    finally:
        context.close()


if __name__=='__main__': main(exercise)
