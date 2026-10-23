"""Security middleware, authentication helpers, and route guards."""
import hmac
from functools import wraps
from typing import Optional
from flask import request, redirect, url_for, jsonify, abort, g
from safepath.services.auth_service import AuthService
from safepath.repositories.user_repository import UserRepository
from safepath.models.user import User
from safepath.config import Config

_auth_service = AuthService()
_user_repo = UserRepository()


def current_user() -> Optional[User]:
    """Retrieve the validated User from current session or None."""
    return _auth_service.get_current_user()


def device_user() -> Optional[User]:
    """DEMO ONLY. Check the X-Device-Token header and return the seeded survivor,
    or None if the token is missing or wrong."""
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
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH"):
        if not isinstance(request.get_json(silent=True), dict) and request.content_length:
            return jsonify({"error": "json_object_required"}), 400
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify({"error": "cross_origin_write_forbidden"}), 403


def apply_security_headers(resp):
    """After-request hook to attach hardened HTTP security headers."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=()")
    if request.path.startswith((
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
        resp.headers["Cache-Control"] = "no-store"
    return resp
