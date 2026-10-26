"""Hybrid alert encryption: public-key capture, server-only retained private keys."""
import base64
import hashlib
import json
import re
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FIELDS = frozenset(('version','kid','owner_id','iv','wrapped_key','ciphertext'))
PAYLOAD_FIELDS = frozenset(('client_id','client_ts','lat','lng','location_accuracy',
                            'location_recorded_at','location_consent_token'))
LEGACY_DIARY_FIELDS = frozenset(('client_id','owner_id','contract_version','note','photo_data','_vault_photo',
    'note_sha256','photo_sha256','file_hash','entry_fingerprint','shared','has_photo','captured_at','created_at','status','last_error'))


class QueueSealingKeys:
    def __init__(self, environ, required=False):
        self.keys={}
        self.active=None
        primary=environ.get('OFFLINE_QUEUE_PRIVATE_KEY_PEM')
        try:
            retired=json.loads(environ.get('OFFLINE_QUEUE_RETIRED_KEYS_JSON','[]'))
            if not isinstance(retired,list) or len(retired)>5: raise ValueError()
            if required and not primary: raise ValueError()
            for index,pem in enumerate(([primary] if primary else [])+retired):
                if not isinstance(pem,str) or len(pem)>16384: raise ValueError()
                key=serialization.load_pem_private_key(pem.encode(),password=None)
                if not isinstance(key,rsa.RSAPrivateKey) or key.key_size not in (3072,4096) or key.public_key().public_numbers().e!=65537:
                    raise ValueError()
                public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
                kid=hashlib.sha256(public).hexdigest()
                self.keys[kid]=key
                if primary and index==0: self.active={'kid':kid,'spki':base64.b64encode(public).decode()}
        except (ValueError,TypeError):
            raise RuntimeError('Configure valid, separately held offline queue RSA keys (3072/4096 bits)') from None

    def __repr__(self):
        return '<QueueSealingKeys private material redacted>'

    def public(self):
        return self.active

    def decrypt(self, owner, client_id, envelope, purpose='alert',allowed_fields=PAYLOAD_FIELDS,budget=16384):
        if not isinstance(envelope,dict) or set(envelope)!=FIELDS:
            raise ValueError('invalid_sealed_alert')
        if type(envelope['owner_id']) is not int or envelope['owner_id']!=owner or type(envelope['version']) is not int or envelope['version']!=1:
            raise ValueError('invalid_sealed_alert')
        kid=envelope['kid']
        if not isinstance(kid,str) or not re.fullmatch(r'[a-f0-9]{64}',kid): raise ValueError('invalid_sealed_alert')
        if not isinstance(client_id,str) or not 1<=len(client_id)<=64 or client_id!=client_id.strip(): raise ValueError('invalid_sealed_alert')
        def decoded(name,maximum):
            value=envelope[name]
            if not isinstance(value,str) or len(value)>maximum*2: raise ValueError('invalid_sealed_alert')
            raw=base64.b64decode(value,validate=True)
            if len(raw)>maximum: raise ValueError('invalid_sealed_alert')
            return raw
        try:
            nonce=decoded('iv',12); wrapped=decoded('wrapped_key',512); ciphertext=decoded('ciphertext',budget)
            if len(nonce)!=12 or len(ciphertext)<16: raise ValueError()
            key=self.keys.get(kid)
            if key is None: raise RuntimeError('sealing_key_unavailable')
            if len(wrapped)!=key.key_size//8: raise ValueError()
            aes_key=key.decrypt(wrapped,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
            aad=json.dumps([1,owner,client_id,purpose],ensure_ascii=False,separators=(',',':')).encode()
            payload=json.loads(AESGCM(aes_key).decrypt(nonce,ciphertext,aad))
            if not isinstance(payload,dict) or set(payload)-allowed_fields or payload.get('client_id')!=client_id: raise ValueError()
            return payload
        except (ValueError,TypeError,InvalidTag,UnicodeError):
            raise ValueError('invalid_sealed_alert') from None

    def recover_diary(self, owner, client_id, envelope):
        return self.decrypt(owner,client_id,envelope,purpose='legacy-diary',allowed_fields=LEGACY_DIARY_FIELDS,budget=6*1024*1024)
