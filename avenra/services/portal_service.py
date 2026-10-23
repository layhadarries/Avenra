"""Staff portal queries and validated alert transitions."""
from datetime import date, timedelta
from avenra.repositories.portal_repository import PortalRepository
from avenra.repositories.case_access_repository import CaseAccessRepository
from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.models.alert import Alert
from avenra.services.alert_service import utc_now


class PortalService:
    def __init__(self, repository=None):
        self.repo = repository or PortalRepository()

    def list_alerts(self, user, args):
        try:
            filters = {key: int(args.get(key, default)) for key, default in
                       [('page', 1), ('per_page', 25), ('snapshot', 0)]}
            if filters['page'] < 1 or not 1 <= filters['per_page'] <= 100 or filters['snapshot'] < 0:
                raise ValueError
            filters['q'] = args.get('q', '').strip()[:80]
            filters['status'] = args.get('status', '')
            if filters['status'] not in ('', 'new', 'acknowledged', 'in_progress', 'resolved'):
                raise ValueError
            filters['assignee'] = int(args['assignee']) if args.get('assignee') else None
            for key in ('since', 'until'):
                if args.get(key):
                    value = date.fromisoformat(args[key])
                    if key == 'until':
                        value += timedelta(days=1)
                    filters[key] = value.isoformat() + 'T00:00:00Z'
            if filters.get('since', '') >= filters.get('until', '9999'):
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            return {'error': 'invalid_filters'}, 400
        rows, total = self.repo.alert_page(user.id, filters)
        consent = ConsentRepository(self.repo.conn)
        items = []
        for row in rows:
            item = Alert.from_row(row).serialize(consent.is_active(row['user_id'], 'location_sharing'))
            item.update({key: row[key] for key in ('assigned_to', 'assigned_name', 'escalated_at', 'revision')})
            # The current sender does not supply a measured GPS accuracy or fix time.
            item['location_accuracy'] = None
            item['location_recorded_at'] = row['client_ts'] or row['created_at']
            items.append(item)
        return {'alerts': items, 'total': total, 'page': filters['page'],
                'per_page': filters['per_page'],
                'snapshot': filters['snapshot'] or (max((r['id'] for r in rows), default=0)),
                'has_next': filters['page'] * filters['per_page'] < total}, 200

    def change_alert(self, alert_id, user, data):
        conn = self.repo.conn
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            alert = AlertRepository(conn).get_by_id(alert_id)
            access = CaseAccessRepository(conn)
            if alert is None or not access.allows(user.id, alert.user_id):
                return {'error': 'not_found'}, 404
            workflow = self.repo.workflow(alert_id)
            if type(data.get('revision')) is not int or data['revision'] != workflow['revision']:
                return {'error': 'stale_alert', 'message': 'This alert changed. Refresh and try again.'}, 409
            action = data.get('action')
            reason = data.get('reason', '')
            if not isinstance(reason, str) or len(reason) > 500:
                return {'error': 'invalid_reason'}, 400
            reason = reason.strip()
            if alert.status == 'resolved':
                return {'error': 'alert_resolved'}, 409
            if action == 'assign':
                assignee = data.get('assignee_id')
                candidates = access.candidates(alert.user_id)
                if type(assignee) is not int or assignee not in [c['id'] for c in candidates]:
                    return {'error': 'invalid_assignee'}, 400
                workflow['assigned_to'] = assignee
                reason = f'Assigned to staff #{assignee}'
            elif action == 'escalate':
                if not reason:
                    return {'error': 'reason_required'}, 400
                workflow['escalated_at'] = utc_now()
            elif action == 'resolve':
                if alert.status == 'new' or not reason:
                    return {'error': 'acknowledgement_and_reason_required'}, 409
                if conn.execute("SELECT 1 FROM referrals WHERE alert_id=? AND status IN ('sent','accepted')", (alert_id,)).fetchone():
                    return {'error': 'active_referral'}, 409
                conn.execute("UPDATE alerts SET status='resolved' WHERE id=?", (alert_id,))
            else:
                return {'error': 'invalid_action'}, 400
            self.repo.update_workflow(alert_id, workflow['assigned_to'], workflow['escalated_at'])
            self.repo.record(alert_id, user.id, action, reason)
            conn.execute('INSERT INTO audit_log(actor,action,case_code,detail) VALUES (?,?,?,?)',
                         (f'user:{user.id}', 'alert_' + action, alert.case_code, f'alert {alert_id}'))
        return {'ok': True, 'revision': workflow['revision'] + 1}, 200
