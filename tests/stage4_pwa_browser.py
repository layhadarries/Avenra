"""Combined Stage 2/3/4 contracts; temporary data, no notification sends."""
import base64
import io
import sqlite3

from PIL import Image
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async
from stage2_pwa_browser import FAST


def exercise(page, staff, base, env):
    headers = {'X-Device-Token': env.get('DEVICE_TOKEN', 'demo-device')}
    browser = staff.browser
    errors = []

    def phone(script='', workers='block'):
        context = browser.new_context(viewport={'width': 390, 'height': 844},
                                      is_mobile=True, has_touch=True, service_workers=workers)
        context.add_init_script(FAST + script)
        tab = context.new_page()
        tab.on('pageerror', lambda error: errors.append(str(error)))
        return context, tab

    def consent(key, value):
        result = staff.request.post(base + '/api/consents', headers=headers,
                                    data={'item': key, 'active': value})
        assert result.ok, result.text()

    # Existing alerts reach both the staff portal and the privacy-controlled phone.
    consent('location_sharing', True)
    alert = staff.request.post(base + '/api/alerts', headers=headers, data={
        'client_id': 'stage4-shared-location', 'lat': -33.9249, 'lng': 18.4241,
        'location_accuracy': 35.5, 'location_recorded_at': '2026-10-24T12:00:00Z',
    }).json()
    page.goto(base + '/dashboard')
    card = page.get_by_role('article', name=f"Alert {alert['id']}", exact=True)
    expect(card).to_contain_text('Reported location:')
    context, tab = phone()
    tab.goto(base + '/survivor/privacy.html')
    location = tab.locator('#consent-location_sharing')
    expect(location).to_be_enabled()
    location.uncheck(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    expect(card).to_contain_text('Location unavailable or not shared.', timeout=10000)
    location.check(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    expect(card).to_contain_text('Reported location:', timeout=10000)
    tab.reload()
    expect(location).to_be_checked()
    print('PASS: PWA consent changes persist and redact/restore the open staff dashboard.')

    # Successful diary/photo access is visible; consent revocation blocks subsequent reads.
    consent('diary_sharing', True)
    image = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(image, format='JPEG')
    receipt = staff.request.post(base + '/api/diary', headers=headers, data={
        'client_id': 'stage4-shared-diary', 'shared': True, 'note': 'PRIVATE-STAGE4-NOTE',
        'photo_data': 'data:image/jpeg;base64,' + base64.b64encode(image.getvalue()).decode(),
    })
    assert receipt.status == 201, receipt.text()
    entry_id = receipt.json()['id']
    assert staff.request.get(base + '/api/diary?case_code=' + alert['case_code']).ok
    assert staff.request.get(base + f'/cases/diary-photo/{entry_id}').status == 200
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(tab.locator('#access-list')).to_contain_text('Viewed a shared photo')
    assert 'PRIVATE-STAGE4-NOTE' not in tab.locator('#access-list').inner_text()
    diary = tab.locator('#consent-diary_sharing')
    diary.uncheck(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    assert staff.request.get(base + f'/cases/diary-photo/{entry_id}').status == 403
    assert staff.request.get(base + '/api/diary?case_code=' + alert['case_code']).json()['entries'] == []
    diary.check(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    print('PASS: actual diary/photo views reach safe history; PWA withdrawal blocks disclosure.')

    consent('shelter_referral_sharing', True)
    csrf = page.locator('meta[name="csrf-token"]').get_attribute('content')
    shelter_id = staff.request.get(base + '/api/shelters').json()['shelters'][0]['id']
    payload = {'alert_id': alert['id'], 'shelter_id': shelter_id}
    created = staff.request.post(base + '/api/referrals', headers={'X-CSRFToken': csrf}, data=payload)
    assert created.status == 201, created.text()
    referral_id = created.json()['referral']['id']
    tab.get_by_role('button', name='Refresh privacy settings').click()
    referral_toggle = tab.locator('#consent-shelter_referral_sharing')
    expect(referral_toggle).to_be_enabled()
    referral_toggle.uncheck(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    assert not any(row['id'] == referral_id for row in staff.request.get(base + '/api/referrals').json()['referrals'])
    denied = staff.request.post(base + '/api/referrals', headers={'X-CSRFToken': csrf}, data=payload)
    assert denied.status == 403, denied.text()
    referral_toggle.check(force=True)
    expect(tab.locator('#status-banner')).to_have_text('Change saved.')
    assert any(row['id'] == referral_id for row in staff.request.get(base + '/api/referrals').json()['referrals'])
    print('PASS: PWA referral withdrawal/restoration controls real staff referral reads and writes.')

    # Use real signed cursors and enough events to exercise a second page.
    with sqlite3.connect(env['DATABASE_PATH']) as conn:
        actor = 'user:' + str(conn.execute("SELECT id FROM users WHERE role='responder'").fetchone()[0])
        for index in range(25):
            conn.execute("INSERT INTO audit_log(actor,action,case_code,detail) VALUES(?,'case_viewed',?,?)",
                         (actor, alert['case_code'], 'PRIVATE-DETAIL-' + str(index)))
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(tab.locator('#access-list [data-event-id]')).to_have_count(20)
    tab.get_by_role('button', name='Load older activity').click()
    tab.wait_for_function("document.querySelectorAll('#access-list [data-event-id]').length > 20")
    event_ids = tab.locator('#access-list [data-event-id]').evaluate_all('(rows) => rows.map(r => r.dataset.eventId)')
    assert len(event_ids) == len(set(event_ids))
    assert 'PRIVATE-DETAIL-' not in tab.locator('#access-list').inner_text()

    # Malicious names are text, and malformed/failed responses do not become fake success.
    def evil_history(route):
        route.fulfill(json={'events': [{'id': 1000000, 'action': 'case_viewed',
            'actor_name': '<img src=x onerror="window.stage4Xss=true">',
            'viewed_at': '2026-10-24T12:00:00Z'}], 'next_cursor': None})
    tab.route('**/api/my-access?*', evil_history)
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(tab.locator('#access-list')).to_contain_text('<img src=x')
    assert tab.locator('#access-list img').count() == 0
    assert tab.evaluate('window.stage4Xss === undefined')
    tab.unroute('**/api/my-access?*', evil_history)

    def lost_save(route):
        if route.request.method == 'POST':
            assert route.fetch().ok  # The server committed, but the browser loses its response.
            route.abort()
        else:
            route.continue_()
    tab.route('**/api/consents', lost_save)
    expect(location).to_be_enabled()
    location.uncheck(force=True)
    expect(tab.locator('#status-banner')).to_contain_text('server may have saved it')
    expect(location).to_be_disabled()
    tab.unroute('**/api/consents', lost_save)
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(location).to_be_enabled()
    expect(location).not_to_be_checked()

    tab.route('**/api/consents', lambda route: route.abort())
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(tab.locator('#status-banner')).to_contain_text('sharing status is unknown')
    expect(location).to_be_disabled()
    tab.route('**/api/my-access?*', lambda route: route.abort())
    tab.get_by_role('button', name='Refresh privacy settings').click()
    expect(tab.locator('#access-list')).to_contain_text('could not be loaded')
    expect(tab.locator('#access-list [data-event-id]')).to_have_count(0)
    tab.get_by_role('button', name='Quick exit').click()
    tab.wait_for_url('**/survivor/cover.html')
    context.close()
    print('PASS: history pagination, text-safe rendering, uncertain saves and failed-refresh clearing.')

    # Migrate legacy records without inventing ownership or sending them.
    context, tab = phone()
    tab.route('**/api/alerts', lambda route: route.abort())
    tab.goto(base + '/login')
    tab.evaluate('''async () => {
      for (const name of ['cape-weather-queue', 'clear-sky-queue']) {
        const db = await new Promise((resolve, reject) => {
          const req = indexedDB.open(name, 1);
          req.onupgradeneeded = () => req.result.createObjectStore('alerts', {keyPath:'client_id'});
          req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
        });
        await new Promise((resolve, reject) => {
          const tx = db.transaction('alerts', 'readwrite');
          tx.objectStore('alerts').put({client_id:'migration-' + name, lat:null, lng:null});
          tx.oncomplete = resolve; tx.onabort = reject;
        }); db.close();
      }
    }''')
    tab.goto(base + '/survivor/')
    wait_for_async(tab, 'CWQueue.queueSize().then(n => n === 2)')
    assert tab.evaluate('''async () => {
      const db = await new Promise(resolve => {const req=indexedDB.open('cape-weather-queue',1);req.onsuccess=()=>resolve(req.result);});
      const count = await new Promise(resolve => {const req=db.transaction('alerts').objectStore('alerts').count();req.onsuccess=()=>resolve(req.result);});
      db.close();return count;
    }''') == 0
    attempted_legacy_uploads = []
    tab.on('request', lambda request: attempted_legacy_uploads.append(request.url)
           if request.method == 'POST' and request.url == base + '/api/alerts' else None)
    tab.unroute('**/api/alerts')
    tab.evaluate('CWQueue.flushQueue()')
    assert tab.evaluate('CWQueue.queueSize()') == 2
    assert attempted_legacy_uploads == []
    context.close()
    print('PASS: pending legacy records survive migration and remain blocked without an established owner.')

    # Nearby services use an explicit local fix and an actual 25/50 km filter.
    gps = "navigator.geolocation.getCurrentPosition = ok => ok({coords:{latitude:-33.9249,longitude:18.4241}});"
    context, tab = phone(gps)
    tab.route('**/api/shelters', lambda route: route.fulfill(json={'shelters': [
        {'id': 3, 'name': 'Far service', 'lat': -34.6, 'lng': 18.4241},
        {'id': 2, 'name': 'Outer service', 'lat': -34.2249, 'lng': 18.4241},
        {'id': 1, 'name': 'Near service', 'lat': -33.9349, 'lng': 18.4241},
        {'id': 4, 'name': 'Unknown location', 'lat': None, 'lng': None},
    ]}))
    tab.goto(base + '/survivor/help.html')
    expect(tab.locator('.shelter-card')).to_have_count(0)
    tab.get_by_role('button', name='Use my location').click()
    expect(tab.locator('.shelter-card')).to_have_count(1)
    expect(tab.locator('.shelter-card')).to_contain_text('Contact the service to confirm')
    tab.locator('#help-radius').select_option('50')
    expect(tab.locator('.shelter-card')).to_have_count(2)
    assert tab.locator('.shelter-name').all_text_contents() == ['Near service', 'Outer service']
    assert 'beds available' not in tab.locator('#shelter-list').inner_text()
    assert 'Full' not in tab.locator('#shelter-list').inner_text()
    tab.evaluate('() => { navigator.geolocation.getCurrentPosition = (ok, fail) => fail({code:1}); }')
    tab.get_by_role('button', name='Use my location').click()
    expect(tab.locator('.shelter-card')).to_have_count(0)
    expect(tab.locator('#shelter-list')).to_contain_text('no unfiltered directory')
    context.close()
    print('PASS: nearby radius, nearest-first order, truthful availability and denied-location clearing.')

    # Exercise accepted, placed and subsequent updates through the real alert poll.
    context, tab = phone()
    current = {'status': 'acknowledged', 'referral': {'status': 'accepted', 'shelter_name': '<img src=x>'}}
    tab.route('**/api/alerts/*/status', lambda route: route.fulfill(json=current))
    tab.goto(base + '/survivor/')
    tab.locator('#panic-btn').dispatch_event('pointerdown')
    expect(tab.locator('#view-sent')).to_be_visible()
    expect(tab.locator('#help-status')).to_contain_text('Placement is not yet confirmed')
    assert tab.locator('#help-status img').count() == 0
    current['referral']['status'] = 'placed'
    expect(tab.locator('#help-status')).to_contain_text('Placement confirmed')
    context.close()

    # Install the new worker over stale owned API caches; unrelated caches survive.
    context, tab = phone(workers='allow')
    tab.goto(base + '/login')
    tab.evaluate('''async () => {
      for (const name of ['cape-weather-data-v1','clear-sky-data-v1','unrelated-app-cache']) {
        const cache = await caches.open(name); await cache.put('/api/shelters', new Response('old private result'));
      }
    }''')
    tab.goto(base + '/survivor/')
    tab.wait_for_function('navigator.serviceWorker.controller !== null')
    names = tab.evaluate('caches.keys()')
    assert 'cape-weather-data-v1' not in names and 'clear-sky-data-v1' not in names
    assert 'unrelated-app-cache' in names
    assert tab.evaluate('''async () => {
      for (const name of await caches.keys()) {
        if (name === 'unrelated-app-cache') continue;
        for (const req of await (await caches.open(name)).keys()) if (new URL(req.url).pathname.startsWith('/api/')) return false;
      } return true;
    }''')
    context.set_offline(True)
    tab.goto(base + '/survivor/privacy.html')
    expect(tab.locator('#consent-location_sharing')).to_be_disabled()
    expect(tab.locator('#status-banner')).to_contain_text('sharing status is unknown')
    assert tab.evaluate("fetch('/api/shelters').then(() => false, () => true)")
    context.close()
    print('PASS: truthful referral status; public-only offline shell and old API-cache cleanup.')
    assert not errors, errors
    page.goto(base + '/dashboard')


if __name__ == '__main__':
    main(staff_check=exercise)
