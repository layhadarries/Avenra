"""Local fictional vault acceptance; injected lifecycle events are not device tests."""
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async

PHRASE='Cedar! private river vault 826'


def unlock(page):
    # Initialization decides whether confirmation is needed before enabling submit.
    expect(page.locator('#vault-submit')).to_be_enabled()
    page.locator('#vault-passphrase').fill(PHRASE)
    if page.locator('#vault-confirmation').is_visible(): page.locator('#vault-confirmation').fill(PHRASE)
    page.locator('#vault-submit').click()
    expect(page.locator('#diary-private')).to_be_visible()


def exercise(page, staff, base, env):
    phone=staff.browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    try:
        p=phone.new_page(); errors=[]; p.on('pageerror',lambda error:errors.append(str(error)))
        p.goto(base+'/survivor/diary.html')
        assert p.locator('#diary-private').count()==1, 'Diary must have a locked vault boundary before rendering evidence'
        expect(p.locator('#diary-private')).to_be_hidden()
        expect(p.locator('#vault-submit')).to_be_enabled()
        assert phone.request.get(base+'/api/diary',headers={'X-Device-Token':'demo-device'}).status==423
        unlock(p)
        # A copied paired browser-cookie jar must not include a reusable evidence
        # factor. Private fetches use a grant held only in the unlocked page's RAM.
        assert phone.request.get(base+'/api/diary',headers={'X-Device-Token':'demo-device'}).status==423
        assert p.evaluate("""()=>{
          const token=CWVaultUI.headers()['X-Vault-Unlock'];
          return typeof token==='string' && token.length===43 &&
            !JSON.stringify(localStorage).includes(token) && !JSON.stringify(sessionStorage).includes(token) &&
            !document.cookie.includes(token);
        }""")
        wait_for_async(p,'navigator.serviceWorker.controller !== null')
        phone.set_offline(True)
        p.locator('#diary-note').fill('Fictional encrypted offline note')
        p.locator('#diary-save-btn').click()
        expect(p.locator('#diary-entries-list')).to_contain_text('Saved on phone')
        raw=p.evaluate("""() => new Promise((resolve,reject)=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(Error('read'));};})""")
        assert len(raw)==1 and raw[0]['vault_version']==1 and 'note' not in raw[0] and 'photo_blob' not in raw[0]
        assert 'Fictional encrypted offline note' not in str(raw)
        p.reload(); expect(p.locator('#diary-private')).to_be_hidden()
        unlock(p)
        expect(p.locator('#diary-entries-list')).to_contain_text('Fictional encrypted offline note')
        p.locator('#quick-exit-btn').click(); p.wait_for_url('**/cover.html')
        p.goto(base+'/survivor/diary.html'); expect(p.locator('#diary-private')).to_be_hidden()
        assert not p.locator('#diary-note').input_value()
        unlock(p)
        assert len(p.evaluate('CWDiary.getQueuedItems()'))==1
        p.evaluate("window.dispatchEvent(new Event('pagehide')); window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        expect(p.locator('#diary-private')).to_be_hidden()
        assert p.evaluate("CWVaultUI.headers()['X-Vault-Unlock'] === undefined")
        assert 'Fictional encrypted offline note' not in p.locator('#diary-entries-list').inner_text()
        phone.set_offline(False); unlock(p)
        wait_for_async(p,'async()=> (await CWDiary.getQueuedItems()).length === 0')
        phone.set_offline(True)
        p.evaluate("""async()=>{
          const owner=await CWQueue.captureOwner();
          const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>resolve(r.result);r.onerror=reject;});
          await new Promise((resolve,reject)=>{const t=db.transaction('diary_entries','readwrite');
            const store=t.objectStore('diary_entries');
            store.put({client_id:'legacy-migration-fictional',owner_id:owner,note:'Fictional legacy note',status:'queued'});
            store.put({client_id:'foreign-migration-fictional',owner_id:owner+1000,note:'Fictional foreign private note',status:'queued'});
            store.put({client_id:'unbound-migration-fictional',note:'Fictional unbound private note',status:'queued'});
            t.oncomplete=resolve;t.onabort=t.onerror=reject;});db.close();CWVault.lock();
          window.originalVaultPut=IDBObjectStore.prototype.put;
          IDBObjectStore.prototype.put=function(value){if(value.client_id==='legacy-migration-fictional'&&value.vault_version===1){this.transaction.abort();throw new DOMException('Synthetic quota failure','QuotaExceededError');}return originalVaultPut.apply(this,arguments);};
        }""")
        p.locator('#vault-passphrase').fill(PHRASE); p.locator('#vault-submit').click()
        expect(p.locator('#vault-status')).to_contain_text('Existing records are retained')
        retained=p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').get('legacy-migration-fictional');q.onsuccess=()=>resolve(q.result);};})""")
        assert retained['note']=='Fictional legacy note' and 'vault_version' not in retained
        p.evaluate('() => { IDBObjectStore.prototype.put=originalVaultPut; }')
        unlock(p)
        migrated=p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').get('legacy-migration-fictional');q.onsuccess=()=>resolve(q.result);};})""")
        assert migrated['vault_version']==1 and 'note' not in migrated
        entries=p.evaluate('CWDiary.getQueuedItems()')
        assert len(entries)==3
        assert next(row for row in entries if row['client_id']=='legacy-migration-fictional')['note']=='Fictional legacy note'
        blocked=p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').getAll();q.onsuccess=()=>resolve(q.result);};})""")
        for row in blocked:
            if row['client_id']!='legacy-migration-fictional':
                assert row.get('legacy_public')==1 and 'note' not in row, 'Blocked records must be encrypted without adoption or deletion'
        assert 'owner_id' not in next(row for row in blocked if row['client_id']=='unbound-migration-fictional')
        p.evaluate("""async()=>{
          const owner=await CWQueue.captureOwner(), note='Fictional public-envelope recovery';
          const sealed=await CWVault.sealLegacy({client_id:'owned-public-migration',owner_id:owner,note,
            contract_version:1,file_hash:await CWDiary.computeNoteSha256(note),shared:false,has_photo:false,status:'queued'},CWQueue.publicSealingKey());
          const db=await new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>resolve(r.result);});
          await new Promise((resolve,reject)=>{const t=db.transaction('diary_entries','readwrite');t.objectStore('diary_entries').put(sealed);t.oncomplete=resolve;t.onabort=t.onerror=reject;});db.close();CWVault.lock();
        }""")
        p.route('**/api/diary',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"synthetic"}') if route.request.method=='POST' else route.continue_())
        phone.set_offline(False); unlock(p)
        expect(p.locator('#diary-entries-list')).to_contain_text('Fictional public-envelope recovery')
        recovered=p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').get('owned-public-migration');q.onsuccess=()=>resolve(q.result);};})""")
        assert recovered['vault_version']==1 and 'note' not in recovered and 'legacy_public' not in recovered
        assert not errors, errors
        print('PASS: private API lock, strong vault setup, encrypted offline note, reload/unlock, exit/lifecycle clearing, queue retention and upload receipt.')
        print('PASS: failed additive migration retains original legacy bytes; retry encrypts without changing the client ID or plaintext payload.')
    finally:
        phone.close()


if __name__=='__main__': main(exercise)
