"""Single-use password reset; MFA enrollment and case permissions are preserved."""
import hashlib
import re
import secrets
import time
from urllib.parse import urlsplit
from werkzeug.security import generate_password_hash
from avenra.services.staff_invitation_service import password_error


class PasswordRecoveryService:
    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def digest(token):
        # Domain separation prevents a reset token activating an invitation and vice versa.
        return hashlib.sha256(('staff-password-reset-v1:' + token).encode('ascii')).hexdigest()

    def request(self, email, origin, sender):
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Configure PUBLIC_BASE_URL as an HTTPS origin')
        secret = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            user = self.conn.execute("SELECT id,auth_version FROM users WHERE lower(email)=? AND is_active=1 AND password_hash IS NOT NULL AND role IN ('admin','responder','shelter')", (email.strip().lower(),)).fetchone()
            if user is None:
                return
            self.conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE user_id=? AND used_at IS NULL AND revoked_at IS NULL', (now,user['id']))
            self.conn.execute('INSERT INTO staff_invitations(user_id,token_hash,auth_version,expires_at) VALUES(?,?,?,?)', (user['id'],self.digest(secret),user['auth_version'],now+900))
        try:
            sender(email, 'Reset your Avenra password', 'A password reset was requested for your staff account.\n\n'+origin.rstrip('/')+'/reset-password#'+secret+'\n\nThis link expires in 15 minutes and works once. Your authenticator MFA remains required. If you did not request this, ignore this email.')
        except Exception:
            with self.conn:
                self.conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE token_hash=?', (int(time.time()),self.digest(secret)))
            raise RuntimeError('Password reset email unavailable') from None

    def reset(self, token, password, confirmation):
        error = password_error(password, confirmation)
        if error:
            return error
        invalid = 'This reset link is invalid or expired. Ask for a new link.'
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
            return invalid
        hashed = generate_password_hash(password)
        now = int(time.time())
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.conn.execute("SELECT i.id,i.user_id FROM staff_invitations i JOIN users u ON u.id=i.user_id WHERE i.token_hash=? AND i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>? AND i.auth_version=u.auth_version AND u.is_active=1 AND u.role IN ('admin','responder','shelter')", (self.digest(token),now)).fetchone()
            if row is None:
                return invalid
            self.conn.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?', (hashed,row['user_id']))
            self.conn.execute('UPDATE staff_invitations SET used_at=? WHERE id=?', (now,row['id']))
            self.conn.execute("INSERT INTO audit_log(actor,action,detail) VALUES(?,'staff_password_reset','Existing sessions revoked; MFA retained')", ('user:'+str(row['user_id']),))
        return None
