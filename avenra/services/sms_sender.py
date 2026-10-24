"""Explicit Twilio SMS adapter. No retries, redirects, or channel fallback."""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from flask import current_app, has_app_context

class SenderConfigurationError(ValueError):
    pass

class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class TwilioSender:
    def __init__(self, environ, opener=None):
        self.enabled = environ.get('AVENRA_SMS_ENABLED') == '1'
        if not self.enabled or environ.get('APP_ENV') not in {'development', 'production'}:
            raise SenderConfigurationError('SMS requires explicit enablement outside evaluation.')
        self.account = environ.get('TWILIO_ACCOUNT_SID', '')
        self.token = environ.get('TWILIO_AUTH_TOKEN', '')
        self.number = environ.get('TWILIO_FROM_NUMBER', '') or environ.get('TWILIO_FROM', '')
        if not re.fullmatch(r'AC[0-9a-fA-F]{32}', self.account):
            raise SenderConfigurationError('Invalid or missing SMS account configuration.')
        if not isinstance(self.token, str) or not 1 <= len(self.token) <= 256:
            raise SenderConfigurationError('Invalid or missing SMS credential configuration.')
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}', self.number):
            raise SenderConfigurationError('Invalid or missing SMS sender configuration.')
        self.opener = opener or urllib.request.build_opener(NoRedirects())

    def __repr__(self):
        return '<TwilioSender credentials=redacted>'

    def __call__(self, *, name, phone, message, case_code):
        if has_app_context() and current_app.config.get('EVALUATION_MODE'):
            return {'outcome': 'failed', 'reason': 'evaluation_disabled'}
        if not isinstance(phone, str) or not re.fullmatch(r'\+27[1-9][0-9]{8}', phone):
            return {'outcome': 'failed', 'reason': 'invalid_recipient'}
        if not isinstance(message, str) or not message.strip() or len(message) > 1000:
            return {'outcome': 'failed', 'reason': 'invalid_message'}
        body = urllib.parse.urlencode({'To': phone, 'From': self.number, 'Body': message}).encode()
        request = urllib.request.Request(
            f'https://api.twilio.com/2010-04-01/Accounts/{self.account}/Messages.json',
            data=body, method='POST', headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
                'Authorization': 'Basic ' + base64.b64encode(
                    (self.account + ':' + self.token).encode()
                ).decode('ascii'),
            },
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                status = response.status
                raw = response.read(65537)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return {'outcome': 'failed' if code in {400, 401, 403, 404, 422} else 'unknown',
                    'reason': 'provider_rejected' if code in {400, 401, 403, 404, 422} else 'provider_uncertain'}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {'outcome': 'unknown', 'reason': 'transport_uncertain'}
        if not 200 <= status < 300 or len(raw) > 65536:
            return {'outcome': 'unknown', 'reason': 'invalid_response'}
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            return {'outcome': 'unknown', 'reason': 'invalid_response'}
        if not isinstance(result, dict):
            return {'outcome': 'unknown', 'reason': 'invalid_response'}
        sid = result.get('sid')
        if not isinstance(sid, str) or not re.fullmatch(r'SM[0-9a-fA-F]{32}', sid):
            return {'outcome': 'unknown', 'reason': 'invalid_response'}
        state = result.get('status')
        if state in {'accepted', 'scheduled', 'queued', 'sending', 'sent'}:
            outcome, reason = 'accepted', 'provider_accepted'
        elif state in {'failed', 'undelivered', 'canceled'}:
            outcome, reason = 'failed', 'provider_rejected'
        else:
            outcome, reason = 'unknown', 'provider_uncertain'
        return {'outcome': outcome, 'reason': reason, 'provider_message_id': sid}
