"""Thin HTML controllers; services and repositories own data and business rules."""
from flask import render_template, redirect, url_for, request, abort, jsonify, current_app
from avenra.repositories.portal_repository import PortalRepository
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.services.case_service import CaseService
from avenra.services.portal_service import PortalService
from avenra.services.referral_service import ReferralService
from avenra.security import current_user, login_required, require_role
from avenra.config import Config


class PagesController:
    def home(self):
        return redirect(url_for('dashboard' if current_user() else 'login'))

    def health(self):
        body = {'status': 'ok'}
        if current_app.config.get('EVALUATION_MODE'):
            import seed
            from avenra.repositories.audit_repository import AuditRepository
            if seed.is_evaluation_database():
                body['counts'] = AuditRepository().table_counts()
        return jsonify(body)

    @login_required
    def dashboard(self):
        if current_user().role == 'shelter':
            return redirect(url_for('referrals_page'))
        return render_template('dashboard.html', can_see_alerts=True)

    @require_role(*Config.ALERT_ROLES)
    def cases_page(self, case_code=None):
        user = current_user()
        if case_code is None:
            return render_template('case_list.html', cases=PortalRepository().cases(user.id))
        context = CaseService().view(user, case_code.strip().upper())
        if context is None:
            abort(404)
        selected = request.args.get('alert_id', type=int)
        ids = [a['id'] for a in context['alerts']]
        context['selected_alert_id'] = selected if selected in ids else (ids[0] if ids else None)
        return render_template('cases.html', **context)

    @login_required
    def shelters_page(self):
        user = current_user()
        shelters = ShelterRepository().get_all()
        return render_template('shelters.html', shelters=shelters)

    @login_required
    def referrals_page(self):
        user = current_user()
        alerts = PortalService().list_alerts(user, {'per_page': '100'})[0]['alerts'] if user.role in Config.ALERT_ROLES else []
        return render_template('referrals.html', referrals=ReferralService().list_referrals(user),
                               shelters=ShelterRepository().get_all(), alerts=alerts)

    @require_role(*Config.ALERT_ROLES)
    def audit_log_page(self):
        return render_template('audit_log.html', events=[])

    @require_role('admin')
    def manage_case_access(self, case_code: str):
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        staff_id = data.get('staff_id')
        if not isinstance(staff_id, int):
            return jsonify({'error': 'invalid_staff'}), 400
        res, status = CaseService().manage_grant(
            current_user(),
            case_code.strip().upper(),
            action,
            staff_id
        )
        return jsonify(res), status
