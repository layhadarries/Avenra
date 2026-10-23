"""SafePath: Core Application Entry Point and API.

Refactored to Object-Oriented Architecture:
  Models:       safepath.models (User, Alert, Shelter, Referral, Consent, DiaryEntry, AuditEntry)
  Repositories: safepath.repositories (OOP SQLite data access layers)
  Services:     safepath.services (Business logic, authentication, dispatching)
  Controllers:  safepath.controllers (HTTP request handling and responses)
  Security:     safepath.security (Session validation, CSRF, route decorators)
  Application:  safepath.application (Application factory)
"""
import os
from safepath.application import SafePathApplication
from safepath.config import Config, BASE_DIR, SURVIVOR_DIR, UPLOADS_DIR
from safepath.repositories import AlertRepository, ConsentRepository, AuditRepository
from safepath.security import (
    current_user,
    device_user,
    login_required,
    require_role,
    wants_json,
    apply_security_headers,
    validate_json_body,
)
from safepath.services import (
    parse_coord,
    parse_client_ts,
    utc_now,
    AuthService,
)
import db

# Instantiate application following OOP factory pattern
safe_app_factory = SafePathApplication(Config)
app = safe_app_factory.create_app()

# Backward-compatibility exports for test suites and scripts
DEVICE_TOKEN = Config.DEVICE_TOKEN
DEMO_CASE_CODE = Config.DEMO_CASE_CODE
DEMO_LOGIN = Config.DEMO_LOGIN
ROLE_LABELS = Config.ROLE_LABELS
ALERT_ROLES = Config.ALERT_ROLES
COUNT_TABLES = Config.COUNT_TABLES
STAFF_SESSION_SECONDS = Config.STAFF_SESSION_SECONDS


def ensure_alert_columns():
    """Ensure required columns exist on alerts table."""
    AlertRepository.ensure_columns()


def is_consent_active(conn, user_id, item):
    """Check whether a consent item is currently active for a user."""
    repo = ConsentRepository(conn)
    return repo.is_active(user_id, item)


def audit(actor, action, case_code=None, detail=None):
    """Write one row to the audit log."""
    AuditRepository().log(actor, action, case_code, detail)


def table_counts():
    """Return dictionary of row counts for system tables."""
    return AuditRepository().table_counts()


def start_session(user_row):
    """Initiate a staff user session."""
    from safepath.models.user import User
    from flask import redirect, url_for
    user = User.from_row(user_row)
    dest = AuthService().start_session(user)
    return redirect(url_for(dest))


# The application factory initialises and migrates the database once.

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG") == "1" and app.config['APP_ENV'] == 'development'
    app.run(host="0.0.0.0", port=port, debug=debug)
