"""Scoped Web Push invitations, opt-ins and acknowledgement capabilities."""
import secrets
from avenra.repositories.base import BaseRepository
from avenra.services.push_service import PushError,digest

SCHEMA="""
CREATE TABLE IF NOT EXISTS push_invites (
 id INTEGER PRIMARY KEY,contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
 token_hash TEXT UNIQUE NOT NULL,expires_at TEXT NOT NULL,used_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE INDEX IF NOT EXISTS push_invite_contact ON push_invites(contact_id);
CREATE TABLE IF NOT EXISTS push_subscriptions (
 id INTEGER PRIMARY KEY,contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
 endpoint_hash TEXT NOT NULL,encrypted_subscription TEXT NOT NULL,browser_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)),last_test_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 UNIQUE(contact_id,endpoint_hash));
CREATE TABLE IF NOT EXISTS push_acknowledgements (
 job_id INTEGER PRIMARY KEY REFERENCES notification_outbox(id) ON DELETE CASCADE,
 subscription_id INTEGER NOT NULL REFERENCES push_subscriptions(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,acknowledged_at TEXT);
"""

class PushRepository(BaseRepository):
    def invite(self,user_id,contact_id):
        if self.conn.execute('SELECT id FROM contacts WHERE id=? AND user_id=?',(contact_id,user_id)).fetchone() is None:
            raise PushError('not_found',404)
        if self.conn.execute("SELECT COUNT(*) FROM push_invites WHERE contact_id=? AND julianday(created_at)>=julianday('now','-1 hour')",(contact_id,)).fetchone()[0]>=5:
            raise PushError('invite_rate_limited',429)
        token=secrets.token_urlsafe(32)
        self.conn.execute("UPDATE push_invites SET used_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE contact_id=? AND used_at IS NULL",(contact_id,))
        self.conn.execute("INSERT INTO push_invites(contact_id,token_hash,expires_at) VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now','+1 day'))",(contact_id,digest(token)))
        return token
    def accept(self,token,subscription,browser_token,settings):
        if not isinstance(token,str) or len(token)!=43:raise PushError('not_found',404)
        row=self.conn.execute("SELECT * FROM push_invites WHERE token_hash=? AND used_at IS NULL AND julianday(expires_at)>julianday('now')",(digest(token),)).fetchone()
        if row is None:raise PushError('not_found',404)
        encrypted=settings.encrypt(subscription)
        endpoint_hash=digest(subscription['endpoint'])
        existing=self.conn.execute('SELECT * FROM push_subscriptions WHERE contact_id=? AND active=1',(row['contact_id'],)).fetchone()
        # Another browser cannot silently replace an accepted contact's device.
        if existing is not None and existing['browser_hash']!=digest(browser_token):raise PushError('contact_already_enrolled',409)
        self.conn.execute("UPDATE push_invites SET used_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",(row['id'],))
        self.conn.execute('UPDATE push_subscriptions SET active=0 WHERE contact_id=?',(row['contact_id'],))
        self.conn.execute("""INSERT INTO push_subscriptions(contact_id,endpoint_hash,encrypted_subscription,browser_hash)
            VALUES(?,?,?,?) ON CONFLICT(contact_id,endpoint_hash) DO UPDATE SET
            encrypted_subscription=excluded.encrypted_subscription,browser_hash=excluded.browser_hash,active=1""",
            (row['contact_id'],endpoint_hash,encrypted,digest(browser_token)))
        # Enrollment must never dispatch previously queued alerts retroactively.
        self.conn.execute("UPDATE notification_outbox SET status='cancelled',reason_code='recipient_unavailable',completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE contact_id=? AND status='pending'",(row['contact_id'],))
        self.conn.execute("UPDATE contacts SET channel='webpush' WHERE id=?",(row['contact_id'],))
        return self.conn.execute('SELECT id FROM push_subscriptions WHERE contact_id=? AND endpoint_hash=?',(row['contact_id'],endpoint_hash)).fetchone()['id']
    def for_browser(self,token):
        if not isinstance(token,str) or len(token)!=43:return []
        return [dict(r) for r in self.conn.execute('SELECT id FROM push_subscriptions WHERE browser_hash=? AND active=1',(digest(token),))]
    def owned(self,subscription_id,token):
        if type(subscription_id) is not int or not isinstance(token,str) or len(token)!=43:return None
        return self.conn.execute('SELECT * FROM push_subscriptions WHERE id=? AND browser_hash=? AND active=1',(subscription_id,digest(token))).fetchone()
    def revoke(self,subscription_id):
        self.conn.execute('UPDATE push_subscriptions SET active=0 WHERE id=?',(subscription_id,))
    def acknowledge(self,token):
        if not isinstance(token,str) or len(token)!=43:raise PushError('not_found',404)
        row=self.conn.execute("""SELECT p.job_id FROM push_acknowledgements p
            JOIN push_subscriptions s ON s.id=p.subscription_id AND s.active=1
            JOIN notification_outbox n ON n.id=p.job_id AND n.status IN ('processing','accepted','unknown')
            WHERE p.token_hash=? AND julianday(p.expires_at)>julianday('now')""",(digest(token),)).fetchone()
        if row is None:raise PushError('not_found',404)
        self.conn.execute("UPDATE push_acknowledgements SET acknowledged_at=COALESCE(acknowledged_at,strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE job_id=?",(row['job_id'],))
