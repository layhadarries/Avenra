"""Authentication controller."""
from typing import Optional
from flask import request, render_template, render_template_string, redirect, url_for, flash, jsonify, session, current_app, abort
from safepath.services.auth_service import AuthService
from safepath.security import current_user
from safepath.config import Config
from safepath.repositories.portal_repository import PortalRepository


class AuthController:
    """Handles staff authentication and sign-out workflows."""

    def __init__(self, auth_service: Optional[AuthService] = None):
        self.auth_service = auth_service or AuthService()

    def staff_session(self):
        user = current_user()
        if user is None:
            return jsonify({"error": "sign_in_required"}), 401
        return jsonify({"user_id": user.id, "role": user.role,
                        "access_signature": PortalRepository().access_signature(user),
                        "expires_at": session["issued_at"] + Config.STAFF_SESSION_SECONDS})

    def login(self):
        if request.method == "POST":
            if request.form.get('quick_role'):
                return self.evaluation_login(request.form['quick_role'])
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = self.auth_service.authenticate(email, password)
            if user:
                dest = self.auth_service.start_session(user)
                return redirect(url_for(dest))

            flash("That email and password don't match. Check them and try again.")
            return render_template("login.html", demo_login=Config.DEMO_LOGIN), 401

        if current_user():
            return redirect(url_for("dashboard"))
        return render_template("login.html", demo_login=Config.DEMO_LOGIN)

    def logout(self):
        user = current_user()
        self.auth_service.logout(user)
        return redirect(url_for("login"))

    def _require_evaluation(self):
        if not current_app.config.get('EVALUATION_MODE'):
            abort(404)
        import seed
        if not seed.is_evaluation_database():
            abort(403)

    def evaluation_page(self):
        self._require_evaluation()
        return render_template_string('''<!doctype html><html lang="en"><head>
          <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
          <title>Avenra evaluation</title>
          <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
          </head><body><div class="login-wrap"><main class="card login-card">
          <h1>Avenra evaluation</h1><p>Fictional data only. No emergency response or real notification delivery.</p>
          {% for role,label in [('responder','Social worker'),('shelter','Shelter staff')] %}
          <form method="post" action="{{ url_for('evaluation_login', role=role) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <button type="submit" class="btn">Sign in as {{ label }}</button></form>
          {% endfor %}<a href="{{ url_for('login') }}">Password sign-in</a>
          </main></div></body></html>''')

    def evaluation_login(self, role):
        self._require_evaluation()
        if role not in {'responder', 'shelter'}:
            abort(404)
        email = {'responder': 'nomsa@safepath.demo', 'shelter': 'pieter@safepath.demo'}[role]
        user = self.auth_service.user_repo.get_by_email(email)
        if user is None or not user.can_sign_in() or user.role != role:
            abort(403)
        destination = self.auth_service.start_session(user)
        self.auth_service.audit_repo.log(f'user:{user.id}', 'evaluation_login', detail=role)
        return redirect(url_for(destination))
