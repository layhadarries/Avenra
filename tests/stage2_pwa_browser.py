"""Stage 2 PWA failure-path tests. Isolated evaluation DB; no SMS sent.
Run: python tests/stage2_pwa_browser.py (requires Playwright Chromium).
"""
from playwright.sync_api import expect
import sqlite3
from contextlib import closing
from stage0_browser import main, wait_for_async

FAST = """(() => {
  const timeout = window.setTimeout.bind(window), interval = window.setInterval.bind(window);
  window.setTimeout = (fn, ms, ...args) => timeout(fn, ms === 1000 ? 80 : ms === 5000 ? 180 : ms, ...args);
  window.setInterval = (fn, ms, ...args) => interval(fn, ms === 5000 ? 150 : ms, ...args);
})();"""


def exercise(page, staff_context, base, env):
    browser = staff_context.browser
    headers = {'X-Device-Token': env.get('DEVICE_TOKEN', 'demo-device')}
    errors = []
    passed = []

    def fresh(script='', offline_shell=False):
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                                      service_workers='allow' if offline_shell else 'block')
        context.add_init_script(FAST + script)
        phone = context.new_page()
        phone.on('pageerror', lambda error: errors.append(str(error)))
        phone.goto(base + '/survivor/')
        phone.evaluate("() => CWQueue.ready")
        if offline_shell:
            wait_for_async(phone,'navigator.serviceWorker.controller !== null')
        return context, phone

    def queued(phone):
        return phone.evaluate('CWQueue.queueSize()')

    def trigger(phone):
        phone.locator('#panic-btn').dispatch_event('pointerdown', {'pointerType': 'touch'})
        expect(phone.locator('#view-countdown')).to_be_visible()

    def alert_count():
        response = staff_context.request.get(base + '/api/alerts?per_page=100')
        assert response.ok, response.text()
        body = response.json()
        return len(body['alerts'])

    def stored(client_id):
        with closing(sqlite3.connect(env['DATABASE_PATH'])) as conn:
            conn.row_factory=sqlite3.Row
            return dict(conn.execute('SELECT * FROM alerts WHERE client_id=?',(client_id,)).fetchone())

    before = alert_count()
    context, phone = fresh()
    phone.locator('#panic-btn').dispatch_event('pointerdown')
    phone.locator('#panic-btn').dispatch_event('pointerup')
    phone.wait_for_timeout(130)
    assert queued(phone) == 0 and alert_count() == before
    trigger(phone)
    phone.locator('#undo-btn').click()
    phone.wait_for_timeout(250)
    assert queued(phone) == 0 and alert_count() == before
    context.close(); passed.append('short hold and Undo create no queued or server alert')

    abort_script = """(() => {
      const put = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function(...args) {
        const req = put.apply(this, args), tx = this.transaction;
        req.addEventListener('success', () => tx.abort()); return req;
      };
    })();"""
    context, phone = fresh(abort_script)
    trigger(phone)
    expect(phone.locator('#view-error')).to_be_visible()
    assert queued(phone) == 0 and alert_count() == before
    expect(phone.locator('#view-queued')).to_be_hidden()
    context.close(); passed.append('aborted storage transaction never claims saved or sends')

    # No actual GPS permission prompt without the explicit checkbox.
    context, phone = fresh("navigator.geolocation.getCurrentPosition = () => { throw Error('unexpected GPS'); };")
    context.set_offline(True)
    trigger(phone)
    expect(phone.locator('#view-queued')).to_be_visible()
    assert queued(phone) == 1 and alert_count() == before
    phone.close()  # browser context retains IndexedDB after the page is closed
    context.set_offline(False)
    phone = context.new_page()
    phone.goto(base + '/survivor/')
    wait_for_async(phone, 'CWQueue.queueSize().then(n => n === 0)')
    wait_for_async(page, "n => fetch('/api/alerts?per_page=100').then(r => r.json()).then(b => b.total === n)", arg=before + 1)
    assert alert_count() == before + 1
    context.close(); passed.append('offline queue survives page close and sends once after reopening')

    context, phone = fresh()
    calls = []
    def lost_response(route):
        if route.request.method != 'POST':
            route.continue_(); return
        calls.append(route.request.post_data_json['client_id'])
        if len(calls) == 1:
            response = route.fetch()
            assert response.status == 201
            route.abort('failed')
        else:
            route.continue_()
    phone.route('**/api/alerts', lost_response)
    trigger(phone)
    expect(phone.locator('#view-queued')).to_be_visible()
    phone.evaluate('CWQueue.flushQueue()')
    expect(phone.locator('#view-sent')).to_be_visible()
    assert len(calls) == 2 and calls[0] == calls[1]
    assert alert_count() == before + 2 and queued(phone) == 0
    # Acknowledge using the real staff cookie and real CSRF token.
    alert_id = staff_context.request.get(base + '/api/alerts?per_page=100').json()['alerts'][0]['id']
    page.goto(base + '/dashboard')
    card = page.get_by_role('article', name=f'Alert {alert_id}', exact=True)
    card.get_by_role('button', name='Acknowledge', exact=True).click()
    expect(phone.locator('#help-status')).to_have_text('Help status: Someone has seen your alert')
    context.close(); passed.append('lost response retries original ID once; dashboard acknowledgement reaches phone')

    # GPS is gathered only for an explicit choice and active consent.
    consent = staff_context.request.post(base + '/api/consents', headers=headers,
        data={'item': 'location_sharing', 'active': True})
    assert consent.ok
    gps = """navigator.geolocation.getCurrentPosition = success => success({
      coords: {latitude: -33.9249, longitude: 18.4241, accuracy: 35.5}, timestamp: Date.UTC(2026,9,23,12,0,0)
    });"""
    context, phone = fresh(gps)
    phone.locator('#share-alert-location').check()
    sent = []
    phone.on('request', lambda req: sent.append(req.post_data_json) if req.method == 'POST' and req.url.endswith('/api/alerts') else None)
    trigger(phone)
    expect(phone.locator('#view-sent')).to_be_visible()
    assert 'sealed_location' in sent[0] and 'lat' not in sent[0]
    assert stored(sent[0]['client_id'])['location_accuracy'] == 35.5
    assert stored(sent[0]['client_id'])['location_recorded_at'] == '2026-10-23T12:00:00Z'
    context.close(); passed.append('consented GPS preserves measured accuracy and fix timestamp')

    staff_context.request.post(base + '/api/consents', headers=headers, data={'item':'location_sharing','active':False})
    context, phone = fresh("navigator.geolocation.getCurrentPosition = () => { throw Error('GPS without consent'); };")
    phone.locator('#share-alert-location').check()
    sent = []
    phone.on('request', lambda req: sent.append(req.post_data_json) if req.method == 'POST' and req.url.endswith('/api/alerts') else None)
    trigger(phone)
    expect(phone.locator('#view-sent')).to_be_visible()
    assert 'sealed_location' not in sent[0]
    assert stored(sent[0]['client_id'])['lat'] is None and stored(sent[0]['client_id'])['location_accuracy'] is None
    context.close(); passed.append('revoked consent avoids GPS collection and still sends alert')

    # Exit during delayed location lookup must not submit or dereference a cleared pending object.
    staff_context.request.post(base + '/api/consents', headers=headers, data={'item':'location_sharing','active':True})
    context, phone = fresh("navigator.geolocation.getCurrentPosition = () => {};" )
    phone.locator('#share-alert-location').check()
    count = alert_count()
    trigger(phone)
    expect(phone.locator('#view-sending')).to_be_visible()
    phone.locator('#quick-exit').click()
    phone.wait_for_url('**/survivor/cover.html')
    phone.wait_for_timeout(250)
    assert alert_count() == count and queued(phone) == 0
    context.close(); passed.append('quick exit during location preparation cancels unsaved alert')

    context, phone = fresh(offline_shell=True)
    context.set_offline(True)
    trigger(phone)
    expect(phone.locator('#view-queued')).to_be_visible()
    phone.locator('#quick-exit').click()
    phone.wait_for_url('**/survivor/cover.html')
    assert queued(phone) == 1
    context.set_offline(False)
    phone.evaluate('CWQueue.flushQueue()')
    wait_for_async(phone, 'CWQueue.queueSize().then(n => n === 0)')
    assert phone.url.endswith('/survivor/cover.html')
    context.close(); passed.append('quick exit preserves committed alert and cover page flushes it')

    context, phone = fresh()
    phone.goto(base + '/survivor/setup.html')
    expect(phone.locator('.contact-row').first).to_be_visible()
    original = phone.locator('.contact-row').count()
    phone.route('**/api/contacts/*', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"unavailable"}'))
    phone.locator('.remove-btn').first.click()
    expect(phone.locator('#form-error')).to_contain_text("Couldn't confirm removal")
    assert phone.locator('.contact-row').count() == original
    phone.route('**/api/contacts', lambda route: route.fulfill(status=401, content_type='application/json', body='{"error":"bad_device_token"}'))
    phone.reload()
    expect(phone.locator('#form-error')).to_contain_text("Couldn't load contacts")
    expect(phone.get_by_text('No trusted contacts yet.', exact=True)).to_have_count(0)
    context.close(); passed.append('contact read/remove failures are visible and do not fake empty/success')

    context, phone = fresh("indexedDB.open = () => { throw new Error('storage disabled'); };")
    count = alert_count()
    trigger(phone)
    expect(phone.locator('#view-error')).to_be_visible()
    assert alert_count() == count
    context.close(); passed.append('unavailable storage shows failure instead of saved')

    context, phone = fresh()
    phone.route('**/api/alerts', lambda route: route.fulfill(status=401, content_type='application/json', body='{"error":"bad_device_token"}'))
    trigger(phone)
    expect(phone.locator('#queue-message')).to_contain_text('service could not accept it')
    assert queued(phone) == 1
    context.close(); passed.append('authentication rejection keeps queue and never claims server receipt')

    context, phone = fresh()
    phone.route('**/api/alerts', lambda route: route.fulfill(status=200, content_type='application/json', body='{"id": 1, "client_id": "wrong-alert"}'))
    trigger(phone)
    expect(phone.locator('#view-queued')).to_be_visible()
    assert queued(phone) == 1
    expect(phone.locator('#view-sent')).to_be_hidden()
    context.close(); passed.append('mismatched receipt cannot delete a queued alert')

    context, phone = fresh("navigator.geolocation.getCurrentPosition = (ok, fail) => fail({code:1});")
    phone.locator('#share-alert-location').check()
    sent = []
    phone.on('request', lambda req: sent.append(req.post_data_json) if req.method == 'POST' and req.url.endswith('/api/alerts') else None)
    trigger(phone)
    expect(phone.locator('#view-sent')).to_be_visible()
    assert 'sealed_location' not in sent[0]
    assert stored(sent[0]['client_id'])['lat'] is None and stored(sent[0]['client_id'])['location_recorded_at'] is None
    context.close(); passed.append('denied GPS still permits an alert without location metadata')

    # Server consent is checked again when an old queued payload is flushed.
    context, phone = fresh()
    context.set_offline(True)
    phone.evaluate("CWQueue.queueAlert({client_id:'queued-consent-revocation',lat:-33.9,lng:18.4,location_accuracy:35.5,location_recorded_at:'2026-10-23T12:00:00Z'})")
    staff_context.request.post(base + '/api/consents', headers=headers, data={'item':'location_sharing','active':False})
    sent = []
    phone.on('request', lambda req: sent.append(req.post_data_json) if req.method == 'POST' and req.url.endswith('/api/alerts') else None)
    context.set_offline(False)
    phone.evaluate('CWQueue.flushQueue()')
    wait_for_async(phone, 'CWQueue.queueSize().then(n => n === 0)')
    assert sent and 'sealed_location' not in sent[0] and sent[0]['suppress_location'] is True
    assert stored(sent[0]['client_id'])['lat'] is None and stored(sent[0]['client_id'])['location_recorded_at'] is None
    context.close(); passed.append('revoked consent strips GPS from an older queued alert before transmission')

    # Exercise the actual contact form as well as backend API validation.
    response = staff_context.request.post(base + '/api/contacts', headers=headers, data={'contacts':[]})
    assert response.ok
    context, phone = fresh()
    phone.goto(base + '/survivor/setup.html')
    def add(name, number):
        phone.locator('#c-name').fill(name)
        phone.locator('#c-phone').fill(number)
        phone.get_by_role('button', name='Add contact', exact=True).click()
    add('Contact One', '082 123 4567')
    expect(phone.locator('.contact-row')).to_have_count(1)
    expect(phone.locator('.phone')).to_have_text('••••4567')
    add('Contact One', '0831234567')
    expect(phone.locator('#form-error')).to_be_visible()
    assert phone.locator('.contact-row').count() == 1
    add('Bad Number', '123')
    expect(phone.locator('#form-error')).to_be_visible()
    assert phone.locator('.contact-row').count() == 1
    for i in range(2,6):
        add('Contact ' + str(i), '+2782123456' + str(i))
        expect(phone.locator('.contact-row')).to_have_count(i)
    add('Sixth', '0831234567')
    expect(phone.locator('#form-error')).to_contain_text('up to 5')
    expect(phone.locator('.contact-row')).to_have_count(5)
    phone.locator('.remove-btn').first.click()
    expect(phone.locator('.contact-row')).to_have_count(4)
    phone.reload()
    expect(phone.locator('.contact-row')).to_have_count(4)
    context.close(); passed.append('contact form masks, persists, rejects invalid/duplicate/sixth entries, and removes')

    assert not errors, errors
    for item in passed: print('PASS:', item)


if __name__ == '__main__':
    main(staff_check=exercise)
