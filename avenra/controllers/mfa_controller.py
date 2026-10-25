"""Private staff MFA views; services own credential and transaction policy."""
import sqlite3
import click
from cryptography.fernet import InvalidToken
from flask import request, render_template, redirect, url_for, session
import db
from avenra.services.mfa_service import MFAService
from avenra.services.auth_service import AuthService
from avenra.security import current_user


def register_mfa(app):
    @app.route('/mfa', methods=['GET', 'POST'])
    def staff_mfa():
        user = current_user()
        if user is not None:
            return redirect(url_for('shelters_page' if user.role == 'shelter' else 'dashboard'))
        service = MFAService(db.get_db())
        nonce = session.get('mfa_challenge')
        try:
            view = service.view(nonce)
            if view is None:
                session.clear()
                return redirect(url_for('login'))
            error, status = None, 200
            if request.method == 'POST':
                user, codes, status = service.verify(nonce, request.form.get('code'))
                if user is not None:
                    destination = AuthService().start_session(user, mfa_verified=True)
                    if codes:
                        return render_template('mfa_recovery.html', codes=codes, destination=destination)
                    return redirect(url_for(destination))
                error = 'Verification failed. Check your code and try again.' if status != 429 else 'Too many attempts. Please wait 15 minutes.'
            return render_template('mfa.html', error=error, **view), status
        except (sqlite3.Error, RuntimeError, InvalidToken):
            return render_template('mfa.html', error='Verification temporarily unavailable.', enrolling=False, secret=None), 503

    @app.cli.command('staff-mfa-reset')
    @click.option('--email', required=True)
    @click.option('--verification-reference', required=True)
    @click.option('--confirm', is_flag=True, help='Confirm independent identity verification is complete.')
    def reset(email, verification_reference, confirm):
        """Operator-only recovery after independent identity verification; no public reset endpoint."""
        if not confirm:
            raise click.ClickException('Independent identity verification and --confirm are required.')
        try:
            MFAService(db.get_db()).reset(email, verification_reference)
        except ValueError as error:
            raise click.ClickException(str(error)) from None
        except sqlite3.Error:
            raise click.ClickException('MFA reset unavailable; no success confirmed.') from None
        click.echo('MFA reset recorded; sessions invalidated. Password and new MFA enrollment are required.')
