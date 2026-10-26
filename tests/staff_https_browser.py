"""Real Chromium HTTPS auth; a temporary trusted CA, never TLS bypass flags.

Requires certutil (libnss3-tools) and the pinned browser/dev dependencies.
Only isolated fictional accounts are used. No mail/SMS providers are configured.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image
from playwright.sync_api import sync_playwright, expect
import pyotp
import zxingcpp

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def https_fixture():
    with tempfile.TemporaryDirectory(prefix='avenra-https-') as directory:
        root = Path(directory)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Avenra isolated browser CA')])
        now = datetime.now(timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
              .not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
              .sign(key, hashes.SHA256()))
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]))
                .issuer_name(name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        for filename, data in (('ca.pem', ca.public_bytes(serialization.Encoding.PEM)),
                               ('cert.pem', leaf.public_bytes(serialization.Encoding.PEM)),
                               ('key.pem', leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))):
            (root/filename).write_bytes(data)
            (root/filename).chmod(0o600)
        nss = root/'.pki/nssdb'
        nss.mkdir(parents=True)
        subprocess.run(['certutil', '-N', '-d', 'sql:'+str(nss), '--empty-password'], check=True, capture_output=True)
        subprocess.run(['certutil', '-A', '-d', 'sql:'+str(nss), '-n', 'isolated-auth-ca', '-t', 'C,,', '-i', str(root/'ca.pem')], check=True, capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'https://localhost:{port}'
        blocked = ('DATABASE_', 'SMTP_', 'TWILIO_', 'WEBPUSH_', 'STAFF_MFA_', 'OFFLINE_QUEUE_', 'AVENRA_', 'VERCEL')
        env = {k: v for k, v in os.environ.items() if not k.startswith(blocked)}
        env.update(APP_ENV='development', COOKIE_SECURE='1', SECRET_KEY=secrets.token_urlsafe(48),
                   PUBLIC_BASE_URL=base, DATABASE_PATH=str(root/'auth.sqlite3'), UPLOADS_DIR=str(root/'uploads'),
                   AVENRA_SMS_ENABLED='0', AVENRA_WEBPUSH_ENABLED='0', AVENRA_PUSH_SELF_TEST='0')
        server = subprocess.Popen([sys.executable, '-m', 'gunicorn', 'app:app', '--workers', '1', '--threads', '4',
                                   '--bind', f'127.0.0.1:{port}', '--certfile', str(root/'cert.pem'), '--keyfile', str(root/'key.pem')],
                                  cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            trusted = ssl.create_default_context(cafile=str(root/'ca.pem'))
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('HTTPS fixture failed to start')
                try:
                    with urllib.request.urlopen(base+'/health', context=trusted, timeout=1):
                        break
                except OSError as error:
                    last_error = error
                    time.sleep(.1)
            else:
                raise RuntimeError('HTTPS fixture startup timed out') from last_error
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(env={**os.environ, 'HOME': directory})
                try:
                    yield browser, base, env
                finally:
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)


class StaffHTTPSBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = https_fixture()
        cls.browser, cls.base, cls.env = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.__exit__(None, None, None)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 1200})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()

    def test_forgot_submission_keeps_origin_and_cookie(self):
        page = self.page
        page.goto(self.base+'/forgot-password')
        page.get_by_label('Work email').fill('absent@example.invalid')
        with page.expect_response(lambda r: r.request.method == 'POST') as received:
            page.get_by_role('button', name='Send reset link').click()
        response = received.value
        headers = response.request.all_headers()
        self.assertEqual(response.status, 200, f'Forgot password: HTTP {response.status}, Origin={headers.get("origin")}')
        self.assertEqual(headers['origin'], self.base)
        self.assertIn('cookie', headers)
        self.assertIsNone(response.request.redirected_from)
        expect(page.get_by_role('status')).to_contain_text('If an eligible account exists')

    def test_password_mfa_enrollment_and_normal_login(self):
        from werkzeug.security import generate_password_hash
        email = 'https-staff+enroll@example.test'
        password = secrets.token_urlsafe(24)
        with sqlite3.connect(self.env['DATABASE_PATH']) as conn:
            conn.execute("INSERT INTO users(name,role,email,org,is_active,auth_version,password_hash) VALUES('HTTPS staff','responder',?,'Test',1,1,?)", (email, generate_password_hash(password)))
        page = self.page
        external, errors, violations = [], [], []
        page.on('request', lambda r: external.append(r.url) if not r.url.startswith(self.base+'/') else None)
        page.on('pageerror', lambda e: errors.append(type(e).__name__))
        page.on('console', lambda m: violations.append(m.text) if 'Content Security Policy' in m.text else None)
        page.goto(self.base+'/login')
        page.get_by_label('Work email').fill(email)
        page.get_by_label('Password', exact=True).fill(password)
        with page.expect_response(lambda r: r.request.method == 'POST') as received:
            page.get_by_role('button', name='Sign in', exact=True).click()
        self.assertEqual(received.value.status, 302)
        self.assertEqual(received.value.headers['location'], '/mfa')
        page.wait_for_url('**/mfa')
        self.assertEqual(page.evaluate("fetch('/api/session').then(r=>r.status)"), 401)
        cookies = self.context.cookies()
        self.assertTrue(all(c['secure'] and c['httpOnly'] and c['sameSite']=='Lax' for c in cookies))
        secret = page.locator('#mfa-secret').text_content()
        # This assertion reproduces the reported failure before testing QR styling.
        page.get_by_label('Verification code', exact=True).fill(pyotp.TOTP(secret).now())
        with page.expect_response(lambda r: r.request.method == 'POST') as received:
            page.get_by_role('button', name='Verify', exact=True).click()
        response = received.value
        self.assertEqual(response.status, 200, f'MFA: HTTP {response.status}, Origin={response.request.all_headers().get("origin")}')
        self.assertEqual(response.request.all_headers()['origin'], self.base)
        codes = page.locator('[data-recovery-code]').all_text_contents()
        self.assertEqual(len(codes), 10)
        self.check_layout(page, recovery=True)
        page.get_by_role('link', name='Continue to workspace').click()
        page.wait_for_url('**/dashboard')
        page.get_by_role('button', name='Sign out everywhere').click()
        page.wait_for_url('**/login')
        page.get_by_label('Work email').fill(email)
        page.get_by_label('Password', exact=True).fill(password)
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.wait_for_url('**/mfa')
        self.assertEqual(page.locator('#mfa-secret, .mfa-qr').count(), 0)
        self.check_layout(page)
        page.get_by_label('Verification code', exact=True).fill(codes[0])
        page.get_by_role('button', name='Verify', exact=True).click()
        page.wait_for_url('**/dashboard')
        self.assertEqual(page.evaluate("fetch('/api/session').then(r=>r.status)"), 200)
        self.assertFalse(external)
        self.assertFalse(errors)
        self.assertFalse(violations)

    def test_qr_scans_same_secret_in_both_themes_and_mobile(self):
        from werkzeug.security import generate_password_hash
        email, password = 'qr+label@example.test', secrets.token_urlsafe(24)
        with sqlite3.connect(self.env['DATABASE_PATH']) as conn:
            conn.execute("INSERT INTO users(name,role,email,org,is_active,auth_version,password_hash) VALUES('QR staff','responder',?,'Test',1,1,?)", (email, generate_password_hash(password)))
        page = self.page
        requests = []
        page.on('request', lambda r: requests.append(r.url))
        page.goto(self.base+'/login')
        page.get_by_label('Work email').fill(email)
        page.get_by_label('Password', exact=True).fill(password)
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.wait_for_url('**/mfa')
        expect(page.locator('.mfa-qr svg')).to_be_visible()
        secret = page.locator('#mfa-secret').text_content()
        self.assertFalse(page.locator('#mfa-secret').is_visible())
        page.get_by_text('Can’t scan? Enter setup key', exact=True).focus()
        self.assertNotEqual(page.locator('summary').evaluate('(e)=>getComputedStyle(e).outlineStyle'), 'none')
        page.keyboard.press('Enter')
        expect(page.locator('#mfa-secret')).to_be_visible()
        for theme in ('light', 'dark'):
            page.emulate_media(color_scheme=theme)
            image = Image.open(io.BytesIO(page.locator('.mfa-qr').screenshot()))
            decoded = zxingcpp.read_barcode(image)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded.text, pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name='Avenra'))
            self.assertEqual(image.convert('RGB').getpixel((0, 0)), (255, 255, 255))
            width = page.locator('.mfa-qr').bounding_box()['width']
            self.assertTrue(220 <= width <= 240)
        self.check_layout(page)
        refreshed = page.reload()
        self.assertIn('no-store', refreshed.headers['cache-control'])
        self.assertEqual(page.locator('#mfa-secret').text_content(), secret)
        storage = page.evaluate('JSON.stringify([localStorage,sessionStorage])')
        self.assertNotIn(secret, storage)
        self.assertTrue(all(url.startswith(self.base+'/') for url in requests))
        self.assertTrue(all(secret not in url and 'otpauth' not in url for url in requests))

    def check_layout(self, page, recovery=False):
        for theme in ('light', 'dark'):
            page.emulate_media(color_scheme=theme)
            for width, height in ((1280, 1200), (390, 844), (320, 420), (390, 300)):
                page.set_viewport_size({'width': width, 'height': height})
                self.assertTrue(page.locator('html').evaluate('(e)=>e.scrollWidth<=innerWidth'))
                expect(page.locator('.brand')).to_be_visible()
                target = page.get_by_role('link', name='Continue to workspace') if recovery else page.get_by_label('Verification code', exact=True)
                target.focus()
                target.scroll_into_view_if_needed()
                box = target.bounding_box()
                self.assertTrue(box['y'] >= 0 and box['y']+box['height'] <= height, (theme, width, height, box))
        page.set_viewport_size({'width': 1280, 'height': 1200})


if __name__ == '__main__':
    unittest.main(verbosity=2)
