"""Public invitation acceptance and operator-only provisioning CLI."""
import hashlib
import hmac
import os
import sqlite3
import time
import click
from flask import Blueprint, current_app, render_template, request, redirect, url_for, session
import db
from avenra.services.staff_invitation_service import activate, issue_invitation
from avenra.services.staff_email import send_staff_email
from avenra.services.auth_service import AuthService
from avenra.repositories.user_repository import UserRepository


def register_staff_invitations(app):
    bp = Blueprint('staff_invitation', __name__)

    @bp.route('/activate', methods=['GET','POST'])
    def accept():
        error = None
        status = 200
        if request.method == 'POST':
            conn = db.get_db()
            bucket = hmac.new(current_app.secret_key.encode(), (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
            now = int(time.time())
            with conn:
                conn.execute('DELETE FROM staff_activation_attempts WHERE window_start<?', (now-900,))
                conn.execute('INSERT INTO staff_activation_attempts(bucket,window_start,attempts) VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=staff_activation_attempts.attempts+1', (bucket,now))
                attempts = conn.execute('SELECT attempts FROM staff_activation_attempts WHERE bucket=?',(bucket,)).fetchone()[0]
            if attempts > 20:
                return render_template('activate.html', error='Too many attempts. Please wait 15 minutes.'), 429
            try:
                uid, error = activate(conn, request.form.get('token',''), request.form.get('password',''), request.form.get('confirm_password',''))
            except sqlite3.Error:
                uid, error, status = None, 'Activation is temporarily unavailable. Please try again.', 503
            if uid:
                user = UserRepository().get_by_id(uid)
                destination = AuthService().start_session(user)
                return redirect(url_for(destination))
            status = status if status == 503 else 400
        return render_template('activate.html',error=error), status

    app.register_blueprint(bp)

    @app.cli.command('staff-invite')
    @click.option('--email', required=True)
    @click.option('--name', required=True)
    @click.option('--role', type=click.Choice(['admin','responder','shelter']), required=True)
    @click.option('--org', required=True)
    @click.option('--case-code', multiple=True, help='Explicit assigned case; repeat for additional cases.')
    @click.option('--shelter-id', type=int)
    def invite(email,name,role,org,case_code,shelter_id):
        """Create inactive staff and send a one-use password setup invitation."""
        try:
            uid = issue_invitation(db.get_db(),email=email,name=name,role=role,org=org,
                case_codes=case_code,shelter_id=shelter_id,
                base_url=os.environ.get('PUBLIC_BASE_URL',''),sender=send_staff_email)
        except (ValueError,RuntimeError) as error:
            raise click.ClickException(str(error)) from None
        except sqlite3.Error:
            raise click.ClickException('Account provisioning failed. Check role and access configuration.') from None
        click.echo(f'Invitation submitted to the email server for staff account {uid}. Delivery is not yet confirmed.')

    @app.cli.command("staff-setup")
    def setup_staff():
        """Interactively provision staff and send a one-use activation link."""
        role = click.prompt(
            "Account type",
            type=click.Choice(["admin", "responder", "shelter"], case_sensitive=False),
        ).lower()
        email = click.prompt("Email address").strip()
        name = click.prompt("Full name").strip()
        org = click.prompt("Organisation").strip()

        case_codes = ()
        shelter_id = None
        if role == "responder":
            raw = click.prompt(
                "Assigned case codes (comma-separated; blank for none)",
                default="",
                show_default=False,
            )
            case_codes = tuple(code.strip() for code in raw.split(",") if code.strip())
        elif role == "shelter":
            shelter_id = click.prompt(
                "Existing shelter ID",
                type=click.IntRange(min=1),
            )

        if not click.confirm(
            f"Send a one-use activation invitation to {email} as {role}?",
            default=False,
        ):
            click.echo("Cancelled; no account or invitation was created.")
            return

        click.get_current_context().invoke(
            invite,
            email=email,
            name=name,
            role=role,
            org=org,
            case_code=case_codes,
            shelter_id=shelter_id,
        )

    @app.cli.command('staff-disable')
    @click.option('--email', required=True)
    def disable(email):
        """Disable a staff account, revoke invitations and invalidate all sessions."""
        conn=db.get_db()
        with conn:
            row=conn.execute("SELECT id FROM users WHERE lower(email)=? AND role IN ('admin','responder','shelter')",(email.strip().lower(),)).fetchone()
            if row is None:
                raise click.ClickException('Staff account not found')
            conn.execute('UPDATE users SET is_active=0,auth_version=auth_version+1 WHERE id=?',(row['id'],))
            conn.execute('UPDATE staff_invitations SET revoked_at=? WHERE user_id=? AND used_at IS NULL',(int(time.time()),row['id']))
            conn.execute("INSERT INTO audit_log(actor,action,detail) VALUES('developer-cli','staff_disabled',?)",(f"user {row['id']}",))
        click.echo('Staff account disabled; sessions and pending invitations invalidated.')
