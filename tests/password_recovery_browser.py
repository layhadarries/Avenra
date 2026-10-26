"""Browser recovery acceptance using a synthetic account/token; no SMTP/network providers."""
import hashlib
import secrets
import sqlite3
import time
from playwright.sync_api import expect
from werkzeug.security import generate_password_hash
from stage0_browser import main, complete_staff_mfa


def exercise(page,context,base,env):
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(('staff-password-reset-v1:'+token).encode()).hexdigest()
    with sqlite3.connect(env['DATABASE_PATH']) as conn:
        row=conn.execute("INSERT INTO users(name,role,email,org,is_active,auth_version,password_hash) VALUES('Recovery colleague','responder','recovery-browser@example.test','Test',1,1,?)",(generate_password_hash('Q7!Old-River-Cloud-29'),))
        conn.execute('INSERT INTO staff_invitations(user_id,token_hash,auth_version,expires_at) VALUES(?,?,1,?)',(row.lastrowid,digest,int(time.time())+900))
    private=context.browser.new_context()
    try:
        browser=private.new_page()
        browser.goto(base+'/login')
        browser.get_by_role('link',name='Forgot your password?').click()
        expect(browser.get_by_label('Work email')).to_be_visible()
        response=browser.goto(base+'/reset-password#'+token)
        assert 'no-store' in response.headers['cache-control']
        expect(browser.locator('#reset-token')).to_have_value(token)
        assert '#' not in browser.url
        browser.get_by_label('New password',exact=True).fill('weak')
        browser.get_by_label('New password',exact=True).fill('J9!New-River-Cloud-47')
        browser.get_by_label('Confirm password').fill('J9!New-River-Cloud-47')
        browser.get_by_role('button',name='Save password').click()
        browser.wait_for_url('**/login')
        browser.get_by_label('Work email').fill('recovery-browser@example.test')
        browser.get_by_label('Password',exact=True).fill('J9!New-River-Cloud-47')
        browser.get_by_role('button',name='Sign in',exact=True).click()
        complete_staff_mfa(browser,env,'recovery-browser@example.test')
        browser.wait_for_url('**/dashboard')
    finally:private.close()
    print('PASS: reset secret removed from URL, password reset and normal MFA login.')

if __name__=='__main__':main(exercise)
