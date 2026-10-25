"""Fictional weather-entry setup and real WebAuthn via a virtual authenticator.

Virtual verification is not evidence of physical fingerprint/Face ID acceptance.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import expect
from stage0_browser import main


def secret(screen, base):
    screen.goto(base + '/survivor/cover.html')
    screen.locator('[data-thursday="1"]').click()
    expect(screen.locator('#cv-modal')).to_be_visible()


def enter_pin(screen, pin, setup=False):
    pad = screen.locator('#ob-pin-pad' if setup else '#pin-pad')
    for digit in pin:
        pad.get_by_role('button', name=digit, exact=True).click()


def finish_steps(screen, name='Fictional Alex'):
    expect(screen.locator('[data-ob="2"]')).to_be_visible()
    screen.locator('#ob-name').fill(name)
    screen.locator('#ob-next-2').click()
    screen.locator('#ob-next-3').click()
    screen.locator('#ob-finish').click()
    screen.wait_for_url('**/survivor/')


def exercise(page, context, base, env):
    phone = context.browser.new_context(viewport={'width': 390, 'height': 844})
    errors = []
    try:
        screen = phone.new_page()
        screen.on('pageerror', lambda error: errors.append(str(error)))
        phone.route('https://api.open-meteo.com/**', lambda route: route.abort())
        secret(screen, base)
        expect(screen.locator('[data-ob="1"]')).to_be_visible()
        enter_pin(screen, '1234', setup=True)
        enter_pin(screen, '1235', setup=True)
        expect(screen.locator('#ob-pin-err')).to_contain_text('did not match')
        enter_pin(screen, '2468', setup=True)
        enter_pin(screen, '2468', setup=True)
        expect(screen.locator('[data-ob="2"]')).to_be_visible()
        screen.locator('#ob-name').fill('Fictional Alex')
        screen.locator('#ob-next-2').click()
        screen.locator('#ob-c1-name').fill('New Fictional Contact')
        screen.locator('#ob-c1-phone').fill('0821234567')
        if os.environ.get('AVENRA_SCREENSHOT_DIR'):
            screen.screenshot(path=str(Path(os.environ['AVENRA_SCREENSHOT_DIR']) / 'onboarding-contacts.png'))
        screen.locator('#ob-next-3').click()
        screen.locator('#ob-finish').click()
        screen.wait_for_url('**/survivor/')
        stored = screen.evaluate('Object.fromEntries(Object.entries(localStorage))')
        assert json.loads(stored['cs_pin_hash'])['version'] == 2
        assert 'Fictional Alex' not in json.dumps(stored)
        assert '0821234567' not in json.dumps(stored)
        result = phone.request.get(base + '/api/onboarding', headers={'X-Device-Token': 'demo-device'}).json()
        assert result['name'] == 'Fictional Alex'
        assert any(row['name'] == 'New Fictional Contact' for row in result['contacts'])
        secret(screen, base)
        enter_pin(screen, '1111')
        expect(screen.locator('#pin-err')).to_contain_text('Incorrect')
        enter_pin(screen, '2468')
        screen.wait_for_url('**/survivor/')
        # Legacy PINs still work and are upgraded without a reset.
        screen.evaluate("""() => {
            let hash = 2166136261;
            for (const c of 'safepath:1357') { hash ^= c.charCodeAt(0); hash = Math.imul(hash, 16777619); }
            localStorage.setItem('cs_pin_hash', (hash >>> 0).toString(16));
        }""")
        secret(screen, base)
        enter_pin(screen, '1357')
        screen.wait_for_url('**/survivor/')
        assert screen.evaluate("JSON.parse(localStorage.getItem('cs_pin_hash')).version") == 2
        screen.wait_for_function('navigator.serviceWorker.controller !== null')
        phone.set_offline(True)
        secret(screen, base)
        enter_pin(screen, '1357')
        screen.wait_for_url('**/survivor/')
        assert not errors, errors
    finally:
        phone.close()

    biometric = context.browser.new_context(viewport={'width': 390, 'height': 844})
    try:
        # WebAuthn RP IDs must be domains, not the fixture's IPv4 literal.
        biometric_base = base.replace('127.0.0.1', 'localhost')
        screen = biometric.new_page()
        biometric.route('https://api.open-meteo.com/**', lambda route: route.abort())
        cdp = biometric.new_cdp_session(screen)
        cdp.send('WebAuthn.enable')
        authenticator = cdp.send('WebAuthn.addVirtualAuthenticator', {'options': {
            'protocol': 'ctap2', 'transport': 'internal', 'hasResidentKey': True,
            'hasUserVerification': True, 'isUserVerified': True, 'automaticPresenceSimulation': True,
        }})['authenticatorId']
        secret(screen, biometric_base)
        screen.locator('#ob-device-unlock').click()
        finish_steps(screen, 'Fictional Device User')
        assert screen.evaluate("localStorage.getItem('cs_pin_hash')") is None
        assert screen.evaluate('CWQueue !== undefined')
        record = screen.evaluate("localStorage.getItem('cs_device_unlock')")
        assert json.loads(record)['version'] == 1
        secret(screen, biometric_base)
        expect(screen.locator('#pin-pad')).to_be_hidden()
        screen.locator('#device-unlock').click()
        screen.wait_for_url('**/survivor/')
        # A response without user verification must not unlock the screen.
        cdp.send('WebAuthn.setUserVerified', {'authenticatorId': authenticator, 'isUserVerified': False})
        secret(screen, biometric_base)
        screen.locator('#device-unlock').click()
        expect(screen.locator('#pin-err')).to_contain_text('not completed', timeout=65000)
        assert screen.url.endswith('/cover.html')
        screen.locator('#cv-modal-close').click()
        assert screen.evaluate("localStorage.getItem('cs_device_unlock')") == record
    finally:
        biometric.close()

    unpaired = context.browser.new_context(viewport={'width': 320, 'height': 740})
    try:
        screen = unpaired.new_page()
        unpaired.route('https://api.open-meteo.com/**', lambda route: route.abort())
        unpaired.route('**/api/onboarding', lambda route: route.fulfill(
            status=401, content_type='application/json', body='{"error":"device_pairing_required"}'))
        secret(screen, base)
        enter_pin(screen, '8642', setup=True)
        enter_pin(screen, '8642', setup=True)
        screen.locator('#cv-modal-close').click()
        assert screen.evaluate("localStorage.getItem('cs_pin_hash')") is None
        screen.locator('[data-thursday="1"]').click()
        enter_pin(screen, '8642', setup=True)
        enter_pin(screen, '8642', setup=True)
        screen.locator('#ob-name').fill('Unsaved Fictional Name')
        screen.locator('#ob-next-2').click()
        screen.locator('#ob-next-3').click()
        screen.locator('#ob-finish').click()
        expect(screen.locator('#ob-save-status')).to_contain_text('private connection link')
        assert screen.evaluate("localStorage.getItem('cs_pin_hash')") is None
        assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth'), screen.evaluate('''() =>
            Array.from(document.querySelectorAll('body *')).filter(el => el.getBoundingClientRect().right > innerWidth)
              .map(el => [el.tagName, el.className, el.getBoundingClientRect().width])''')
        screen.locator('#ob-skip-save').click()
        screen.wait_for_url('**/survivor/')
        assert 'Unsaved Fictional Name' not in screen.evaluate('JSON.stringify(localStorage)')
    finally:
        unpaired.close()
    page.goto(base + '/dashboard')
    print('PASS: weather hidden entry, name/contact setup, PIN confirmation/legacy migration, signed WebAuthn unlock and UV rejection.')


if __name__ == '__main__':
    main(staff_check=exercise)
