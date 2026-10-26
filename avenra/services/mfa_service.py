"""Password-bound enrollment, one-use RFC 6238 verification and recovery codes."""
import base64
import hashlib
import os
import re
import secrets
import time
import pyotp
import qrcode
from qrcode.image.svg import SvgPathFillImage
from cryptography.fernet import Fernet
from flask import current_app
from avenra.models.user import User
from avenra.repositories.mfa_repository import MFARepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.services.abuse_service import AbuseService


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encryption():
    key = os.environ.get('STAFF_MFA_ENCRYPTION_KEY')
    if key and key == current_app.secret_key:
        raise RuntimeError('MFA encryption and session keys must be separate')
    if not key:
        if current_app.config['APP_ENV'] == 'production' or os.environ.get('VERCEL') or os.environ.get('DATABASE_URL'):
            raise RuntimeError('Staff MFA encryption key required')
        # Development only; operational key custody must be separate from DB backups.
        key = base64.urlsafe_b64encode(hashlib.sha256(('dev-mfa:'+current_app.secret_key).encode()).digest())
    return Fernet(key)


class MFAService:
    def __init__(self, conn):
        self.conn = conn
        self.repo = MFARepository(conn)

    def begin(self, user):
        nonce = secrets.token_urlsafe(32)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            self.repo.begin(user.id, user.auth_version, digest(nonce), int(time.time()))
        return nonce

    def pending(self, nonce):
        if not isinstance(nonce, str) or len(nonce) != 43:
            return None
        return User.from_row(self.repo.challenge(digest(nonce), int(time.time())))

    def view(self, nonce):
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            user = self.pending(nonce)
            if user is None:
                return None
            now = int(time.time())
            row = self.repo.credential(user.id)
            if row is None or (row['confirmed_at'] is None and row['enrollment_expires_at'] <= now):
                self.repo.prepare(user.id, encryption().encrypt(pyotp.random_base32().encode()).decode(), now)
                row = self.repo.credential(user.id)
            secret = encryption().decrypt(row['encrypted_secret'].encode()).decode() if row['confirmed_at'] is None else None
        # Generate locally, in memory, after the persistence transaction. SVG
        # contains geometry only; no secret-bearing URL, cache or remote request.
        qr_svg = None
        if secret:
            uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name='Avenra')
            qr_svg = qrcode.make(uri, image_factory=SvgPathFillImage, border=4).to_string(encoding='unicode')
        return {'enrolling': secret is not None, 'secret': secret, 'qr_svg': qr_svg}

    def verify(self, nonce, raw_code):
        user = self.pending(nonce)
        if user is None:
            return None, [], 401
        if not AbuseService(self.conn).allow('mfa', str(user.id), 8):
            return None, [], 429
        code = raw_code.strip() if isinstance(raw_code, str) and len(raw_code) <= 128 else ''
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            user = self.pending(nonce)
            if user is None:
                return None, [], 401
            row = self.repo.credential(user.id)
            now = int(time.time())
            if row is None or (row['confirmed_at'] is None and row['enrollment_expires_at'] <= now):
                return None, [], 401
            enrolling = row['confirmed_at'] is None
            valid = False
            if re.fullmatch(r'[0-9]{6}', code):
                secret = encryption().decrypt(row['encrypted_secret'].encode()).decode()
                totp = pyotp.TOTP(secret)
                for counter in range(now//30-1, now//30+2):
                    if counter > row['last_counter'] and secrets.compare_digest(totp.at(counter*30), code):
                        valid = self.repo.advance_counter(user.id, counter, now)
                        break
            elif not enrolling and re.fullmatch(r'[a-f0-9]{32}', code):
                valid = self.repo.consume_recovery(user.id, digest(code), now)
            if not valid:
                AuditRepository(self.conn).log(f'user:{user.id}', 'staff_mfa_failed', commit=False)
                return None, [], 401
            if not self.repo.consume_challenge(digest(nonce)):
                raise RuntimeError('MFA challenge already consumed')
            codes = [secrets.token_hex(16) for _ in range(10)] if enrolling else []
            if enrolling:
                self.repo.replace_recovery(user.id, [digest(code) for code in codes])
                self.conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (user.id,))
                user.auth_version += 1
            AuditRepository(self.conn).log(f'user:{user.id}', 'staff_mfa_enrolled' if enrolling else 'staff_mfa_verified', commit=False)
            return user, codes, 200

    def reset(self, email, reference):
        if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,120}', reference):
            raise ValueError('A verified recovery ticket reference is required')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.conn.execute("SELECT id FROM users WHERE lower(email)=? AND role IN ('admin','responder','shelter')", (email.strip().lower(),)).fetchone()
            if row is None:
                raise ValueError('Staff account not found')
            self.repo.reset(row['id'])
            self.conn.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (row['id'],))
            AuditRepository(self.conn).log('operator', 'staff_mfa_reset', detail=f"user {row['id']}; verification {reference.strip()}", commit=False)
