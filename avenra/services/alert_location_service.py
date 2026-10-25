"""Bounded, consent-epoch-bound emergency fixes; never dispatch or change workflow."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3

from flask import current_app, request
from itsdangerous import URLSafeTimedSerializer, BadData

from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.audit_repository import AuditRepository

MAX_FIX_AGE = 120
MAX_ACCURACY = 1000
ALLOWED = frozenset(('lat','lng','location_accuracy','location_recorded_at','location_consent_token'))


def timestamp(value):
    if not isinstance(value,str) or len(value)>64:
        raise ValueError('invalid_location_time')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None: raise ValueError('timezone_required')
        return result.astimezone(timezone.utc)
    except (ValueError,OverflowError):
        raise ValueError('invalid_location_time') from None


def validate_fix(data):
    if not isinstance(data,dict) or set(data)!=ALLOWED:
        raise ValueError('invalid_location_fields')
    for name,limit in (('lat',90),('lng',180),('location_accuracy',MAX_ACCURACY)):
        value=data[name]
        if type(value) not in (int,float) or abs(value)>limit or not math.isfinite(value):
            raise ValueError('invalid_location_'+name)
    if data['location_accuracy']<0: raise ValueError('invalid_location_accuracy')
    captured=timestamp(data['location_recorded_at'])
    age=(datetime.now(timezone.utc)-captured).total_seconds()
    if not -10 <= age <= MAX_FIX_AGE: raise ValueError('location_not_recent')
    return {'lat':round(data['lat'],6),'lng':round(data['lng'],6),'location_accuracy':float(data['location_accuracy']),
            'location_recorded_at':captured.isoformat(timespec='microseconds').replace('+00:00','Z')}


class LocationPermission:
    def __init__(self,conn): self.conn=conn

    def grant(self,survivor):
        row=self.conn.execute("SELECT id,granted_at,revoked_at FROM consents WHERE user_id=? AND item='location_sharing' ORDER BY id DESC LIMIT 1",(survivor.id,)).fetchone()
        if not row or row['revoked_at'] is not None: return None
        # Existing consent updates and their audit event commit atomically. The
        # event sequence prevents revoke/regrant ABA even within the same second.
        event=self.conn.execute("SELECT MAX(id) FROM audit_log WHERE case_code=? AND action IN ('consent_granted','consent_revoked') AND detail LIKE ?",
            (survivor.case_code,'location_sharing (%)')).fetchone()[0]
        return hashlib.sha256(json.dumps([row['id'],row['granted_at'],event],separators=(',',':')).encode()).hexdigest()

    @staticmethod
    def device_binding():
        return hashlib.sha256(request.cookies.get('avenra_device','').encode()).hexdigest()

    @staticmethod
    def signer():
        return URLSafeTimedSerializer(current_app.secret_key,salt='emergency-location-v1')

    def issue(self,survivor):
        grant=self.grant(survivor)
        return {'allowed':bool(grant),'owner_id':survivor.id,'grant':grant,'max_age_seconds':MAX_FIX_AGE,'max_accuracy_meters':MAX_ACCURACY,
                'token':self.signer().dumps({'owner':survivor.id,'grant':grant,'device':self.device_binding()}) if grant else None}

    def valid(self,survivor,token):
        if not isinstance(token,str) or len(token)>1024: return False
        try: value=self.signer().loads(token,max_age=MAX_FIX_AGE)
        except BadData: return False
        grant=self.grant(survivor)
        return bool(grant) and value == {'owner':survivor.id,'grant':grant,'device':self.device_binding()}


class AlertLocationService:
    def __init__(self,conn): self.conn=conn

    def update(self,survivor,client_id,data,reauthorize):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',client_id): return {'error':'invalid_client_id'},400
        try: fix=validate_fix(data)
        except ValueError as error: return {'error':str(error)},400
        try:
            with self.conn:
                self.conn.execute('BEGIN IMMEDIATE')
                if not reauthorize(): return {'error':'device_pairing_required'},401
                repo=AlertRepository(self.conn)
                alert=repo.get_by_client_id(client_id)
                if alert is None or alert.user_id!=survivor.id: return {'error':'not_found'},404
                if not LocationPermission(self.conn).valid(survivor,data['location_consent_token']):
                    return {'error':'location_permission_required'},403
                if (datetime.now(timezone.utc)-timestamp(alert.created_at)).total_seconds()>600:
                    return {'error':'location_update_window_closed'},409
                if alert.location_recorded_at:
                    try: previous=timestamp(alert.location_recorded_at)
                    except ValueError: previous=None
                    incoming=timestamp(fix['location_recorded_at'])
                    if previous and incoming<=previous:
                        same=incoming==previous and (alert.lat,alert.lng,alert.location_accuracy)==(fix['lat'],fix['lng'],fix['location_accuracy'])
                        return ({'id':alert.id,'client_id':client_id,'updated':False},200) if same else ({'error':'location_update_out_of_order'},409)
                repo.update_location(alert.id,survivor.id,fix)
                AuditRepository(self.conn).log(f'survivor {survivor.case_code}','alert_location_updated',survivor.case_code,f'alert {alert.id}',commit=False)
                return {'id':alert.id,'client_id':client_id,'updated':True},200
        except sqlite3.Error:
            return {'error':'location_storage_unavailable'},503
