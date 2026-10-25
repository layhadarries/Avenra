"""Security middleware, authentication helpers, and route guards."""
import hmac
import os
import time
import hashlib
import db
from functools import wraps
from typing import Optional
from flask import request, redirect, url_for, jsonify, abort, g
from avenra.services.auth_service import AuthService
from avenra.repositories.user_repository import UserRepository
from avenra.models.user import User
from avenra.config import Config

_auth_service = AuthService()
_user_repo = UserRepository()


def current_user() -> Optional[User]:
    """Retrieve the validated User from current session or None."""
    return _auth_service.get_current_user()


def device_user() -> Optional[User]:
    """DEMO ONLY. Check the X-Device-Token header and return the seeded survivor,
    or None if the token is missing or wrong."""
    cookie = request.cookies.get('avenra_device')
    if cookie:
        if len(cookie) > 128:
            return None
        row = db.get_db().execute(
            "SELECT user_id FROM survivor_devices WHERE token_hash=? AND expires_at>? AND revoked_at IS NULL",
            (hashlib.sha256(cookie.encode()).hexdigest(), int(time.time())),
        ).fetchone()
        if row is None:
            return None
        owner = _user_repo.get_by_id(row['user_id'])
        return owner if owner and owner.is_active and owner.role == 'survivor' else None
    if Config.APP_ENV == 'production' or os.environ.get('VERCEL') or os.environ.get('DATABASE_URL'):
        return None
    token = request.headers.get("X-Device-Token", "")
    if not token or not hmac.compare_digest(token.encode(), Config.DEVICE_TOKEN.encode()):
        return None
    return _user_repo.get_survivor_by_case(Config.DEMO_CASE_CODE)


def wants_json() -> bool:
    return request.path.startswith("/api/")


def login_required(view):
    """Staff route guard: redirect unauthenticated users to login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login" if "auth.login" in request.url_rule.rule else "login"))
        return view(*args, **kwargs)
    return wrapped


def require_role(*roles):
    """Role-based authorization decorator.
    Unauthenticated -> 401 (API) or redirect to login (pages).
    Wrong role -> 403."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                if wants_json():
                    return jsonify({"error": "sign_in_required"}), 401
                return redirect(url_for("login"))
            if user.role not in roles:
                if wants_json():
                    return jsonify({"error": "forbidden"}), 403
                abort(403)
            # The route's staff authority determines CSRF protection. A supplied
            # device header must never exempt a cookie-authenticated staff write.
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                from flask import current_app
                current_app.extensions["csrf"].protect()
            return view(*args, **kwargs)
        return wrapped
    return decorator


def validate_json_body():
    """Request validator for JSON API endpoints."""
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        is_diary_multipart = (
            request.path == "/api/diary"
            and request.method == "POST"
            and request.mimetype == "multipart/form-data"
        )
        if not is_diary_multipart and not isinstance(request.get_json(silent=True), dict) and request.content_length:
            return jsonify({"error": "json_object_required"}), 400
        origin = request.headers.get("Origin")
        if (origin or request.cookies.get("avenra_device")) and origin != os.environ.get("PUBLIC_BASE_URL", request.host_url.rstrip("/")).rstrip("/"):
            return jsonify({"error": "cross_origin_write_forbidden"}), 403


def apply_security_headers(resp):
    """After-request hook to attach hardened HTTP security headers."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=()")
    if request.path.startswith((
        "/survivor/enroll.html",
        "/devices",
        "/activate",
        "/api/",
        "/cases",
        "/dashboard",
        "/referrals",
        "/audit-log",
        "/shelters",
        "/login",
        "/logout",
        "/evaluation",
    )):
        resp.headers["Cache-Control"] = "private, no-store"
    return resp
