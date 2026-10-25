"""One-use staff pairing; opaque device credentials remain HttpOnly."""
import hashlib
import hmac
import click
import os
import secrets
import time
import sqlite3
from flask import request, jsonify, current_app, render_template
import db
from avenra.security import current_user, device_user, require_role

COOKIE = 'avenra_device'

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def rate_allowed(conn, bucket, maximum):
    """Persistent fixed window. Store only keyed IP digests, never raw addresses."""
    now = int(time.time())
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM device_pairing_attempts WHERE window_start<?', (now - 600,))
        conn.execute("INSERT INTO device_pairing_attempts(bucket,window_start,attempts) VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=device_pairing_attempts.attempts+1", (bucket, now))
        attempts = conn.execute('SELECT attempts FROM device_pairing_attempts WHERE bucket=?', (bucket,)).fetchone()['attempts']
    return attempts <= maximum


def register_devices(app):
    @app.get('/devices')
    @require_role('admin', 'responder')
    def devices_page():
        return render_template('devices.html')

    @app.cli.command('device-revoke')
    @click.option('--case-code', required=True)
    def revoke(case_code):
        """Revoke all device credentials for one exact case; retain its records."""
        conn = db.get_db()
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            owner = conn.execute("SELECT id FROM users WHERE case_code=? AND role='survivor'", (case_code,)).fetchone()
            if owner is None:
                raise click.ClickException('Case not found.')
            conn.execute('UPDATE survivor_devices SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',
                         (int(time.time()), owner['id']))
            conn.execute("INSERT INTO audit_log(actor,action,case_code,detail) VALUES('operator','device_revoked',?,'All case device credentials revoked')", (case_code,))
        click.echo('Device credentials revoked; case records retained.')

    @app.post('/api/device-invites')
    def device_invite():
        staff = current_user()
        if staff is None:
            return jsonify(error='sign_in_required'), 401
        if staff.role not in ('admin', 'responder'):
            return jsonify(error='forbidden'), 403
        conn = db.get_db()
        if not rate_allowed(conn, 'staff:' + str(staff.id), 10):
            return jsonify(error='too_many_attempts'), 429
        token = secrets.token_urlsafe(32)
        conn.execute('INSERT INTO device_enrollments(token_hash,staff_id,expires_at) VALUES(?,?,?)',
                     (digest(token), staff.id, int(time.time()) + 600))
        conn.execute("INSERT INTO audit_log(actor,action,detail) VALUES(?,'device_invitation_created','Ten minute individual pairing invitation')", ('user:' + str(staff.id),))
        conn.commit()
        origin = os.environ.get('PUBLIC_BASE_URL', request.host_url.rstrip('/')).rstrip('/')
        return jsonify(enrollment_url=origin + '/survivor/enroll.html#' + token, expires_in=600), 201

    @app.post('/api/device/enroll')
    def device_enroll():
        if request.headers.get('Origin') != os.environ.get('PUBLIC_BASE_URL', request.host_url.rstrip('/')).rstrip('/'):
            return jsonify(error='cross_origin_write_forbidden'), 403
        conn = db.get_db()
        bucket = hmac.new(current_app.secret_key.encode(),
                          (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
        if not rate_allowed(conn, 'device:' + bucket, 20):
            return jsonify(error='too_many_attempts'), 429
        if request.cookies.get(COOKIE):
            return jsonify(error='device_already_paired'), 409
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'token'}:
            return jsonify(error='invalid_invitation'), 400
        token = data.get('token')
        if not isinstance(token, str) or not 30 <= len(token) <= 128:
            return jsonify(error='invalid_invitation'), 400
        conn = db.get_db()
        now = int(time.time())
        try:
            conn.execute('BEGIN IMMEDIATE')
            invite = conn.execute("SELECT d.staff_id FROM device_enrollments d JOIN users u ON u.id=d.staff_id WHERE d.token_hash=? AND d.expires_at>? AND d.consumed_at IS NULL AND u.is_active=1 AND u.role IN ('admin','responder')", (digest(token), now)).fetchone()
            if invite is None:
                conn.rollback()
                return jsonify(error='invalid_invitation'), 400
            case = 'AV-' + secrets.token_hex(8).upper()
            conn.execute("INSERT INTO users(name,role,email,case_code,is_active) VALUES(?,'survivor',?,?,1)",
                         ('Private account', secrets.token_hex(24) + '@device.invalid', case))
            owner = conn.execute('SELECT id FROM users WHERE case_code=?', (case,)).fetchone()['id']
            conn.execute('INSERT INTO case_access(staff_id,survivor_id) VALUES(?,?)', (invite['staff_id'], owner))
            credential = secrets.token_urlsafe(32)
            conn.execute('INSERT INTO survivor_devices(token_hash,user_id,expires_at) VALUES(?,?,?)',
                         (digest(credential), owner, now + 2592000))
            conn.execute('UPDATE device_enrollments SET consumed_at=? WHERE token_hash=?', (now, digest(token)))
            conn.execute("INSERT INTO audit_log(actor,action,case_code,detail) VALUES(?,'device_enrolled',?,'Individual device paired')", ('user:' + str(invite['staff_id']), case))
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            return jsonify(error='pairing_unavailable'), 503
        response = jsonify(paired=True)
        response.status_code = 201
        response.set_cookie(COOKIE, credential, max_age=2592000, httponly=True,
                            secure=current_app.config['SESSION_COOKIE_SECURE'], samesite='Strict', path='/')
        return response

    @app.get('/api/device')
    def device_status():
        owner = device_user()
        if owner is None:
            return jsonify(error='device_pairing_required'), 401
        return jsonify(paired=True, account_id=owner.id)
