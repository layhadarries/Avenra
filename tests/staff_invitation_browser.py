"""Real browser invitation acceptance; synthetic accounts and no email delivery."""
import hashlib
import secrets
import sqlite3
import time
from playwright.sync_api import expect
from stage0_browser import main, complete_staff_mfa


def exercise(page, context, base, env):
    token = secrets.token_urlsafe(32)
    with sqlite3.connect(env['DATABASE_PATH']) as conn:
        cur = conn.execute("INSERT INTO users(name,role,email,org,is_active,auth_version) VALUES('Invited browser colleague','responder','browser-invite@example.test','Test organisation',0,1)")
        conn.execute('INSERT INTO staff_invitations(user_id,token_hash,auth_version,expires_at) VALUES(?,?,1,?)',
                     (cur.lastrowid,hashlib.sha256(token.encode()).hexdigest(),int(time.time())+3600))
        conn.commit()
    invited_context = context.browser.new_context()
    try:
        invited = invited_context.new_page()
        errors=[]
        invited.on('pageerror',lambda error:errors.append(str(error)))
        response=invited.goto(base+'/activate#'+token)
        assert response.status == 200
        expect(invited.locator('#invite-token')).to_have_value(token)
        assert '#' not in invited.url
        invited.get_by_label('Create password',exact=True).fill('Q7!fern-River-Cloud-29')
        invited.get_by_label('Confirm password',exact=True).fill('Q7!fern-River-Cloud-29')
        invited.get_by_role('button',name='Activate account',exact=True).click()
        complete_staff_mfa(invited,env,'browser-invite@example.test')
        invited.wait_for_url('**/dashboard')
        expect(invited.locator('.topbar-user')).to_contain_text('Invited browser colleague')
        invited.get_by_role('button',name='Sign out everywhere').click()
        invited.wait_for_url('**/login')
        invited.get_by_label('Work email').fill('browser-invite@example.test')
        invited.get_by_label('Password',exact=True).fill('Q7!fern-River-Cloud-29')
        invited.get_by_role('button',name='Sign in',exact=True).click()
        complete_staff_mfa(invited,env,'browser-invite@example.test')
        invited.wait_for_url('**/dashboard')
        assert not errors, errors
    finally:
        invited_context.close()
    print('PASS: invitation fragment is cleared, password setup signs in, and normal login works.')

if __name__=='__main__':
    main(exercise)
