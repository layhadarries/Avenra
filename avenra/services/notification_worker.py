"""One worker iteration; no provider retry or channel fallback."""
import re
import urllib.error
from datetime import datetime, timedelta, timezone
from flask import current_app, has_app_context
import sms
from avenra.repositories.audit_repository import AuditRepository
from avenra.repositories.consent_repository import ConsentRepository
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository

class NotificationWorker:
    def __init__(self, connection, sender, *, evaluation_mode):
        if type(evaluation_mode) is not bool: raise ValueError('Evaluation mode must be a boolean.')
        if not callable(sender): raise TypeError('Sender must be callable.')
        self.conn,self.sender,self.evaluation_mode=connection,sender,evaluation_mode
        self.repo=NotificationOutboxRepository(connection)
        self.consents=ConsentRepository(connection)
        self.audit=AuditRepository(connection)

    def _disabled(self):
        from avenra.services.environment_isolation_service import EnvironmentIsolationService
        if not EnvironmentIsolationService(self.conn).compatible():
            return True
        marked=self.conn.execute(
            "SELECT 1 FROM app_metadata WHERE key='evaluation_fixture'"
        ).fetchone()
        return bool(marked) or self.evaluation_mode or (
            has_app_context() and current_app.config.get('EVALUATION_MODE')
        )

    def _finish(self, job, outcome, case_code=None, *, provider_message_id=None, reason_code=None):
        with self.conn:
            changed=self.repo.finish(job['id'],job['claim_token'],outcome,
                provider_message_id=provider_message_id,reason_code=reason_code)
            self.audit.log('notification_worker',
                'notification_'+outcome if changed else 'notification_outcome_unrecorded',
                case_code,f"job {job['id']}; alert {job['alert_id']}",commit=False)
        return changed

    def run_once(self):
        if self._disabled(): return False
        if self.conn.in_transaction: raise RuntimeError('Worker requires an idle connection.')
        with self.conn:
            job=self.repo.claim_next(channel='sms')
            if job is not None and not self.repo.reserve_alert_budget(job['alert_id']):
                row=self.conn.execute('SELECT case_code FROM alerts WHERE id=?',(job['alert_id'],)).fetchone()
                self.repo.finish(job['id'],job['claim_token'],'cancelled',reason_code='rate_limited')
                self.repo.cancel_rate_limited_pending(job['alert_id'])
                self.audit.log('notification_worker','notification_rate_limited',
                    row['case_code'] if row else None,f"alert {job['alert_id']}",commit=False)
                return True
        if job is None: return False
        context=self.repo.dispatch_context(job['id'],job['claim_token'])
        if context is None:
            self._finish(job,'cancelled',reason_code='recipient_unavailable'); return True
        if context['channel']!='sms':
            self._finish(job,'cancelled',context['case_code'],reason_code='unsupported_channel'); return True
        if not context.get('sms_opt_in'):
            self._finish(job,'cancelled',context['case_code'],reason_code='recipient_unavailable'); return True
        lat,lng=context['lat'],context['lng']
        if not self.consents.is_active(context['user_id'],'location_sharing'): lat=lng=None
        message=sms.build_message(context['case_code'],lat,lng,context['client_ts'])
        provider_id=None; reason=None
        try:
            result=self.sender(name=context['name'],phone=context['phone'],message=message,case_code=context['case_code'])
        except (TimeoutError,urllib.error.URLError,OSError):
            outcome,reason='unknown','transport_uncertain'
        else:
            value=result.get('outcome') if isinstance(result,dict) else None
            outcome=value if isinstance(value,str) and value in {'accepted','failed','unknown'} else 'unknown'
            if isinstance(result,dict):
                candidate=result.get('provider_message_id')
                if candidate is not None:
                    if isinstance(candidate,str) and re.fullmatch(r'SM[0-9a-fA-F]{32}',candidate): provider_id=candidate
                    else: outcome='unknown'
                candidate=result.get('reason')
                if candidate in ('provider_accepted','provider_rejected','provider_uncertain',
                    'transport_uncertain','invalid_response','invalid_recipient','invalid_message','evaluation_disabled'):
                    reason=candidate
        self._finish(job,outcome,context['case_code'],provider_message_id=provider_id,reason_code=reason)
        return True

    def recover_stale(self,max_age_seconds=900):
        if type(max_age_seconds) is not int or not 60<=max_age_seconds<=86400:
            raise ValueError('Recovery age must be an integer from 60 to 86400 seconds.')
        if self._disabled(): return 0
        if self.conn.in_transaction: raise RuntimeError('Recovery requires an idle connection.')
        cutoff=datetime.now(timezone.utc)-timedelta(seconds=max_age_seconds)
        with self.conn:
            changed=self.repo.mark_stale_unknown(cutoff)
            if changed:self.audit.log('notification_worker','notification_recovery',None,
                f'claims_marked_unknown={changed}',commit=False)
        return changed
