"""Bearer invitation creation and explicit contact opt-in; no case-data access."""
import os
import secrets
import sqlite3
from flask import Blueprint,request,jsonify,render_template,current_app,make_response,send_from_directory
from avenra.security import device_user
from avenra.repositories.push_repository import PushRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.services.push_service import PushError,PushSettings,validate_subscription


def register_webpush(app):
    def cookie_name():
        return '__Host-avenra_push_browser' if request.is_secure else 'avenra_push_browser'
    bp=Blueprint('contact_push',__name__)
    @bp.errorhandler(PushError)
    def failed(error):return jsonify({'error':error.code}),error.status
    @bp.errorhandler(sqlite3.Error)
    def database_failed(error):return jsonify({'error':'push_storage_unavailable'}),503
    @bp.before_request
    def secure_origin():
        if os.environ.get('AVENRA_WEBPUSH_ENABLED')!='1':raise PushError('push_disabled',404)
        if not request.is_secure and request.host.split(':')[0] not in {'localhost','127.0.0.1'}:
            raise PushError('https_required',400)
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
    @bp.get('/contact-push/')
    def page():return render_template('contact_push.html')
    @bp.get('/contact-push/<name>')
    def asset(name):
        if name not in {'contact.js','worker.js','manifest.json','contact.css'}:raise PushError('not_found',404)
        return send_from_directory(os.path.join(app.static_folder,'contact-push'),name)
    @bp.get('/api/contact-push/config')
    def config():
        settings=PushSettings()
        return jsonify({'public_key':settings.public,'self_test_enabled':os.environ.get('AVENRA_PUSH_SELF_TEST')=='1'})
    @bp.post('/api/contacts/<int:contact_id>/push-invite')
    def invite(contact_id):
        user=device_user()
        if user is None:raise PushError('bad_device_token',401)
        PushSettings() # Fail before issuing unusable links.
        repo=PushRepository()
        with repo.conn:
            repo.conn.execute('BEGIN IMMEDIATE')
            token=repo.invite(user.id,contact_id)
            AuditRepository(repo.conn).log('survivor '+user.case_code,'push_invite_created',user.case_code,
                'Contact invitation created',commit=False)
        return jsonify({'invite_token':token,'expires_in_seconds':86400,'path':'/contact-push/#invite='+token}),201
    @bp.post('/api/contact-push/accept')
    def accept():
        body=request.get_json(silent=True) or {}
        subscription=validate_subscription(body.get('subscription'))
        browser=request.cookies.get(cookie_name())
        if not browser or len(browser)!=43:browser=secrets.token_urlsafe(32)
        repo=PushRepository();settings=PushSettings()
        with repo.conn:
            repo.conn.execute('BEGIN IMMEDIATE')
            subscription_id=repo.accept(body.get('invite_token'),subscription,browser,settings)
            AuditRepository(repo.conn).log('contact','push_opt_in',None,'Contact notifications enabled',commit=False)
        response=make_response(jsonify({'subscription_id':subscription_id,'status':'subscribed'}),201)
        response.set_cookie(cookie_name(),browser,httponly=True,secure=request.is_secure,
            samesite='Strict',max_age=60*60*24*90,path='/')
        return response
    @bp.get('/api/contact-push/subscriptions')
    def subscriptions():
        return jsonify({'subscriptions':PushRepository().for_browser(request.cookies.get(cookie_name()))})
    @bp.post('/api/contact-push/unsubscribe')
    def unsubscribe():
        body=request.get_json(silent=True) or {};repo=PushRepository()
        with repo.conn:
            repo.conn.execute('BEGIN IMMEDIATE')
            row=repo.owned(body.get('subscription_id'),request.cookies.get(cookie_name()))
            if row is None:raise PushError('not_found',404)
            repo.revoke(row['id'])
        return jsonify({'status':'unsubscribed'})
    @bp.post('/api/contact-push/acknowledge')
    def acknowledge():
        body=request.get_json(silent=True) or {};repo=PushRepository()
        with repo.conn:
            repo.conn.execute('BEGIN IMMEDIATE');repo.acknowledge(body.get('token'))
        return jsonify({'status':'acknowledged'})
    @bp.post('/api/contact-push/test')
    def test():
        # Explicitly enrolled browser, neutral test only. Never claims alert jobs.
        if os.environ.get('AVENRA_PUSH_SELF_TEST')!='1':raise PushError('not_found',404)
        body=request.get_json(silent=True) or {};repo=PushRepository()
        with repo.conn:
            repo.conn.execute('BEGIN IMMEDIATE')
            row=repo.owned(body.get('subscription_id'),request.cookies.get(cookie_name()))
            if row is None:raise PushError('not_found',404)
            if row['last_test_at'] and repo.conn.execute("SELECT julianday(?)>=julianday('now','-1 minute')",(row['last_test_at'],)).fetchone()[0]:
                raise PushError('test_rate_limited',429)
            repo.conn.execute("UPDATE push_subscriptions SET last_test_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",(row['id'],))
        from avenra.services.webpush_sender import WebPushSender
        settings=PushSettings()
        result=WebPushSender(settings).send(settings.decrypt(row['encrypted_subscription']),'/contact-push/')
        return jsonify(result)
    app.register_blueprint(bp)
