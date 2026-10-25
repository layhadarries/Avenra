"""One-time staff enrollment. Raw invitation secrets are never persisted or logged."""
import hashlib
import re
import secrets
import time
from urllib.parse import urlsplit
from werkzeug.security import generate_password_hash
from zxcvbn import zxcvbn

SCHEMA = '''CREATE TABLE IF NOT EXISTS staff_invitations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 token_hash TEXT NOT NULL UNIQUE,
 auth_version INTEGER NOT NULL,
 expires_at INTEGER NOT NULL,
 used_at INTEGER,
 revoked_at INTEGER
)'''


def token_digest(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def password_error(password, confirmation):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        return 'Use between 15 and 128 characters for your password.'
    if password != confirmation:
        return 'The passwords do not match.'
    if zxcvbn(password)['score'] < 3:
        return 'Choose a less predictable password or a longer passphrase.'
    return None


def issue_invitation(conn, *, email, name, role, org, base_url, sender,
                     case_codes=(), shelter_id=None):
    parsed = urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('PUBLIC_BASE_URL must be an HTTPS origin')
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
        raise ValueError('A valid email address is required')
    if role not in ('admin', 'responder', 'shelter') or not name.strip() or len(name) > 120 or not org.strip() or len(org) > 160:
        raise ValueError('Valid staff role, name and organisation are required')
    if (role == 'shelter') != (shelter_id is not None) or (role == 'shelter' and case_codes):
        raise ValueError('Shelter staff require one shelter and cannot receive private case access')
    secret = secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute('BEGIN IMMEDIATE')
    try:
        existing = conn.execute('SELECT * FROM users WHERE lower(email)=?', (email,)).fetchone()
        if existing is not None:
            if existing['is_active'] or existing['password_hash']:
                raise ValueError('Account already configured; invitations cannot reset existing credentials')
            if (existing['role'], existing['name'], existing['org'], existing['shelter_id']) != (role, name.strip(), org.strip(), shelter_id):
                raise ValueError('Existing account details differ; review access before resending')
            user_id = existing['id']
            version = existing['auth_version']
        else:
            cur = conn.execute('INSERT INTO users(name,role,email,org,shelter_id,is_active,auth_version) VALUES(?,?,?,?,?,0,1)',
                               (name.strip(), role, email, org.strip(), shelter_id))
            user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
            version = 1
        if shelter_id is not None and conn.execute('SELECT id FROM shelters WHERE id=?',(shelter_id,)).fetchone() is None:
            raise ValueError('Unknown shelter')
        for code in case_codes:
            owner = conn.execute("SELECT id FROM users WHERE case_code=? AND role='survivor'", (code,)).fetchone()
            if owner is None:
                raise ValueError('Unknown case code')
            conn.execute('INSERT OR IGNORE INTO case_access(staff_id,survivor_id) VALUES(?,?)', (user_id,owner['id']))
        conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE user_id=? AND used_at IS NULL AND revoked_at IS NULL', (now,user_id))
        cur = conn.execute('INSERT INTO staff_invitations(user_id,token_hash,auth_version,expires_at) VALUES(?,?,?,?)',
                           (user_id,token_digest(secret),version,now+86400))
        invitation_id = conn.execute("SELECT id FROM staff_invitations WHERE token_hash=?", (token_digest(secret),)).fetchone()["id"]
        conn.execute("INSERT INTO audit_log(actor,action,detail) VALUES('developer-cli','staff_invited',?)", (f'user {user_id}; role {role}',))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    link = base_url.rstrip('/') + '/activate#' + secret
    body = ('Welcome to Avenra.\n\nYour organisation has invited you to its staff workspace.\n'
            'Create your password and activate your account using this link:\n\n' + link +
            '\n\nThis invitation expires in 24 hours and works once. '
            'If you were not expecting it, do not activate it; contact your organisation.\n')
    try:
        sender(email, 'Welcome to Avenra — activate your account', body)
    except Exception:
        with conn:
            conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE id=?', (int(time.time()),invitation_id))
        raise RuntimeError('Email delivery could not be confirmed. Invitation revoked; resend after checking email settings.') from None
    return user_id


def activate(conn, token, password, confirmation):
    error = password_error(password, confirmation)
    if error:
        return None, error
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None, 'This invitation is invalid or expired. Ask for a new invitation.'
    hashed = generate_password_hash(password)
    now = int(time.time())
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('''SELECT i.id invitation_id,i.user_id FROM staff_invitations i
          JOIN users u ON u.id=i.user_id WHERE i.token_hash=? AND i.used_at IS NULL
          AND i.revoked_at IS NULL AND i.expires_at>? AND u.is_active=0
          AND u.password_hash IS NULL AND u.auth_version=i.auth_version
          AND u.role IN ('admin','responder','shelter')''', (token_digest(token),now)).fetchone()
        if row is None:
            conn.rollback()
            return None, 'This invitation is invalid or expired. Ask for a new invitation.'
        conn.execute('UPDATE users SET password_hash=?,is_active=1,auth_version=auth_version+1 WHERE id=?', (hashed,row['user_id']))
        conn.execute('UPDATE staff_invitations SET used_at=? WHERE id=?', (now,row['invitation_id']))
        conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE user_id=? AND used_at IS NULL', (now,row['user_id']))
        conn.execute("INSERT INTO audit_log(actor,action,detail) VALUES(?,'staff_activated','Invitation accepted')", (f"user:{row['user_id']}",))
        conn.commit()
        return row['user_id'], None
    except Exception:
        conn.rollback()
        raise
