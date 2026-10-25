"""Complete real MFA for fictional fixture staff; never forge authenticated cookies."""
from contextlib import closing
import re
import pyotp


def complete_mfa(testcase, base_url=None):
    import test_avenra as fixtures
    from avenra.services.mfa_service import encryption
    options = {'base_url':base_url} if base_url else {}
    page = testcase.client.get('/mfa', **options)
    testcase.assertEqual(page.status_code, 200)
    secret_match = re.search(r'id="mfa-secret">([A-Z2-7]+)</code>', page.text)
    codes = getattr(testcase, '_mfa_fixture_codes', {})
    if secret_match:
        code = pyotp.TOTP(secret_match.group(1)).now()
        with testcase.client.session_transaction() as session:
            nonce = session['mfa_challenge']
        from avenra.services.mfa_service import digest
        with closing(fixtures.db.connect()) as conn:
            uid = conn.execute('SELECT user_id FROM staff_mfa_challenges WHERE nonce_hash=?', (digest(nonce),)).fetchone()[0]
    else:
        with testcase.client.session_transaction() as session:
            nonce = session['mfa_challenge']
        from avenra.services.mfa_service import digest
        with closing(fixtures.db.connect()) as conn:
            row = conn.execute('SELECT m.* FROM staff_mfa m JOIN staff_mfa_challenges c ON c.user_id=m.user_id WHERE c.nonce_hash=?', (digest(nonce),)).fetchone()
        uid = row['user_id']
        with fixtures.avenra_app.app.app_context():
            secret = encryption().decrypt(row['encrypted_secret'].encode()).decode()
        totp = pyotp.TOTP(secret)
        code = totp.now() if int(__import__('time').time())//30 > row['last_counter'] else codes[uid].pop()
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text).group(1)
    response = testcase.client.post('/mfa', data={'code':code,'csrf_token':csrf},
        headers={'Origin':base_url} if base_url else {}, **options)
    testcase.assertIn(response.status_code, (200,302), 'Fictional fixture MFA failed')
    if secret_match:
        codes[uid] = re.findall(r'data-recovery-code>([a-f0-9]{32})</code>', response.text)
        testcase.assertEqual(len(codes[uid]), 10)
    testcase._mfa_fixture_codes = codes
    testcase.assertEqual(testcase.client.get('/api/session', **options).status_code, 200)
    return response
