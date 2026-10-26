"""Server-verifiable survivor evidence unlock, separate from disguise PINs."""
import hashlib
import secrets
import time
from werkzeug.security import generate_password_hash, check_password_hash
from zxcvbn import zxcvbn
from avenra.repositories.vault_repository import VaultRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.services.abuse_service import AbuseService
from avenra.models.identifiers import valid_identifier

HEADER = 'X-Vault-Unlock'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class VaultService:
    def __init__(self, conn):
        self.conn=conn
        self.repo=VaultRepository(conn)

    def authorized(self, survivor, device, token):
        return isinstance(token,str) and len(token)==43 and self.repo.valid(survivor.id,digest(device),digest(token),int(time.time()))

    def unlock(self, survivor, device, body, setup=False):
        if not isinstance(body,dict) or set(body)-({'passphrase','confirmation'} if setup else {'passphrase'}):
            return {'error':'invalid_vault_fields'},400,None
        phrase=body.get('passphrase')
        if not isinstance(phrase,str) or not 15 <= len(phrase) <= 128:
            return {'error':'invalid_vault_passphrase'},400,None
        if not AbuseService(self.conn).allow('vault',str(survivor.id),8):
            return {'error':'too_many_attempts'},429,None
        if setup and (body.get('confirmation')!=phrase or zxcvbn(phrase)['score']<3):
            return {'error':'strong_passphrase_required'},400,None
        password_hash=generate_password_hash(phrase) if setup else None
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            row=self.repo.credential(survivor.id)
            if setup:
                if row is not None: return {'error':'vault_already_configured'},409,None
                self.repo.create(survivor.id,password_hash)
                version=1
            else:
                if row is None or not check_password_hash(row['passphrase_hash'],phrase):
                    return {'error':'vault_unlock_failed'},401,None
                version=row['credential_version']
            token=secrets.token_urlsafe(32)
            self.repo.grant(survivor.id,digest(device),digest(token),version,int(time.time()))
            AuditRepository(self.conn).log(f'survivor {survivor.case_code}',
                'vault_configured' if setup else 'vault_unlocked',survivor.case_code,commit=False)
            return {'unlocked':True,'expires_in':900},201 if setup else 200,token

    def lock(self, survivor, device, token):
        with self.conn:
            if isinstance(token,str) and len(token)==43:
                self.repo.revoke(survivor.id,digest(device),digest(token))

    def recover(self, survivor, body, keys):
        if not valid_identifier(survivor.id) or not isinstance(body,dict) or set(body)!={'client_id','sealed_payload'}:
            raise ValueError('invalid_legacy_record')
        if not AbuseService(self.conn).allow('vault-recovery',str(survivor.id),200):
            return {'error':'too_many_attempts'},429
        record=keys.recover_diary(survivor.id,body['client_id'],body['sealed_payload'])
        if type(record.get('owner_id')) is not int or record['owner_id']!=survivor.id: raise ValueError('invalid_legacy_owner')
        AuditRepository(self.conn).log(f'survivor {survivor.case_code}','vault_legacy_recovered',survivor.case_code,
            'Own offline record decoded for encrypted migration')
        return {'record':record},200
