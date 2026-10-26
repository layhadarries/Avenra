"""Isolated Quick Exit restoration checks; lifecycle injection is not an OS test."""
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async
from stage9_vault_browser import unlock
from weather_onboarding_browser import secret, enter_pin


def exercise(page, staff, base, env):
    # Playwright normally disables BFCache. Permit it here; Chromium can still
    # decline restoration for a particular document, so record actual observation
    # separately from the explicit lifecycle-event checks below.
    restoration_browser = staff.browser.browser_type.launch(ignore_default_args=['--disable-back-forward-cache'])
    phone = restoration_browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
    phone.route('https://**', lambda route: route.abort())
    try:
        p = phone.new_page()
        p.goto(base+'/survivor/')
        p.evaluate("document.querySelector('#help-status').textContent='Fictional private responder status'; window.dispatchEvent(new Event('pagehide'))")
        assert p.locator('#help-status').inner_text() == '', 'Page hide must remove rendered alert status'
        p.goto(base+'/survivor/diary.html'); unlock(p)
        wait_for_async(p, 'navigator.serviceWorker.controller !== null')
        phone.set_offline(True)
        p.locator('#diary-note').fill('Fictional exit queue preservation')
        p.locator('#diary-save-btn').click()
        expect(p.locator('#diary-entries-list')).to_contain_text('Saved on phone')
        queued = p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').getAll();q.onsuccess=()=>resolve(q.result);};})""")
        p.locator('#quick-exit-btn').click(); p.wait_for_url('**/cover.html')
        p.goto(base+'/survivor/diary.html')
        expect(p.locator('#diary-private')).to_be_hidden()
        restored = p.evaluate("""()=>new Promise(resolve=>{const r=indexedDB.open('clear-sky-diary-queue',1);r.onsuccess=()=>{const q=r.result.transaction('diary_entries').objectStore('diary_entries').getAll();q.onsuccess=()=>resolve(q.result);};})""")
        assert restored == queued, 'Exit must preserve exact encrypted queue records'
        p.reload(); expect(p.locator('#diary-private')).to_be_hidden()
        p.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        expect(p.locator('#diary-private')).to_be_hidden()
        phone.set_offline(False)
        # Privacy data has no vault screen: after exit, reopening it must use the
        # disguised entry rather than refetch and redisplay private history.
        p.goto(base+'/survivor/privacy.html'); p.wait_for_url('**/cover.html')
        p.reload(); assert p.url.endswith('/cover.html')
        reopened = phone.new_page()
        reopened.goto(base+'/survivor/privacy.html'); reopened.wait_for_url('**/cover.html')
        # Start a separate browser profile to test actual history traversal.
        fresh = restoration_browser.new_context()
        fresh.add_init_script("""addEventListener('pageshow', event => {
          if (event.persisted && location.pathname === '/survivor/privacy.html')
            sessionStorage.setItem('fixture-privacy-bfcache-observed','1');
        });""")
        fresh.route('https://**', lambda route: route.abort())
        try:
            assert staff.request.get(base+'/cases/SP-1042').ok  # Fictional viewing-history event.
            q = fresh.new_page(); q.goto(base+'/survivor/cover.html')
            q.goto(base+'/survivor/privacy.html')
            expect(q.locator('#consent-location_sharing')).to_be_enabled()
            expect(q.locator('#access-list')).to_contain_text('Nomsa D')
            # Leave the protected page in history, then exit from a later page.
            # Exiting directly from privacy would replace that history entry and
            # would not exercise restoration of the earlier protected document.
            q.goto(base+'/survivor/help.html')
            q.get_by_role('button', name='Quick exit', exact=True).click(); q.wait_for_url('**/cover.html')
            q.go_back(); q.wait_for_url('**/cover.html')
            q.go_forward(); q.wait_for_url('**/cover.html')
            observed = q.evaluate("sessionStorage.getItem('fixture-privacy-bfcache-observed') === '1'")
            print('BFCache: actual protected-page restoration observed:', observed,
                  '(explicit persisted-pageshow injection also tested; not OS tab/snapshot proof).')
            q.goto(base+'/survivor/privacy.html'); q.wait_for_url('**/cover.html')
            q.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
            assert q.url.endswith('/cover.html')
            q.evaluate("CWUnlock.setPin('2468')")
            secret(q, base); enter_pin(q, '2468'); q.wait_for_url('**/survivor/')
            q.goto(base+'/survivor/privacy.html')
            expect(q.locator('#consent-location_sharing')).to_be_enabled()
            # Exercise the protected document's persisted-pageshow handlers even
            # when this Chromium run chooses a network load rather than BFCache.
            q.evaluate("localStorage.setItem('clear-sky-exited-v1','1'); window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
            q.wait_for_url('**/cover.html')
        finally:
            fresh.close()
        print('PASS: rendered alert clearing, locked diary reload/pageshow, exact encrypted queue preservation, privacy reopening/new tab and Back/Forward exit boundary.')
    finally:
        phone.close()
        restoration_browser.close()


if __name__ == '__main__': main(exercise)
