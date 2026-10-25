"""Stage 5 browser integration: offline diary v2, receipt verification, own-entry detail, sharing controls, and Quick Exit."""
import io
import sqlite3
from PIL import Image
from playwright.sync_api import expect
from stage0_browser import main
from stage2_pwa_browser import FAST


def create_png_bytes():
    buf = io.BytesIO()
    with Image.new('RGB', (1600, 1200), (30, 110, 114)) as img:
        img.save(buf, format='PNG')
    return buf.getvalue()


def exercise(page, staff, base, env):
    headers = {'X-Device-Token': env.get('DEVICE_TOKEN', 'demo-device')}
    browser = staff.browser
    errors = []

    def phone(script='', workers='block'):
        context = browser.new_context(
            viewport={'width': 412, 'height': 846},
            is_mobile=True,
            has_touch=True,
            service_workers=workers,
        )
        context.add_init_script(FAST + script)
        tab = context.new_page()
        tab.on('pageerror', lambda error: errors.append(str(error)))
        return context, tab

    # Ensure global diary_sharing consent is active for responder coordination checks
    res = staff.request.post(
        base + '/api/consents',
        headers=headers,
        data={'item': 'diary_sharing', 'active': True},
    )
    assert res.ok, res.text()

    context, tab = phone()
    tab.goto(base + '/survivor/diary.html', wait_until='networkidle')
    assert tab.title() == 'Clear Sky'
    assert tab.evaluate('Boolean(window.CWDiary && window.CWDiary.canonicalNote)')

    # 1. Offline capture with photo compression + CRLF Unicode note
    fail_uploads = {'mode': '503'}

    def handle_diary_post(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        if fail_uploads['mode'] == '503':
            route.fulfill(
                status=503,
                content_type='application/json',
                body='{"error":"diary_storage_unavailable"}',
            )
        elif fail_uploads['mode'] == 'bad_receipt':
            route.fulfill(
                status=200,
                content_type='application/json',
                body='{"stored":true,"id":999,"client_id":"wrong","file_hash":"bad"}',
            )
        elif fail_uploads['mode'] == '401':
            route.fulfill(
                status=401,
                content_type='application/json',
                body='{"error":"device_token_required"}',
            )
        else:
            route.continue_()

    context.route('**/api/diary', handle_diary_post)

    tab.fill('#diary-note', '  Café — naïve façade 🌍\r\nSecond line  ')
    tab.set_input_files(
        '#diary-photo-input',
        {
            'name': 'evidence.png',
            'mimeType': 'image/png',
            'buffer': create_png_bytes(),
        },
    )
    expect(tab.locator('#photo-preview-wrap')).to_be_visible()
    expect(tab.locator('#photo-size-info')).to_contain_text('1280×960px')

    tab.click('#diary-save-btn')
    expect(tab.locator('#diary-entries-list')).to_contain_text('Café — naïve façade 🌍')

    queued = tab.evaluate('window.CWDiary.getQueuedItems()')
    assert len(queued) == 1
    assert queued[0]['contract_version'] == 2
    assert queued[0]['note'] == 'Café — naïve façade 🌍\nSecond line'
    assert len(queued[0]['note_sha256']) == 64
    assert len(queued[0]['photo_sha256']) == 64
    assert len(queued[0]['entry_fingerprint']) == 64
    assert queued[0]['captured_at'].endswith('Z')

    # 2. Close and reopen tab while offline: queued item must persist
    tab.close()
    tab = context.new_page()
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.goto(base + '/survivor/diary.html', wait_until='networkidle')
    expect(tab.locator('#diary-entries-list')).to_contain_text('Café — naïve façade 🌍')

    # 3. Mismatched receipt must NOT delete local queued item
    fail_uploads['mode'] = 'bad_receipt'
    tab.evaluate('window.CWDiary.flushQueue()')
    queued_after_bad = tab.evaluate('window.CWDiary.getQueuedItems()')
    assert len(queued_after_bad) == 1

    # 4. Permanent 401 error marks item as auth_expired and halts automatic retry loop
    fail_uploads['mode'] = '401'
    tab.evaluate('window.CWDiary.flushQueue()')
    queued_after_401 = tab.evaluate('window.CWDiary.getQueuedItems()')
    assert len(queued_after_401) == 1
    assert queued_after_401[0]['status'] == 'auth_expired'
    expect(tab.locator('#diary-entries-list')).to_contain_text('Authentication expired')

    # 5. Manual Refresh & retry uploads when server is back online (multipart v2 upload)
    fail_uploads['mode'] = 'online'
    tab.click('#sync-refresh-btn')
    expect(tab.locator('#diary-entries-list')).to_contain_text('Saved to account')
    assert len(tab.evaluate('window.CWDiary.getQueuedItems()')) == 0

    # 6. View uploaded entry detail + authenticated photo Blob URL
    tab.click('.btn-view-entry')
    expect(tab.locator('#diary-entry-detail')).to_be_visible()
    expect(tab.locator('#diary-entry-detail')).to_contain_text('Café — naïve façade 🌍')
    tab.wait_for_function(
        'document.getElementById("detail-photo-img").src.startsWith("blob:")'
    )

    # 7. Per-entry share/unshare toggle + responder workspace reflection + uncertain timeout recovery
    tab.click('#detail-share-btn')
    expect(tab.locator('#diary-entry-detail')).to_contain_text('Shared with responder')

    alert = staff.request.post(
        base + '/api/alerts',
        headers=headers,
        data={'client_id': 'stage5-case-alert', 'lat': -33.9249, 'lng': 18.4241},
    ).json()
    page.goto(f"{base}/cases/{alert['case_code']}")
    expect(page.get_by_role('list', name='Shared diary entries')).to_contain_text('Café — naïve façade 🌍')

    # Simulate uncertain network drop after server processes unshare
    intercept_share = {'drop': True}

    def handle_share(route):
        if intercept_share['drop']:
            intercept_share['drop'] = False
            with sqlite3.connect(env['DATABASE_PATH']) as conn:
                conn.execute('UPDATE diary_entries SET shared = 0')
                conn.commit()
            route.abort('failed')
        else:
            route.continue_()

    context.route('**/api/diary/*/share', handle_share)
    tab.click('#detail-share-btn')
    expect(tab.locator('#diary-entry-detail')).to_contain_text('Private (Only you)')

    # 8. Emergency alert priority while diary endpoint fails
    fail_uploads['mode'] = '503'
    alert_tab = context.new_page()
    alert_tab.on('pageerror', lambda error: errors.append(str(error)))
    alert_tab.goto(base + '/survivor/', wait_until='networkidle')
    alert_tab.locator('#panic-btn').dispatch_event('pointerdown')
    expect(alert_tab.locator('#view-sent')).to_be_visible()
    alert_tab.close()

    # 9. Quick Exit clears unsaved state, revokes blob URLs, and preserves offline queues
    tab.fill('#diary-note', 'Queued sensitive note before exit')
    tab.click('#diary-save-btn')
    tab.wait_for_function('window.CWDiary.getQueuedItems().then(q => q.length === 1)')
    tab.fill('#diary-note', 'Unsaved draft in textarea')
    tab.click('#quick-exit-btn')
    tab.wait_for_url('**/survivor/cover.html')

    tab.goto(base + '/survivor/diary.html', wait_until='networkidle')
    surviving_queue = tab.evaluate('window.CWDiary.getQueuedItems()')
    assert len(surviving_queue) == 1
    assert surviving_queue[0]['note'] == 'Queued sensitive note before exit'

    context.close()
    assert not errors, errors
    print('PASS: Stage 5 offline diary v2, receipt verification, own-entry detail, sharing controls, alert priority, and Quick Exit.')


if __name__ == '__main__':
    main(exercise)
