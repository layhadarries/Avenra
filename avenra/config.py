"""Application configuration and constants."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVOR_DIR = os.path.join(BASE_DIR, "static", "survivor")
UPLOADS_DIR = os.environ.get('UPLOADS_DIR', os.path.join(BASE_DIR, 'uploads'))

class Config:
    """Encapsulates Flask and avenra configuration."""
    BASE_DIR = BASE_DIR
    SURVIVOR_DIR = SURVIVOR_DIR
    UPLOADS_DIR = UPLOADS_DIR

    SECRET_KEY = os.environ.get("SECRET_KEY")
    APP_ENV = os.environ.get('APP_ENV', 'development')
    EVALUATION_MODE = APP_ENV == 'evaluation'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get('COOKIE_SECURE', '1' if APP_ENV == 'production' else '0') == '1'
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024
    WTF_CSRF_CHECK_DEFAULT = False

    # Staff session timeout in seconds (15 minutes)
    STAFF_SESSION_SECONDS = 15 * 60

    # Demo settings
    DEMO_LOGIN = False
    DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "demo-device")
    DEMO_CASE_CODE = "SP-1042"

    ROLE_LABELS = {
        "responder": "Social worker",
        "shelter": "Shelter staff",
        "admin": "Admin",
    }

    ALERT_ROLES = ("responder", "admin")

    COUNT_TABLES = [
        "users", "contacts", "shelters", "alerts", "referrals",
        "diary_entries", "consents", "audit_log"
    ]

    CONSENT_CATALOG = {
        "location_sharing": {
            "label": "Share emergency alert location",
            "granted_to": (
                "Staff with access to your case; "
                "trusted contacts when SMS is enabled"
            ),
        },
        "diary_sharing": {
            "label": "Share selected diary entries and photo evidence",
            "granted_to": "Staff with access to your case",
        },
        "shelter_referral_sharing": {
            "label": "Share case code and placement needs for referrals",
            "granted_to": (
                "Staff handling your referral and the selected shelter"
            ),
        },
    }
