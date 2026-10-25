"""Authentication and session management service."""
import time
from typing import Optional, Tuple
from flask import session, g, redirect, url_for, flash, render_template
from avenra.repositories.user_repository import UserRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.config import Config
from werkzeug.security import check_password_hash, generate_password_hash
import secrets

_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


class AuthService:
    """Encapsulates authentication, session lifecycle, and credential verification."""

    def __init__(
        self,
        user_repo: Optional[UserRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
        session_timeout: int = Config.STAFF_SESSION_SECONDS,
    ):
        self.user_repo = user_repo or UserRepository()
        self.audit_repo = audit_repo or AuditRepository()
        self.session_timeout = session_timeout

    def authenticate(self, email: str, password: str) -> Optional[User]:
        if not isinstance(email, str) or not isinstance(password, str) or len(email)>254 or len(password)>128:
            return None
        user = self.user_repo.get_by_email(email)
        valid = user.verify_password(password) if user and user.password_hash else check_password_hash(_DUMMY_PASSWORD_HASH, password)
        if user and user.can_sign_in() and valid:
            return user
        self.audit_repo.log("anonymous", "login_failed", detail='Credentials rejected')
        return None

    def start_session(self, user: User, *, mfa_verified=False) -> str:
        """Initialize a new authenticated session for a staff user. Returns redirect URL."""
        if not user.is_active or not user.password_hash or not mfa_verified:
            raise PermissionError("Account inactive or cannot sign in")

        session.clear()
        self.audit_repo.log(f'user:{user.id}', "login", detail=user.role)
        session["user_id"] = user.id
        session["auth_version"] = user.auth_version
        session["issued_at"] = int(time.time())
        session['mfa_verified'] = True
        g.pop("user", None)

        destination = "shelters_page" if user.role == "shelter" else "dashboard"
        return destination

    def logout(self, user: Optional[User]) -> None:
        """Invalidate session and increment auth_version to invalidate concurrent sessions."""
        if user is not None:
            self.user_repo.increment_auth_version(user.id)
            self.audit_repo.log(
                f"user:{user.id}",
                "logout_all_sesions",
                detail="Staff signed out",
            )
        session.clear()
        g.user = None

    def get_current_user(self) -> Optional[User]:
        """Validate the active session and return the current User entity, or None."""
        if "user" in g and g.user is not None:
            return g.user

        uid = session.get("user_id")
        version = session.get("auth_version")
        issued_at = session.get("issued_at")

        # A password-bound MFA challenge is still anonymous. Template context
        # inspection must not destroy it (or treat it as a staff session).
        if uid is None and isinstance(session.get('mfa_challenge'), str):
            g.user = None
            return None

        if (
            type(uid) is not int
            or type(version) is not int
            or type(issued_at) is not int
            or session.get('mfa_verified') is not True
        ):
            session.clear()
            g.user = None
            return None

        age = time.time() - issued_at
        if not 0 <= age < self.session_timeout:
            session.clear()
            g.user = None
            return None

        user = self.user_repo.get_active_staff(uid, version)
        if user is None:
            session.clear()
            g.user = None
            return None

        g.user = user
        return g.user
