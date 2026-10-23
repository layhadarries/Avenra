"""Local Gunicorn smoke checks using temporary fictional data; no provider calls."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        for name in ('SMS_WEBHOOK_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            env.pop(name, None)
        env.update(APP_ENV='evaluation', COOKIE_SECURE='0',
                   SECRET_KEY=secrets.token_urlsafe(48),
                   DATABASE_PATH=str(Path(directory) / 'evaluation.sqlite3'),
                   UPLOADS_DIR=str(Path(directory) / 'uploads'))
        missing = dict(env, SECRET_KEY='')
        result = subprocess.run([sys.executable, '-c', 'import app'], cwd=ROOT,
                                env=missing, capture_output=True, text=True)
        assert result.returncode != 0 and 'Set SECRET_KEY' in result.stderr
        insecure = dict(env, APP_ENV='production', COOKIE_SECURE='0')
        result = subprocess.run([sys.executable, '-c', 'import app'], cwd=ROOT,
                                env=insecure, capture_output=True, text=True)
        assert result.returncode != 0 and 'Production requires' in result.stderr
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        def serve(check):
            process = subprocess.Popen(
                [sys.executable, '-m', 'gunicorn', 'app:app', '--workers', '1',
                 '--threads', '4', '--bind', f'127.0.0.1:{port}'],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Gunicorn failed to start')
                    try:
                        with urllib.request.urlopen(base + '/health', timeout=1) as response:
                            counts = json.load(response)['counts']
                        break
                    except (OSError, ValueError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError('Gunicorn health check timed out')
                assert counts['users'] == 4 and counts['shelters'] == 3 and counts['contacts'] == 2
                check()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        def login_check():
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(base + '/evaluation', timeout=3) as response:
                html = response.read().decode()
                assert 'no-store' in response.headers['Cache-Control']
            token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
            data = urllib.parse.urlencode({'csrf_token': token}).encode()
            with opener.open(base + '/evaluation/login/responder', data=data, timeout=3) as response:
                assert response.status == 200 and response.url.endswith('/dashboard')
            with opener.open(base + '/api/alerts', timeout=3) as response:
                assert response.status == 200
            with urllib.request.urlopen(base + '/survivor/service-worker.js', timeout=3) as response:
                assert response.status == 200
            with sqlite3.connect(env['DATABASE_PATH']) as conn:
                assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='evaluation_login'").fetchone()[0] == 1
                conn.execute("UPDATE users SET is_active=0,auth_version=7 WHERE role='responder'")
        serve(login_check)
        def restart_check():
            with sqlite3.connect(env['DATABASE_PATH']) as conn:
                row = conn.execute("SELECT is_active,auth_version FROM users WHERE role='responder'").fetchone()
                assert row == (0, 7), 'Restart reset account state'
                assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='evaluation_login'").fetchone()[0] == 1
        serve(restart_check)
    print('PASS: secret/cookie guards, Gunicorn, health counts, CSRF role sign-in, audit, PWA asset, restart preservation. No SMS sent.')


if __name__ == '__main__':
    main()
