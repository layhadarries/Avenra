"""Narrow paired-survivor vault authority; never used by the emergency queue."""
import sqlite3
import base64
import json
from flask import jsonify, request, current_app
import db
from avenra.security import device_user
from avenra.services.vault_service import VaultService, HEADER


def register_vault(app):
    @app.get('/api/vault')
    def vault_status():
        survivor=device_user()
        if survivor is None: return jsonify(error='device_pairing_required'),401
        service=VaultService(db.get_db())
        return jsonify(configured=service.repo.credential(survivor.id) is not None,
            unlocked=service.authorized(survivor,request.cookies.get('avenra_device',''),request.headers.get(HEADER)))

    @app.post('/api/vault/<action>')
    def survivor_vault(action):
        if action not in {'setup','unlock','lock','recover'}: return jsonify(error='not_found'),404
        survivor=device_user()
        if survivor is None: return jsonify(error='device_pairing_required'),401
        service=VaultService(db.get_db())
        device=request.cookies.get('avenra_device','')
        try:
            if action=='recover':
                if not service.authorized(survivor,device,request.headers.get(HEADER)):
                    return jsonify(error='vault_unlock_required'),423
                if request.mimetype=='multipart/form-data':
                    if set(request.form)!={'client_id','envelope'} or set(request.files)!={'payload'} or any(len(request.form.getlist(name))!=1 for name in request.form) or len(request.files.getlist('payload'))!=1:
                        return jsonify(error='invalid_legacy_record'),400
                    envelope=json.loads(request.form['envelope'])
                    if not isinstance(envelope,dict) or 'ciphertext' in envelope: return jsonify(error='invalid_legacy_record'),400
                    envelope['ciphertext']=base64.b64encode(request.files['payload'].stream.read(6*1024*1024)).decode()
                    data={'client_id':request.form['client_id'],'sealed_payload':envelope}
                else: data=request.get_json(silent=True)
                body,status=service.recover(survivor,data,current_app.config['OFFLINE_QUEUE_KEYS'])
                return jsonify(body),status
            if action=='lock':
                service.lock(survivor,device,request.headers.get(HEADER))
                response=jsonify(unlocked=False)
                # No Set-Cookie here: a delayed exit response must not erase a
                # newer unlock. The exact old in-memory grant is revoked server-side.
                return response
            body,status,token=service.unlock(survivor,device,request.get_json(silent=True),setup=action=='setup')
            if token:
                body=dict(body,unlock_token=token)
            response=jsonify(body); response.status_code=status
            return response
        except sqlite3.Error:
            return jsonify(error='vault_storage_unavailable'),503
        except (ValueError,TypeError):
            return jsonify(error='invalid_legacy_record'),400
        except RuntimeError:
            return jsonify(error='sealing_key_unavailable'),503
