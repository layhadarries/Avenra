"""Web Push dispatcher using the existing atomic outbox and rate limit."""
import secrets
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
from avenra.repositories.push_repository import PushRepository
from avenra.services.push_service import digest,PushError
from avenra.repositories.audit_repository import AuditRepository

class PushWorker:
    def __init__(self,connection,sender,settings,*,evaluation_mode):
        if type(evaluation_mode) is not bool:raise ValueError('Explicit evaluation mode required.')
        self.conn,self.sender,self.settings,self.evaluation_mode=connection,sender,settings,evaluation_mode
        self.repo=NotificationOutboxRepository(connection)
    def run_once(self):
        # The separate browser self-test is explicit; fictional alert jobs never send.
        if self.evaluation_mode or self.conn.execute("SELECT 1 FROM app_metadata WHERE key='evaluation_fixture'").fetchone():return False
        if self.conn.in_transaction:raise RuntimeError('Worker requires an idle connection.')
        with self.conn:
            job=self.repo.claim_next(channel='webpush')
            if job is None:return False
            if not self.repo.reserve_alert_budget(job['alert_id']):
                self.repo.finish(job['id'],job['claim_token'],'cancelled',reason_code='rate_limited')
                self.repo.cancel_rate_limited_pending(job['alert_id']);return True
        context=self.repo.dispatch_context(job['id'],job['claim_token'])
        row=self.conn.execute('SELECT * FROM push_subscriptions WHERE contact_id=? AND active=1',(job['contact_id'],)).fetchone()
        if context is None or row is None or context['channel']!='webpush':
            with self.conn:self.repo.finish(job['id'],job['claim_token'],'cancelled',reason_code='recipient_unavailable')
            return True
        token=secrets.token_urlsafe(32)
        with self.conn:
            self.conn.execute("""INSERT INTO push_acknowledgements(job_id,subscription_id,token_hash,expires_at)
                VALUES(?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now','+1 day'))""",(job['id'],row['id'],digest(token)))
        try:
            subscription=self.settings.decrypt(row['encrypted_subscription'])
            # Recheck revocation and current job ownership immediately before the send.
            active=self.conn.execute('SELECT active FROM push_subscriptions WHERE id=?',(row['id'],)).fetchone()
            if active is None or not active['active'] or self.repo.dispatch_context(job['id'],job['claim_token']) is None:
                result={'outcome':'failed','reason':'recipient_unavailable'}
            else:result=self.sender.send(subscription,'/contact-push/#ack='+token)
        except PushError:result={'outcome':'failed','reason':'invalid_recipient'}
        except (OSError,TimeoutError):result={'outcome':'unknown','reason':'transport_uncertain'}
        if not isinstance(result,dict):result={}
        outcome=result.get('outcome')
        if outcome not in {'accepted','failed','unknown'}:outcome='unknown'
        reason=result.get('reason')
        if reason not in {'provider_accepted','provider_rejected','provider_uncertain','transport_uncertain','invalid_recipient','recipient_unavailable','invalid_message'}:reason='invalid_response'
        with self.conn:
            if result.get('expired'):PushRepository(self.conn).revoke(row['id'])
            changed=self.repo.finish(job['id'],job['claim_token'],outcome,reason_code=reason)
            AuditRepository(self.conn).log('push_worker','push_'+outcome if changed else 'push_outcome_unrecorded',None,'Notification job processed',commit=False)
        return True
