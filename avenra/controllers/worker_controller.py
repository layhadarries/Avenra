"""Bounded hosted outbox processing. No browser, staff or public authority."""
import hmac
import os
import sqlite3
from flask import request,jsonify,current_app
import db

def register_worker(app):
    @app.post('/api/worker/tick')
    def worker_tick():
        expected=os.environ.get('AVENRA_WORKER_TOKEN','')
        supplied=request.headers.get('Authorization','')
        if len(expected)<32 or len(supplied)>512 or not hmac.compare_digest(supplied.encode(),('Bearer '+expected).encode()):
            return jsonify(error='unauthorized'),401
        if os.environ.get('AVENRA_WEBPUSH_ENABLED')!='1' and os.environ.get('AVENRA_SMS_ENABLED')!='1':
            return jsonify(processed=0,enabled=False)
        if current_app.config['EVALUATION_MODE']:
            return jsonify(error='evaluation_dispatch_forbidden'),403
        from avenra.services.push_service import PushSettings,PushError
        from avenra.services.push_worker import PushWorker
        from avenra.services.webpush_sender import WebPushSender
        from avenra.services.notification_worker import NotificationWorker
        conn=db.get_db()
        try:
            settings=PushSettings() if os.environ.get('AVENRA_WEBPUSH_ENABLED')=='1' else None
            from avenra.services.sms_sender import TwilioSender
            sms_sender=TwilioSender(os.environ) if os.environ.get('AVENRA_SMS_ENABLED')=='1' else None
            if (request.get_json(silent=True) or {}).get('dry_run') is True:
                return jsonify(processed=0,enabled=True,release='stage6-demo-20261025',commit=os.environ.get('AVENRA_RELEASE_COMMIT',''))
            recovery=NotificationWorker(conn,lambda **_:None,evaluation_mode=False)
            recovery.recover_stale()
            processed=0
            if settings is not None:
                worker=PushWorker(conn,WebPushSender(settings),settings,evaluation_mode=False)
                processed+=int(worker.run_once())
            if sms_sender is not None:
                processed+=int(NotificationWorker(conn,sms_sender,evaluation_mode=False).run_once())
            from avenra.services.alert_service import utc_now
            with conn:
                conn.execute("INSERT INTO worker_state(key,last_seen_at,processed,release) VALUES('webpush',?,?,?) ON CONFLICT(key) DO UPDATE SET last_seen_at=EXCLUDED.last_seen_at,processed=EXCLUDED.processed,release=EXCLUDED.release", (utc_now(),processed,'stage6-demo-20261025'))
        except (PushError,sqlite3.Error,RuntimeError,ValueError):
            conn.rollback()
            return jsonify(error='worker_unavailable'),503
        # Never expose recipients, subscription endpoints, job payloads or tokens.
        return jsonify(processed=processed,enabled=True)
