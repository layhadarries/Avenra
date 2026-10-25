"""Optional real-browser Stage 0 checks. Requires Playwright and its Chromium.

Run from any directory: python tests/stage0_browser.py
AVENRA_SERVER_PYTHON can select the interpreter running the pinned Gunicorn app.
No external messages are sent; all records and browser state are temporary.
"""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main(staff_check=None):
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        # Never pass hosted database, origin or mail credentials to a fixture server.
        for key in ('DATABASE_URL', 'PUBLIC_BASE_URL', 'VERCEL', 'VERCEL_ENV',
                    'SMTP_HOST', 'SMTP_PORT', 'SMTP_TLS_MODE', 'SMTP_USERNAME',
                    'SMTP_PASSWORD', 'SMTP_FROM'):
            env.pop(key, None)

        for name in ('SMS_WEBHOOK_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            env.pop(name, None)
        env.update(APP_ENV='evaluation', COOKIE_SECURE='0',
                   SECRET_KEY=secrets.token_urlsafe(48),
                   DATABASE_PATH=str(Path(directory) / 'evaluation.sqlite3'),
                   UPLOADS_DIR=str(Path(directory) / 'uploads'))
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
                browser = playwright.chromium.launch()
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
                page.wait_for_url('**/dashboard')
                assert 'Nomsa D' in page.locator('.topbar-user').inner_text()
                if staff_check is not None:
                    staff_check(page, context, base, env)
                page.get_by_role('link', name='Shelters', exact=True).click()
                assert page.locator('tbody tr').count() == 3
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
                assert page.evaluate('localStorage.length') == 0
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
