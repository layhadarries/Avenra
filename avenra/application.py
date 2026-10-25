"""avenra Application Factory and Lifecycle Orchestration."""
import os
from flask import Flask, jsonify, request, session
from flask_wtf.csrf import CSRFProtect, CSRFError
import db
from avenra.config import Config, BASE_DIR
from avenra.security import current_user,apply_security_headers,validate_json_body
from avenra.controllers import AuthController, PagesController,AlertsController,ContactsController,SheltersController,ReferralsController,ConsentsController,DiaryController,AuditController,SurvivorController
from avenra.controllers.access_history_controller import AccessHistoryController


class AvenraApplication:
    """Object-Oriented Application Builder for avenra Flask application."""

    def __init__(self, config_class=Config):
        self.config_class = config_class
        self.csrf = CSRFProtect()

    def create_app(self) -> Flask:
        template_dir = os.path.join(BASE_DIR, "templates")
        static_dir = os.path.join(BASE_DIR, "static")

        app = Flask(
            "avenra",
            template_folder=template_dir,
            static_folder=static_dir,
        )

        self._configure_app(app)
        self._register_extensions(app)
        self._register_middleware(app)
        self._register_controllers(app)
        from avenra.controllers.push_controller import register_webpush
        register_webpush(app)
        from avenra.controllers.staff_invitation_controller import register_staff_invitations
        register_staff_invitations(app)

        from avenra.controllers.device_controller import register_devices
        register_devices(app)
        from avenra.controllers.onboarding_controller import register_onboarding
        register_onboarding(app)
        from avenra.controllers.worker_controller import register_worker
        register_worker(app)

        # All entrypoints, including gunicorn app:app, initialise the same schema.
        db.init_db()
        if not os.environ.get("VERCEL"):
            os.makedirs(self.config_class.UPLOADS_DIR, mode=0o700, exist_ok=True)
        if app.config['EVALUATION_MODE']:
            import seed
            seed.prepare_evaluation_database()

        return app

    def _configure_app(self, app: Flask) -> None:
        secret_key = os.environ.get("SECRET_KEY", self.config_class.SECRET_KEY)
        if not secret_key or len(secret_key) < 32:
            raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters")

        app.config["SECRET_KEY"] = secret_key
        app.config['APP_ENV'] = self.config_class.APP_ENV
        app.config['EVALUATION_MODE'] = self.config_class.EVALUATION_MODE
        if app.config['APP_ENV'] not in {'development', 'evaluation', 'production'}:
            raise RuntimeError('APP_ENV must be development, evaluation or production')
        if app.config['APP_ENV'] == 'production' and not self.config_class.SESSION_COOKIE_SECURE:
            raise RuntimeError('Production requires COOKIE_SECURE=1 and HTTPS')
        app.config["SESSION_COOKIE_HTTPONLY"] = self.config_class.SESSION_COOKIE_HTTPONLY
        app.config["SESSION_COOKIE_SAMESITE"] = self.config_class.SESSION_COOKIE_SAMESITE
        app.config["SESSION_COOKIE_SECURE"] = self.config_class.SESSION_COOKIE_SECURE
        app.config["MAX_CONTENT_LENGTH"] = self.config_class.MAX_CONTENT_LENGTH
        app.config["WTF_CSRF_CHECK_DEFAULT"] = self.config_class.WTF_CSRF_CHECK_DEFAULT

    def _register_extensions(self, app: Flask) -> None:
        self.csrf.init_app(app)
        app.teardown_appcontext(db.close_db)

    DEVICE_WRITE_ENDPOINTS = frozenset((
        'worker_tick',
        'device_disconnect',
        'device_enroll',
        'complete_survivor_onboarding',
        'api_update_consent',
        'create_alert',
        'create_diary_entry',
        'update_diary_entry_sharing',
        'delete_contact',
        'save_contacts',
        'contact_push.invite',
    ))

    def _register_middleware(self, app: Flask) -> None:
        @app.errorhandler(CSRFError)
        def handle_csrf_error(error):
            if request.path.startswith("/api/"):
                return jsonify({"error": "csrf_failed"}), 400
            return (
                "This form has expired or could not be verified. "
                "Refresh the page and try again.",
                400,
            )

        @app.before_request
        def protect_writes():
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return
            if request.endpoint is None:
                return
            if request.endpoint in self.DEVICE_WRITE_ENDPOINTS:
                return
            if request.endpoint.startswith('contact_push.') or request.endpoint in {'staff_invitation.accept', 'login', 'logout'}:
                # These pages deliberately suppress Referer. Keep session-bound
                # CSRF token validation and require HTTPS browser Origin instead
                # of disabling CSRF or weakening the site's other form checks.
                from flask_wtf.csrf import validate_csrf
                from wtforms.validators import ValidationError
                try:
                    validate_csrf(request.form.get('csrf_token') if request.endpoint in {'staff_invitation.accept', 'login', 'logout'} else request.headers.get('X-CSRFToken'))
                except ValidationError:
                    raise CSRFError('Invalid contact form token.') from None
                if request.is_secure and request.headers.get('Origin') != os.environ.get('PUBLIC_BASE_URL', request.host_url.rstrip('/')).rstrip('/'):
                    return jsonify({'error':'cross_origin_write_forbidden'}),403
                return
            self.csrf.protect()

        @app.before_request
        def check_json_body():
            if os.environ.get('VERCEL') and not os.environ.get('DATABASE_URL') and request.path.startswith('/api/diary') and request.method not in {'GET','HEAD','OPTIONS'}:
                return jsonify({'error':'diary_storage_not_configured'}),503
            if request.path.startswith('/api/contact-push/') and request.content_length and request.content_length>4096:
                return jsonify({'error':'request_too_large'}),413
            return validate_json_body()

        @app.errorhandler(413)
        def too_large(error):
            return jsonify({"error": "request_too_large"}), 413

        @app.context_processor
        def inject_user():
            user = current_user()
            from avenra.repositories.portal_repository import PortalRepository
            return {
                "access_signature": PortalRepository().access_signature(user) if user else '',
                "session_expires": session.get('issued_at', 0) + self.config_class.STAFF_SESSION_SECONDS,
                "user": user,
                "role_label": self.config_class.ROLE_LABELS.get(user["role"], user["role"]) if user else "",
            }

        @app.after_request
        def record_audit_access_denial(response):
            if response.status_code != 403:
                return response

            from avenra.services.access_denial_service import (
                AccessDenialService,
            )

            if request.endpoint not in AccessDenialService.ENDPOINTS:
                return response

            user = current_user()
            if user is not None:
                AccessDenialService().record(
                    user,
                    request.endpoint,
                    request.method,
                )

            return response

        @app.after_request
        def security_headers(resp):
            return apply_security_headers(resp)

    def _register_controllers(self, app: Flask) -> None:
        auth_ctrl = AuthController()
        pages_ctrl = PagesController()
        alerts_ctrl = AlertsController()
        contacts_ctrl = ContactsController()
        shelters_ctrl = SheltersController()
        referrals_ctrl = ReferralsController()
        consents_ctrl = ConsentsController()
        diary_ctrl = DiaryController()
        audit_ctrl = AuditController()
        survivor_ctrl = SurvivorController()
        access_history_ctrl = AccessHistoryController()

        # Core Pages
        app.add_url_rule("/", endpoint="home", view_func=pages_ctrl.home, methods=["GET"])
        app.add_url_rule("/health", endpoint="health", view_func=pages_ctrl.health, methods=["GET"])
        app.add_url_rule("/dashboard", endpoint="dashboard", view_func=pages_ctrl.dashboard, methods=["GET"])
        app.add_url_rule("/cases", endpoint="cases_page", view_func=pages_ctrl.cases_page, methods=["GET"])
        app.add_url_rule("/cases/<case_code>", endpoint="cases_page", view_func=pages_ctrl.cases_page, methods=["GET"])
        app.add_url_rule("/api/cases/<case_code>/access", endpoint="manage_case_access", view_func=pages_ctrl.manage_case_access, methods=["POST"])
        app.add_url_rule("/shelters", endpoint="shelters_page", view_func=pages_ctrl.shelters_page, methods=["GET"])
        app.add_url_rule("/referrals", endpoint="referrals_page", view_func=pages_ctrl.referrals_page, methods=["GET"])
        app.add_url_rule("/audit-log", endpoint="audit_log_page", view_func=pages_ctrl.audit_log_page, methods=["GET"])

        # Auth
        app.add_url_rule("/login", endpoint="login", view_func=auth_ctrl.login, methods=["GET", "POST"])
        app.add_url_rule("/logout", endpoint="logout", view_func=auth_ctrl.logout, methods=["POST"])
        app.add_url_rule("/api/session", endpoint="staff_session", view_func=auth_ctrl.staff_session, methods=["GET"])
        app.add_url_rule('/evaluation', endpoint='evaluation_page', view_func=auth_ctrl.evaluation_page, methods=['GET'])
        app.add_url_rule('/evaluation/login/<role>', endpoint='evaluation_login', view_func=auth_ctrl.evaluation_login, methods=['POST'])

        # API: Alerts
        app.add_url_rule("/api/alerts", endpoint="create_alert", view_func=alerts_ctrl.create_alert, methods=["POST"])
        app.add_url_rule("/api/alerts", endpoint="list_alerts", view_func=alerts_ctrl.list_alerts, methods=["GET"])
        app.add_url_rule("/api/alerts/<int:alert_id>/acknowledge", endpoint="acknowledge_alert", view_func=alerts_ctrl.acknowledge_alert, methods=["POST"])
        app.add_url_rule("/api/alerts/<int:alert_id>/status", endpoint="alert_status", view_func=alerts_ctrl.alert_status, methods=["GET"])

        app.add_url_rule("/api/alerts/<int:alert_id>/workflow", endpoint="change_alert", view_func=alerts_ctrl.change_alert, methods=["POST"])

        # API: Contacts
        app.add_url_rule("/api/contacts", endpoint="list_contacts", view_func=contacts_ctrl.list_contacts, methods=["GET"])
        app.add_url_rule("/api/contacts", endpoint="save_contacts", view_func=contacts_ctrl.save_contacts, methods=["POST"])
        app.add_url_rule("/api/contacts/<int:contact_id>", endpoint="delete_contact", view_func=contacts_ctrl.delete_contact, methods=["DELETE"])

        # API: Shelters & Referrals
        app.add_url_rule("/api/shelters", endpoint="api_shelters", view_func=shelters_ctrl.api_shelters, methods=["GET"])
        app.add_url_rule("/api/shelters/<int:shelter_id>/capacity", endpoint="update_shelter_capacity", view_func=shelters_ctrl.update_capacity, methods=["POST"])
        app.add_url_rule("/api/alerts/<int:alert_id>/nearby-services", endpoint="nearby_services", view_func=shelters_ctrl.nearby_services, methods=["GET"])
        app.add_url_rule("/api/referrals", endpoint="list_referrals", view_func=referrals_ctrl.list_referrals, methods=["GET"])
        app.add_url_rule("/api/referrals", endpoint="create_referral", view_func=referrals_ctrl.create_referral, methods=["POST"])
        app.add_url_rule("/api/referrals/<int:ref_id>/status", endpoint="update_referral_status", view_func=referrals_ctrl.update_referral_status, methods=["POST"])

        # API: Consents & Audit
        app.add_url_rule("/api/consents", endpoint="api_get_consents", view_func=consents_ctrl.get_consents, methods=["GET"])
        app.add_url_rule("/api/consents", endpoint="api_update_consent", view_func=consents_ctrl.update_consent, methods=["POST"])
        app.add_url_rule("/api/audit-log", endpoint="api_audit_log", view_func=audit_ctrl.api_audit_log, methods=["GET"])
        app.add_url_rule("/api/my-access", endpoint="my_access", view_func=access_history_ctrl.my_access, methods=["GET"])

        # API: Diary
        app.add_url_rule("/api/diary", endpoint="create_diary_entry", view_func=diary_ctrl.create_diary_entry, methods=["POST"])
        app.add_url_rule("/api/diary", endpoint="list_diary_entries", view_func=diary_ctrl.list_diary_entries, methods=["GET"])
        app.add_url_rule("/api/diary/<int:entry_id>", endpoint="get_diary_entry", view_func=diary_ctrl.get_diary_entry, methods=["GET"])
        app.add_url_rule("/api/diary/<int:entry_id>/photo", endpoint="survivor_diary_photo", view_func=diary_ctrl.survivor_diary_photo, methods=["GET"])
        app.add_url_rule("/api/diary/<int:entry_id>/share", endpoint="update_diary_entry_sharing", view_func=diary_ctrl.update_diary_entry_sharing, methods=["POST"])
        app.add_url_rule("/cases/diary-photo/<int:entry_id>", endpoint="diary_photo", view_func=diary_ctrl.diary_photo, methods=["GET"])

        # Survivor PWA static files
        app.add_url_rule("/survivor/", endpoint="survivor_index", view_func=survivor_ctrl.survivor_index, methods=["GET"])
        app.add_url_rule("/survivor/<path:filename>", endpoint="survivor_file", view_func=survivor_ctrl.survivor_file, methods=["GET"])
