"""Optional real-browser Stage 0 checks. Requires Playwright and its Chromium.

Run from any directory: python tests/stage0_browser.py
AVENRA_SERVER_PYTHON can select the interpreter running the pinned Gunicorn app.
No external messages are sent; all records and browser state are temporary.
"""
import os
import base64
import hashlib
import json
import sqlite3
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def complete_staff_mfa(page, env, email='nomsa@avenra.demo'):
    """Use actual TOTP/recovery flow against isolated fictional fixture accounts."""
    import pyotp
    from cryptography.fernet import Fernet
    page.wait_for_url('**/mfa')
    enrolling = page.locator('#mfa-secret').count() == 1
    saved = getattr(complete_staff_mfa, 'codes', {})
    key = (env['DATABASE_PATH'], email)
    if enrolling:
        code = pyotp.TOTP(page.locator('#mfa-secret').inner_text()).now()
    else:
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            row = conn.execute('SELECT m.encrypted_secret,m.last_counter FROM staff_mfa m JOIN users u ON u.id=m.user_id WHERE u.email=?', (email,)).fetchone()
        cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(('dev-mfa:'+env['SECRET_KEY']).encode()).digest()))
        totp = pyotp.TOTP(cipher.decrypt(row[0].encode()).decode())
        code = totp.now() if int(time.time())//30 > row[1] else saved[key].pop()
    page.get_by_label('Verification code', exact=True).fill(code)
    page.get_by_role('button', name='Verify', exact=True).click()
    if enrolling:
        page.get_by_role('heading', name='Save your recovery codes safely').wait_for()
        saved[key] = page.locator('[data-recovery-code]').all_text_contents()
        assert len(saved[key]) == 10
        complete_staff_mfa.codes = saved
        page.get_by_role('link', name='Continue to workspace').click()


def wait_for_async(page, expression, *, arg=None, timeout=30000):
    """Poll resolved values: wait_for_function can treat a Promise as truthy.

    Page.evaluate awaits each Promise. Pump Playwright events between attempts.
    Never infer successful storage from an unresolved/false predicate handle.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        if page.evaluate(expression, arg):
            return
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for resolved async browser condition')
        page.wait_for_timeout(50)


def main(staff_check=None, browser_name='chromium'):
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        # Never pass hosted database, origin or mail credentials to a fixture server.
        for key in ('DATABASE_URL', 'PUBLIC_BASE_URL', 'VERCEL', 'VERCEL_ENV',
                    'SMTP_HOST', 'SMTP_PORT', 'SMTP_TLS_MODE', 'SMTP_USERNAME',
                    'SMTP_PASSWORD', 'SMTP_FROM', 'STAFF_MFA_ENCRYPTION_KEY'):
            env.pop(key, None)

        for name in ('SMS_WEBHOOK_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            env.pop(name, None)
        env.update(APP_ENV='evaluation', COOKIE_SECURE='0',
                   SECRET_KEY=secrets.token_urlsafe(48),
                   DATABASE_PATH=str(Path(directory) / 'evaluation.sqlite3'),
                   UPLOADS_DIR=str(Path(directory) / 'uploads'))
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        env.pop('OFFLINE_QUEUE_RETIRED_KEYS_JSON',None)
        env['OFFLINE_QUEUE_PRIVATE_KEY_PEM']=rsa.generate_private_key(public_exponent=65537,key_size=3072).private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        server = subprocess.Popen(
            [os.environ.get('AVENRA_SERVER_PYTHON', sys.executable), '-m', 'gunicorn',
             'app:app', '--workers', '1', '--threads', '4', '--bind', f'127.0.0.1:{port}'],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Gunicorn failed to start')
                try:
                    with urllib.request.urlopen(base + '/health', timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError('Gunicorn startup timed out')
            with sync_playwright() as playwright:
                browser = getattr(playwright, browser_name).launch()
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('pageerror', lambda error: print(f"\nBROWSER ERROR: {error.stack}", flush=True))
                page.goto(base + '/login')
                page.get_by_label('Work email').fill('unknown@example.test')
                page.get_by_label('Password', exact=True).fill('Wrong-Password-123!')
                page.get_by_role('button', name='Sign in', exact=True).click()
                page.get_by_role('alert').wait_for()
                assert "don't match" in page.get_by_role('alert').inner_text()
                page.goto(base + '/evaluation')
                page.get_by_role('button', name='Sign in as Social worker').click()
                complete_staff_mfa(page, env)
                page.wait_for_url('**/dashboard')
                assert 'Nomsa D' in page.locator('.topbar-user').inner_text()
                if staff_check is not None:
                    staff_check(page, context, base, env)
                page.get_by_role('link', name='Shelters', exact=True).click()
                expect(page.locator('tbody tr')).to_have_count(3)
                if os.environ.get('AVENRA_SCREENSHOT_DIR'):
                    page.screenshot(path=str(Path(os.environ['AVENRA_SCREENSHOT_DIR']) / 'staff.png'), full_page=True)
                page.get_by_role('button', name='Sign out everywhere').click()
                page.wait_for_url('**/login')
                assert context.request.get(base + '/api/alerts').status == 401
                assert not errors, errors
                context.close()

                mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                page = mobile.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('pageerror', lambda error: print(f"\nBROWSER ERROR: {error.stack}", flush=True))
                identity = mobile.request.get(base + '/survivor/manifest.json').json()
                page.goto(base + '/survivor/')
                page.wait_for_function('navigator.serviceWorker.controller !== null')
                page.wait_for_function("document.querySelector('#offline-state').textContent.includes('ready to open offline')")
                assert page.locator('html').evaluate('(el) => el.scrollWidth <= innerWidth')
                if os.environ.get('AVENRA_SCREENSHOT_DIR'):
                    page.screenshot(path=str(Path(os.environ['AVENRA_SCREENSHOT_DIR']) / 'pwa.png'), full_page=True)
                mobile.set_offline(True)
                page.goto(base + '/survivor/index.html')
                assert page.title() == identity['name']
                assert 'offline' in page.locator('#connection-state').inner_text()
                assert page.evaluate("fetch('/api/alerts').then(() => false, () => true)")
                cached = page.evaluate('''async () => {
                    const urls = [];
                    for (const name of await caches.keys()) {
                        for (const request of await (await caches.open(name)).keys()) urls.push(request.url);
                    }
                    return urls;
                }''')
                assert cached and all('/survivor/' in url or url.endswith('/static/css/style.css') for url in cached), cached
                local_values = page.evaluate(
                    "() => Object.fromEntries(Object.entries(localStorage))"
                )

                allowed_keys = {"clear-sky-alert-owner-v1", "clear-sky-alert-public-key-v1"}
                assert set(local_values) <= allowed_keys, (
                    "Unexpected localStorage keys",
                    list(local_values),
                )

                owner = local_values.get("clear-sky-alert-owner-v1")
                if owner is not None:
                    assert (
                            owner.isascii()
                            and owner.isdecimal()
                            and 0 < int(owner) <= 9007199254740991
                            and str(int(owner)) == owner
                    ), "Invalid cached account identifier"
                public_record=local_values.get('clear-sky-alert-public-key-v1')
                if public_record:
                    public_record=json.loads(public_record)
                    assert set(public_record)=={'kid','spki'}
                    public_bytes=base64.b64decode(public_record['spki'],validate=True)
                    public_key=serialization.load_der_public_key(public_bytes)
                    assert isinstance(public_key,rsa.RSAPublicKey) and public_key.key_size>=3072
                    assert hashlib.sha256(public_bytes).hexdigest()==public_record['kid']
                assert not errors, errors
                mobile.close()
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
    print('PASS: visible login errors, staff identity/navigation/sign-out, mobile layout, offline shell, private API cache exclusion, no browser script errors.')


if __name__ == '__main__':
    main()
