"""Keyed identifiers and separate account/address limits for public identity flows."""
import hashlib
import hmac
import time
from flask import current_app, request
from avenra.repositories.abuse_repository import AbuseRepository


class AbuseService:
    def __init__(self, conn):
        self.repo = AbuseRepository(conn)

    def allow(self, purpose, identity, maximum):
        def bucket(value):
            return purpose + ':' + hmac.new(current_app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
        return self.repo.allow([
            (bucket('identity:'+identity[:254].strip().lower()), maximum),
            (bucket('address:'+(request.remote_addr or 'unknown')), 60),
        ], int(time.time()))

    def allow_public(self, purpose, maximum):
        value = purpose + ':' + hmac.new(current_app.secret_key.encode(),
            (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
        return self.repo.allow([(value, maximum)], int(time.time()))
