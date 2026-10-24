"""Web Push validation, key management and neutral payload policy."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

PROVIDERS=frozenset(('fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'))

class PushError(ValueError):
    def __init__(self,code='push_unavailable',status=400):self.code,self.status=code,status;super().__init__(code)

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')
def decode(value,length):
    if not isinstance(value,str) or len(value)>200 or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value):raise PushError('invalid_subscription')
    try:data=base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)
    except ValueError:raise PushError('invalid_subscription') from None
    if len(data)!=length:raise PushError('invalid_subscription')
    return data

def validate_subscription(value):
    if not isinstance(value,dict):raise PushError('invalid_subscription')
    endpoint=value.get('endpoint');keys=value.get('keys')
    if not isinstance(endpoint,str) or not 1<=len(endpoint)<=2048 or any(ord(c)<33 or ord(c)>126 for c in endpoint):raise PushError('invalid_subscription')
    try:url=urlsplit(endpoint);port=url.port
    except ValueError:raise PushError('invalid_subscription') from None
    if (url.scheme!='https' or url.hostname not in PROVIDERS or url.username is not None or
        url.password is not None or port not in (None,443) or url.fragment or not url.path or not isinstance(keys,dict)):
        raise PushError('invalid_subscription')
    point=decode(keys.get('p256dh'),65);decode(keys.get('auth'),16)
    from cryptography.hazmat.primitives.asymmetric import ec
    try:ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),point)
    except ValueError:raise PushError('invalid_subscription') from None
    return {'endpoint':endpoint,'keys':{'p256dh':keys['p256dh'],'auth':keys['auth']}}

def generate_keys(directory):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.fernet import Fernet
    directory=Path(directory).expanduser()
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    private=directory/'vapid-private.pem';storage=directory/'subscription-storage.key'
    if private.exists() or storage.exists():raise PushError('keys_already_exist')
    key=ec.generate_private_key(ec.SECP256R1())
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    for path,data in ((private,pem),(storage,Fernet.generate_key())):
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as handle:handle.write(data)

class PushSettings:
    def __init__(self,environ=None):
        environ=os.environ if environ is None else environ
        if environ.get('AVENRA_WEBPUSH_ENABLED')!='1':raise PushError('push_disabled',404)
        directory=Path(environ.get('WEBPUSH_KEY_DIR','')).expanduser()
        self.private=directory/'vapid-private.pem'
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization
        try:
            self.fernet=Fernet((directory/'subscription-storage.key').read_bytes())
            self.key=serialization.load_pem_private_key(self.private.read_bytes(),password=None)
            from cryptography.hazmat.primitives.asymmetric import ec
            if not isinstance(self.key,ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve,ec.SECP256R1):raise ValueError()
            raw=self.key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        except (OSError,ValueError,TypeError):raise PushError('push_configuration_unavailable',503) from None
        self.public=b64(raw)
        self.subject=environ.get('WEBPUSH_SUBJECT','')
        if not re.fullmatch(r'mailto:[^\s@]+@[^\s@]+',self.subject):raise PushError('push_subject_required',503)
    def encrypt(self,value):return self.fernet.encrypt(json.dumps(value,separators=(',',':')).encode()).decode()
    def decrypt(self,value):
        try:return validate_subscription(json.loads(self.fernet.decrypt(value.encode())))
        except Exception:raise PushError('subscription_unavailable',503) from None
    def __repr__(self):return '<PushSettings secrets=redacted>'
