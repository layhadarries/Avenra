"""Synthetic ownership and durable-server acceptance, including offline reopen."""
import sqlite3
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async


def exercise(page,context,base,env):
    page.goto(base+'/devices')
    page.get_by_role('button',name='Create private pairing link',exact=True).click()
    expect(page.locator('#device-invite-link')).to_be_visible()
    invitation=page.locator('#device-invite-link').get_attribute('href')
    phone_context=context.browser.new_context(service_workers='block')
    sent=[]
    try:
        def record(request):
            if request.method=='POST' and request.url==base+'/api/diary':
                sent.append((request.post_data_json['client_id'],request.headers.get('x-queue-owner')))
        phone_context.on('request',record)
        phone=phone_context.new_page()
        phone.evaluate('window.__asyncPollingCounter=0')
        wait_for_async(phone, '() => Promise.resolve(++window.__asyncPollingCounter >= 3)')
        assert phone.evaluate('window.__asyncPollingCounter') >= 3
        phone.goto(invitation)
        phone.get_by_role('button',name='Connect my device',exact=True).click()
        expect(phone.locator('#status')).to_contain_text('Device connected')
        owner=phone_context.request.get(base+'/api/device').json()['account_id']
        phone.route('**/api/diary',lambda route:route.abort())
        phone.goto(base+'/survivor/diary.html')
        phone.wait_for_function('Boolean(window.CWDiary)')
        phone.locator('#diary-note').fill('Fictional online ownership test')
        phone.locator('#diary-save-btn').click()
        wait_for_async(phone, 'CWDiary.getQueuedItems().then(x=>x.length===1)')
        first=phone.evaluate('CWDiary.getQueuedItems()')[0]
        assert first.get('owner_id')==owner,'New diary entries must be bound when saved'
        phone_context.set_offline(True)
        phone.locator('#diary-note').fill('Fictional offline ownership test')
        phone.locator('#diary-save-btn').click()
        wait_for_async(phone, 'CWDiary.getQueuedItems().then(x=>x.length===2)')
        entries=phone.evaluate('CWDiary.getQueuedItems()')
        assert all(x.get('owner_id')==owner for x in entries)
        owned_ids={x['client_id'] for x in entries}
        phone.evaluate('''async ({sample,owner})=>{
            const db=await new Promise((resolve,reject)=>{let r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>resolve(r.result);r.onerror=reject;});
            await new Promise((resolve,reject)=>{let t=db.transaction('diary_entries','readwrite'),s=t.objectStore('diary_entries');
                let legacy=Object.assign({},sample,{client_id:'legacy-diary-owner',status:'queued'});delete legacy.owner_id;
                s.put(legacy);s.put(Object.assign({},sample,{client_id:'foreign-diary-owner',owner_id:owner+100000,status:'queued'}));
                t.oncomplete=resolve;t.onerror=t.onabort=reject;});db.close();
        }''',{'sample':first,'owner':owner})
        phone.unroute('**/api/diary');phone_context.set_offline(False)
        phone.evaluate('CWDiary.flushQueue(true)')
        wait_for_async(phone, 'ids=>CWDiary.getQueuedItems().then(items=>ids.every(id=>!items.some(x=>x.client_id===id)))',arg=list(owned_ids))
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            stored={r[0] for r in conn.execute('SELECT client_id FROM diary_entries WHERE user_id=?',(owner,))}
        assert stored==owned_ids,{'missing_from_server':sorted(owned_ids-stored),'unexpected_on_server':sorted(stored-owned_ids),'attempts':sent}
        remaining={x['client_id']:x for x in phone.evaluate('CWDiary.getQueuedItems()')}
        assert 'owner_id' not in remaining['legacy-diary-owner']
        assert remaining['foreign-diary-owner']['owner_id']==owner+100000
        assert {x[0] for x in sent}==owned_ids,sent
        assert all(x[1]==str(owner) for x in sent),sent
    finally:phone_context.close()
    page.goto(base+'/dashboard')
    print('PASS: diary ownership, offline capture, private upload headers, blocked legacy/foreign records and durable database receipts.')

if __name__=='__main__':main(staff_check=exercise)
