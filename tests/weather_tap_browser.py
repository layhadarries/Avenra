"""Experimental tap gesture: browser touch events, actual pairing and queue.

Android user-agent/mobile/touch emulation is NOT physical Android-device testing.
All accounts/data are fictional; external providers are blocked; no messages sent.
"""
import json
import os
import sqlite3
import time

from playwright.sync_api import expect
from stage0_browser import main, wait_for_async

PREF = 'clear-sky-weather-tap-v1'
STATUS = 'clear-sky-weather-tap-status-v1'


def exercise(page, staff, base, env):
    browser = staff.browser
    engine = browser.browser_type.name
    errors, passed = [], []

    def count(owner=None):
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            return conn.execute('SELECT COUNT(*) FROM alerts' + (' WHERE user_id=?' if owner else ''), (owner,) if owner else ()).fetchone()[0]

    def until(phone, predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            assert time.monotonic() < deadline, 'Timed out waiting for fixture condition'
            phone.wait_for_timeout(50)

    def new_phone(pair=True, offline_shell=False, extra_script=''):
        ctx = browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,
            user_agent=('Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1' if engine == 'webkit' else
                'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/' + browser.version + ' Mobile Safari/537.36'),
            service_workers='allow' if offline_shell else 'block')
        ctx.route('https://api.open-meteo.com/**',lambda route:route.abort())
        ctx.route('https://api.bigdatacloud.net/**',lambda route:route.abort())
        ctx.route('https://geocoding-api.open-meteo.com/**',lambda route:route.abort())
        ctx.add_init_script("navigator.geolocation.getCurrentPosition = (_,fail) => { if(fail) fail({code:1}); };" + extra_script)
        phone = ctx.new_page()
        phone.on('pageerror',lambda error:errors.append(str(error)))
        owner = None
        if pair:
            page.goto(base + '/devices')
            page.get_by_role('button',name='Create private pairing link',exact=True).click()
            link = page.locator('#device-invite-link')
            expect(link).to_be_visible()
            phone.goto(link.get_attribute('href'))
            phone.get_by_role('button',name='Connect my device',exact=True).click()
            expect(phone.locator('#status')).to_contain_text('Device connected')
            owner = ctx.request.get(base + '/api/device').json()['account_id']
        return ctx, phone, owner

    def enable(phone):
        phone.goto(base + '/survivor/tap-setup.html')
        expect(phone.locator('#tap-understood')).to_be_enabled()
        expect(phone.locator('#tap-enable')).to_be_disabled()
        phone.locator('#tap-understood').check()
        phone.locator('#tap-enable').click()
        expect(phone.locator('#tap-setup-status')).to_contain_text('are ON')

    def cover(phone, armed=True):
        phone.goto(base + '/survivor/cover.html')
        phone.bring_to_front()
        phone.evaluate('() => CWQueue.ready')
        if armed:
            phone.wait_for_function("document.body.classList.contains('weather-tap-enabled') && document.hasFocus()")

    def taps(phone, number=4):
        for _ in range(number):
            phone.locator('#cv-place').tap()

    def reset(phone):
        phone.evaluate("location.hash = 'fixture-' + Math.random().toString(16).slice(2)")
        phone.wait_for_timeout(30)

    def unchanged(phone, expected):
        phone.wait_for_timeout(400)
        assert count() == expected

    ctx, phone, owner = new_phone()
    try:
        before = count()
        cover(phone,False)
        taps(phone)
        unchanged(phone,before)
        assert phone.evaluate('CWQueue.queueSize()') == 0
        phone.goto(base + '/survivor/tap-setup.html')
        expect(phone.locator('#tap-understood')).to_be_enabled()
        expect(phone.locator('#tap-enable')).to_be_disabled()
        for _ in range(4): phone.locator('h1').tap()
        unchanged(phone,before)
        assert phone.evaluate(f"localStorage.getItem('{PREF}')") is None
        enable(phone)
        cover(phone)
        taps(phone,3); unchanged(phone,before)
        phone.wait_for_timeout(1600); taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,2); phone.wait_for_timeout(1600); taps(phone,2); unchanged(phone,before); reset(phone)
        passed.append('disabled by default, explicit paired opt-in, three taps and out-of-window taps create no alert')

        # Interactive controls and open dialogs never contribute taps.
        for _ in range(4): phone.locator('#cv-refresh').tap()
        unchanged(phone,before)
        phone.evaluate("""() => {
            const fixture=document.createElement('form'); fixture.id='fixture-form';
            fixture.innerHTML='<label>Name<input aria-label="Fixture name"></label><button type="button">Fixture button</button><a href="#fixture-link">Fixture link</a>';
            document.querySelector('.cv-main').prepend(fixture);
        }""")
        for selector in ('#fixture-form label','#fixture-form button','#fixture-form a'):
            for _ in range(4): phone.locator(selector).tap()
        phone.get_by_label('Fixture name').fill('1234')
        unchanged(phone,before)
        phone.evaluate("document.getElementById('fixture-form').remove()")
        phone.locator('#cv-loc-btn').tap()
        for _ in range(4): phone.locator('#cv-search-title').tap()
        phone.locator('#cv-search-input').fill('1234')
        unchanged(phone,before)
        phone.locator('#cv-search-close').tap()
        phone.locator('[data-thursday="1"]').tap()
        expect(phone.locator('#cv-modal')).to_be_visible()
        for _ in range(4): phone.locator('#cv-sheet-title').tap()
        for _ in range(4): phone.locator('#ob-pin-pad').get_by_role('button',name='1',exact=True).tap()
        unchanged(phone,before)
        phone.locator('#cv-modal-close').tap()
        # Existing temperature hold still opens setup instead of sending an alert.
        phone.locator('#cv-temp').scroll_into_view_if_needed()
        box = phone.locator('#cv-temp').bounding_box()
        phone.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        phone.mouse.down(); phone.wait_for_timeout(1600); phone.mouse.up()
        expect(phone.locator('#cv-modal')).to_be_visible()
        phone.locator('#cv-modal-close').tap()
        unchanged(phone,before)
        passed.append('buttons, links, inputs, forms, real search/PIN/setup dialogs excluded; Thursday and temperature hold preserved')

        phone.evaluate('window.scrollTo(0,0)'); phone.wait_for_timeout(50)
        taps(phone,3)
        phone.evaluate('window.scrollTo(0,300)'); phone.wait_for_timeout(60)
        taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,3)
        if engine == 'chromium':
            cdp = ctx.new_cdp_session(phone)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':55,'y':190}]})
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':80,'y':190}]})
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':55,'y':190}]})
            cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            # WebKit has no CDP touch-drag interface: use trusted mouse pointer
            # movement here; touchscreen drag thresholds also have pure unit tests.
            phone.mouse.move(55,190); phone.mouse.down(); phone.mouse.move(80,190); phone.mouse.move(55,190); phone.mouse.up()
        taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,3); reset(phone); taps(phone,1); unchanged(phone,before); reset(phone)
        # Headless Chromium keeps all pages visible/focused. Exercise lifecycle
        # handlers and the guards explicitly; do not claim physical background testing.
        taps(phone,3)
        phone.evaluate("window.dispatchEvent(new Event('blur'))")
        taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,3)
        phone.evaluate("document.hasFocus = () => false; window.dispatchEvent(new Event('blur'))")
        taps(phone); unchanged(phone,before)
        phone.evaluate("delete document.hasFocus; window.dispatchEvent(new Event('focus'))")
        taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,3)
        phone.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}); Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange'))")
        taps(phone); unchanged(phone,before)
        phone.evaluate("delete document.hidden; delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange'))")
        phone.wait_for_function("document.body.classList.contains('weather-tap-enabled')")
        taps(phone,1); unchanged(phone,before); reset(phone)
        taps(phone,3); phone.goto(base + '/survivor/install.html'); cover(phone)
        taps(phone,1); unchanged(phone,before); reset(phone)
        # Programmatic pointer events must not activate the real gesture.
        phone.locator('#cv-place').evaluate("el => { for(let i=0;i<4;i++){el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1,button:0}));el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1,button:0}));} }")
        unchanged(phone,before)
        passed.append('scrolling, drag-return, hash/page navigation, simulated focus/visibility loss and foreground guards, and synthetic events do not trigger')

        phone.evaluate('() => { navigator.geolocation.getCurrentPosition = () => { throw Error("gesture must not request GPS"); }; }')
        consent = ctx.request.post(base + '/api/consents',headers={'Origin':base},data={'item':'location_sharing','active':True})
        assert consent.ok
        sent = []
        phone.on('request',lambda request:sent.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/api/alerts') else None)
        taps(phone,8)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Received by Avenra')
        assert count() == before+1 and len(sent) == 1
        assert 'sealed_alert' in sent[0] and 'sealed_location' not in sent[0]
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            assert conn.execute('SELECT lat,lng FROM alerts WHERE client_id=?',(sent[0]['client_id'],)).fetchone() == (None,None)
        assert phone.url.split('#')[0].endswith('/survivor/cover.html')
        alert_id = phone.evaluate(f"JSON.parse(localStorage.getItem('{STATUS}')).alert_id")
        page.goto(base + '/dashboard')
        csrf = page.locator('meta[name="csrf-token"]').get_attribute('content')
        response = staff.request.post(base + f'/api/alerts/{alert_id}/acknowledge',headers={'X-CSRFToken':csrf},data={})
        assert response.status == 200
        phone.bring_to_front()
        expect(phone.locator('#weather-tap-status')).to_contain_text('Acknowledged by a responder',timeout=15000)
        assert 'help is not guaranteed' in phone.locator('#weather-tap-status').inner_text()
        passed.append('eight quick trusted taps create exactly one GPS-free alert; real receipt and real responder acknowledgement are distinct')

        # Opting out in another tab takes effect without deleting existing alerts.
        settings = ctx.new_page(); settings.goto(base + '/survivor/tap-setup.html')
        settings.locator('#tap-disable').click()
        phone.bring_to_front()
        phone.wait_for_function("!document.body.classList.contains('weather-tap-enabled')")
        taps(phone); unchanged(phone,before+1)
        # Disabling must win over an in-flight enable verification.
        expect(settings.locator('#tap-understood')).to_be_enabled()
        held = []
        settings.route('**/api/device',lambda route:held.append(route))
        settings.locator('#tap-understood').check()
        settings.locator('#tap-enable').click()
        until(phone,lambda:bool(held))
        settings.locator('#tap-disable').click()
        held[0].continue_()
        settings.wait_for_timeout(250)
        assert settings.evaluate(f"localStorage.getItem('{PREF}')") is None
        expect(settings.locator('#tap-setup-status')).to_contain_text('are OFF')
        settings.close()
        passed.append('opt-out applies across tabs and cannot be undone by an earlier in-flight enable request')
    finally:
        ctx.close()

    gps, phone, gps_owner = new_phone(extra_script="navigator.geolocation.getCurrentPosition = ok => { window.finishGPS = () => ok({coords:{latitude:-33.9249,longitude:18.4241,accuracy:22},timestamp:Date.now()}); };")
    try:
        assert gps.request.post(base + '/api/consents',headers={'Origin':base},data={'item':'location_sharing','active':True}).ok
        phone.goto(base + '/survivor/tap-setup.html')
        expect(phone.locator('#tap-understood')).to_be_enabled()
        phone.locator('#tap-understood').check(); phone.locator('#tap-location').check()
        phone.locator('#tap-enable').click()
        expect(phone.locator('#tap-setup-status')).to_contain_text('are ON')
        cover(phone); taps(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Received by Avenra')
        phone.wait_for_function("typeof finishGPS === 'function'")
        client_id = phone.evaluate(f"JSON.parse(localStorage.getItem('{STATUS}')).client_id")
        def row():
            with sqlite3.connect(env['DATABASE_PATH']) as conn:
                return conn.execute('SELECT id,lat,lng,location_accuracy,location_recorded_at FROM alerts WHERE client_id=?',(client_id,)).fetchone()
        original = row(); assert original[1] is None
        before = count(gps_owner)
        phone.evaluate('finishGPS()')
        until(phone,lambda:row()[1] is not None)
        updated = row()
        assert updated[0] == original[0] and updated[1:4] == (-33.9249,18.4241,22.0) and updated[4]
        assert count(gps_owner) == before
        # A subsequent gesture may use that recent genuine fix immediately.
        phone.wait_for_timeout(1600); taps(phone)
        until(phone,lambda:count(gps_owner)==before+1)
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            assert conn.execute('SELECT lat FROM alerts WHERE user_id=? ORDER BY id DESC LIMIT 1',(gps_owner,)).fetchone()[0] == -33.9249
        # Reload removes all in-memory fixes. Withdrawal and regrant must defeat
        # a pending callback, even though both happen in the same second.
        cover(phone); phone.wait_for_timeout(1600); taps(phone)
        phone.wait_for_function("typeof finishGPS === 'function'")
        until(phone,lambda:count(gps_owner)==before+2)
        client_id = phone.evaluate(f"JSON.parse(localStorage.getItem('{STATUS}')).client_id")
        for active in (False,True):
            assert gps.request.post(base+'/api/consents',headers={'Origin':base},data={'item':'location_sharing','active':active}).ok
        phone.evaluate('finishGPS()'); phone.wait_for_timeout(500)
        assert row()[1] is None
        passed.append('GPS-free durable receipt precedes delayed authorised real-fix update; same alert ID, recent fix reuse, and withdrawal/regrant defeats delayed callback')
    finally:
        gps.close()

    offline, phone, first_owner = new_phone(offline_shell=True)
    try:
        enable(phone); cover(phone)
        phone.wait_for_function('navigator.serviceWorker.controller !== null')
        before = count()
        offline.set_offline(True)
        taps(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Saved on this phone')
        assert phone.evaluate('CWQueue.queueSize()') == 1 and count() == before
        client_id = phone.evaluate(f"JSON.parse(localStorage.getItem('{STATUS}')).client_id")
        phone.close(); phone = offline.new_page(); phone.on('pageerror',lambda error:errors.append(str(error)))
        cover(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Saved on this phone')
        posts = []
        def lost_receipt(route):
            if route.request.method != 'POST': route.continue_(); return
            posts.append(route.request.post_data_json['client_id'])
            if len(posts) == 1:
                response = route.fetch(); assert response.status == 201; route.abort('failed')
            else: route.continue_()
        offline.route('**/api/alerts',lost_receipt)
        offline.set_offline(False)
        until(phone,lambda:len(posts)>=1)
        phone.evaluate('CWQueue.flushQueue()')
        expect(phone.locator('#weather-tap-status')).to_contain_text('Received by Avenra',timeout=15000)
        assert len(posts) >= 2 and all(value == client_id for value in posts)
        assert count(first_owner) == 1 and phone.evaluate('CWQueue.queueSize()') == 0
        passed.append('offline queue survives page close; lost server receipt retries the same client ID without duplicate alerts')

        # A pending record must never be adopted by a different paired account.
        offline.set_offline(True); phone.wait_for_timeout(1600); taps(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Saved on this phone')
        foreign, foreign_page, second_owner = new_phone()
        try:
            assert first_owner != second_owner
            cookie = next(value for value in foreign.cookies() if value['name']=='avenra_device')
            offline.add_cookies([cookie])
            phone.close(); phone = offline.new_page(); cover(phone)
            count_before = count()
            offline.set_offline(False)
            phone.wait_for_function("!document.body.classList.contains('weather-tap-enabled')")
            phone.evaluate('CWQueue.flushQueue()')
            assert phone.evaluate('CWQueue.queueSize()') == 1
            assert count() == count_before and count(second_owner) == 0
            passed.append('account switching disables opt-in and retains, rather than reassigns, the old account’s pending alert')
        finally: foreign.close()
    finally:
        offline.close()

    anonymous, phone, _ = new_phone(pair=False)
    try:
        phone.goto(base + '/survivor/tap-setup.html')
        expect(phone.locator('#tap-setup-status')).to_contain_text('unavailable')
        expect(phone.locator('#tap-understood')).to_be_disabled()
        expect(phone.locator('#tap-enable')).to_be_disabled()
        phone.evaluate(f"localStorage.setItem('{PREF}',JSON.stringify({{version:1,setup_version:1,enabled:true,owner_id:1}}))")
        before = count(); cover(phone,False)
        phone.wait_for_function(f"localStorage.getItem('{PREF}') === null")
        taps(phone); unchanged(phone,before)
        passed.append('unpaired browser cannot opt in, including in the local demo environment')
    finally: anonymous.close()

    abort = """(() => { const put=IDBObjectStore.prototype.put; window.restorePut=()=>{IDBObjectStore.prototype.put=put;};
        IDBObjectStore.prototype.put=function(...args){const request=put.apply(this,args),tx=this.transaction;request.addEventListener('success',()=>tx.abort());return request;}; })();"""
    broken, phone, _ = new_phone(extra_script=abort)
    try:
        enable(phone); cover(phone); before = count()
        phone.evaluate("() => { const original=CWQueue.queueAlert; window.fixtureIds=[]; CWQueue.queueAlert=item=>{fixtureIds.push(item.client_id);return original(item);}; }")
        taps(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Could not confirm saving')
        assert count() == before and phone.evaluate('CWQueue.queueSize()') == 0
        phone.evaluate('restorePut()'); phone.wait_for_timeout(1600); taps(phone)
        expect(phone.locator('#weather-tap-status')).to_contain_text('Received by Avenra')
        ids = phone.evaluate('fixtureIds')
        assert len(ids)==2 and ids[0]==ids[1] and count()==before+1
        passed.append('aborted storage never claims saved; retry uses the original client ID')
    finally: broken.close()
    assert not errors, errors
    page.goto(base + '/dashboard')
    for result in passed: print('PASS:',result)
    print('BROWSER:',engine,browser.version,'with',('iPhone' if engine=='webkit' else 'Android'),'user-agent/mobile/touch emulation. No physical phone tested.')


if __name__ == '__main__':
    main(staff_check=exercise,browser_name=os.environ.get('AVENRA_TEST_BROWSER','chromium'))
