"""Durable notification jobs. Callers own all transaction boundaries."""
import re
import os
import secrets
from datetime import datetime, timezone
from avenra.repositories.base import BaseRepository

class NotificationOutboxRepository(BaseRepository):
    def enqueue_for_alert(self, alert_id):
        if self.conn.execute('SELECT id FROM alerts WHERE id=?', (alert_id,)).fetchone() is None:
            raise ValueError('Alert does not exist.')
        if os.environ.get('AVENRA_WEBPUSH_ENABLED') == '1':
            cursor = self.conn.execute("""INSERT INTO notification_outbox(alert_id,contact_id)
                SELECT a.id,c.id FROM alerts a JOIN contacts c ON c.user_id=a.user_id
                WHERE a.id=? AND c.channel='webpush' AND EXISTS(
                SELECT 1 FROM push_subscriptions s WHERE s.contact_id=c.id AND s.active=1)
                ON CONFLICT(alert_id,contact_id) DO NOTHING""", (alert_id,))
            return cursor.rowcount
        cursor = self.conn.execute("""INSERT INTO notification_outbox(alert_id,contact_id)
            SELECT a.id,c.id FROM alerts a JOIN contacts c ON c.user_id=a.user_id
            WHERE a.id=? ON CONFLICT(alert_id,contact_id) DO NOTHING""", (alert_id,))
        return cursor.rowcount

    def pending(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Limit must be an integer from 1 to 100.')
        return [dict(r) for r in self.conn.execute("""SELECT id,alert_id,contact_id,status
            FROM notification_outbox WHERE status='pending' ORDER BY id LIMIT ?""", (limit,))]

    def claim_next(self, channel=None):
        cursor = self.conn.execute("""UPDATE notification_outbox SET status='processing',
            claim_token=?,claimed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE id=(SELECT id FROM notification_outbox WHERE status='pending' AND (? IS NULL OR EXISTS(SELECT 1 FROM contacts c WHERE c.id=notification_outbox.contact_id AND c.channel=?)) ORDER BY id LIMIT 1)
            AND status='pending' RETURNING id,alert_id,contact_id,status,claim_token,claimed_at""",
            (secrets.token_hex(32),channel,channel))
        rows = cursor.fetchall()
        return dict(rows[0]) if rows else None

    def finish(self, job_id, claim_token, outcome, *, provider_message_id=None, reason_code=None):
        if not isinstance(outcome, str) or outcome not in {'accepted','failed','unknown','cancelled'}:
            raise ValueError('Unsupported notification outcome.')
        if provider_message_id is not None and (
            not isinstance(provider_message_id, str)
            or not re.fullmatch(r'SM[0-9a-fA-F]{32}', provider_message_id)
        ):
            raise ValueError('Invalid provider message identifier.')
        allowed_reasons = {'provider_accepted','provider_rejected','provider_uncertain',
            'transport_uncertain','invalid_response','invalid_recipient','invalid_message',
            'rate_limited','recipient_unavailable','unsupported_channel','evaluation_disabled'}
        if reason_code is not None and reason_code not in allowed_reasons:
            raise ValueError('Invalid notification reason.')
        if not isinstance(claim_token, str) or not claim_token:
            return False
        cursor = self.conn.execute("""UPDATE notification_outbox SET status=?,
            provider_message_id=?,reason_code=?,completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE id=? AND status='processing' AND claim_token=?""",
            (outcome,provider_message_id,reason_code,job_id,claim_token))
        return cursor.rowcount == 1

    def dispatch_context(self, job_id, claim_token):
        row = self.conn.execute("""SELECT a.user_id,a.case_code,a.lat,a.lng,a.client_ts,
            c.name,c.phone,c.channel FROM notification_outbox n
            JOIN alerts a ON a.id=n.alert_id
            JOIN users u ON u.id=a.user_id AND u.role='survivor'
            JOIN contacts c ON c.id=n.contact_id AND c.user_id=a.user_id
            WHERE n.id=? AND n.claim_token=? AND n.status='processing' """,
            (job_id,claim_token)).fetchone()
        return dict(row) if row is not None else None

    def mark_stale_unknown(self, cutoff):
        if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError('Cutoff must be a timezone-aware datetime.')
        cursor = self.conn.execute("""UPDATE notification_outbox SET status='unknown',
            reason_code='transport_uncertain',completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE status='processing' AND claimed_at IS NOT NULL
            AND julianday(claimed_at)<julianday(?)""", (cutoff.astimezone(timezone.utc).isoformat(),))
        return cursor.rowcount

    def reserve_alert_budget(self, alert_id):
        """At most five distinct alert-notification batches per survivor/hour.
        Must run in the same write transaction as claim_next()."""
        if self.conn.execute('SELECT 1 FROM notification_batches WHERE alert_id=?', (alert_id,)).fetchone():
            return True
        cursor = self.conn.execute("""INSERT INTO notification_batches(alert_id,user_id)
            SELECT a.id,a.user_id FROM alerts a WHERE a.id=? AND
            (SELECT COUNT(*) FROM notification_batches b WHERE b.user_id=a.user_id
             AND julianday(b.attempted_at)>=julianday('now','-1 hour'))<5
            ON CONFLICT(alert_id) DO NOTHING""", (alert_id,))
        return cursor.rowcount == 1

    def cancel_rate_limited_pending(self, alert_id):
        self.conn.execute("""UPDATE notification_outbox SET status='cancelled',
            reason_code='rate_limited',completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE alert_id=? AND status='pending' """, (alert_id,))

    def summary(self, alert_id):
        rows = list(self.conn.execute("""SELECT status,reason_code,COUNT(*) AS n
            FROM notification_outbox WHERE alert_id=? GROUP BY status,reason_code""", (alert_id,)))
        counts = {key:0 for key in ('pending','processing','accepted','delivered','failed','unknown','cancelled')}
        limited = 0
        for r in rows:
            counts[r['status']] += r['n']
            if r['reason_code']=='rate_limited': limited += r['n']
        total=sum(counts.values())
        if not total: state='not_requested'
        elif counts['unknown']: state='unknown'
        elif counts['processing']: state='processing'
        elif counts['pending']: state='queued'
        elif counts['failed']: state='partial' if counts['accepted'] or counts['delivered'] else 'failed'
        elif limited == total: state='skipped'
        elif counts['cancelled']: state='partial' if counts['accepted'] or counts['delivered'] else 'cancelled'
        elif counts['delivered']==total: state='delivered'
        else: state='accepted'
        return {'status':state,'total':total,**counts}
