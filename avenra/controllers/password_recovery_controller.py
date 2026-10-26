"""Generic public recovery responses; session CSRF and origin checks remain required."""
import os
import sqlite3
from flask import request, render_template, redirect, url_for, session, current_app
import db
from avenra.services.abuse_service import AbuseService
from avenra.services.password_recovery_service import PasswordRecoveryService
from avenra.services.staff_email import send_staff_email


def register_password_recovery(app):
    @app.route('/forgot-password', methods=['GET','POST'])
    def forgot_password():
        message = None
        if request.method == 'POST':
            email = request.form.get('email','').strip().lower()
            abuse = AbuseService(db.get_db())
            if not abuse.allow('password-reset',email,3):
                return render_template('password_recovery.html',reset=False,error='Too many attempts. Please wait 15 minutes.'),429
            try:
                if 3 <= len(email) <= 254:
                    PasswordRecoveryService(db.get_db()).request(email,os.environ.get('PUBLIC_BASE_URL',''),send_staff_email)
            except (sqlite3.Error,RuntimeError,ValueError):
                db.get_db().rollback()
                current_app.logger.warning('Password recovery request could not complete')
            message = 'If an eligible account exists, we have sent a password reset link. Check your spam folder too.'
        return render_template('password_recovery.html',reset=False,message=message)

    @app.route('/reset-password', methods=['GET','POST'])
    def reset_password():
        error = None
        if request.method == 'POST':
            if not AbuseService(db.get_db()).allow_public('password-reset-consume',10):
                return render_template('password_recovery.html',reset=True,error='Too many attempts. Please wait 15 minutes.'),429
            try:
                error = PasswordRecoveryService(db.get_db()).reset(request.form.get('token'),request.form.get('password'),request.form.get('confirm_password'))
            except sqlite3.Error:
                db.get_db().rollback()
                error = 'Password reset temporarily unavailable. Please try again.'
            if error is None:
                session.clear()
                return redirect(url_for('login'))
        return render_template('password_recovery.html',reset=True,error=error),400 if error else 200
