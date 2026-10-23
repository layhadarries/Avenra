"""One-message Twilio verification. Default: dry run, no network.
--send requires environment credentials and a consenting +27 recipient.
--status checks an existing message without creating another.
"""
import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class GatewayError(Exception):
    pass


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, repr=False)
class Settings:
    sid: str
    token: str
    sender: str
    recipient: str

    @classmethod
    def from_environ(cls, environ):
        sid = environ.get('TWILIO_ACCOUNT_SID', '')
        token = environ.get('TWILIO_AUTH_TOKEN', '')
        sender = environ.get('TWILIO_FROM_NUMBER', '') or environ.get('TWILIO_FROM', '')
        recipient = environ.get('TEST_RECIPIENT_PHONE', '')
        if not all((sid, token, sender, recipient)):
            raise GatewayError('Missing TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER or TEST_RECIPIENT_PHONE.')
        if not re.fullmatch(r'AC[0-9a-fA-F]{32}', sid) or not 1 <= len(token) <= 256:
            raise GatewayError('Invalid account credentials format.')
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}', sender):
            raise GatewayError('Sender must be an E.164 number.')
        if not re.fullmatch(r'\+27[1-9][0-9]{8}', recipient):
            raise GatewayError('Recipient must be a consenting South African +27 number.')
        return cls(sid, token, sender, recipient)


def request_message(settings, message_sid=None, opener=None):
    if message_sid is not None and not re.fullmatch(r'SM[0-9a-fA-F]{32}', message_sid):
        raise GatewayError('Invalid Message SID.')
    url = f'https://api.twilio.com/2010-04-01/Accounts/{settings.sid}/Messages'
    if message_sid:
        url += '/' + message_sid
    url += '.json'
    payload = None if message_sid else urllib.parse.urlencode({
        'From': settings.sender, 'To': settings.recipient,
        'Body': 'Test message from a hackathon prototype. No action required.',
    }).encode()
    request = urllib.request.Request(url, data=payload, method='GET' if message_sid else 'POST')
    encoded = base64.b64encode(f'{settings.sid}:{settings.token}'.encode()).decode('ascii')
    request.add_header('Authorization', 'Basic ' + encoded)
    request.add_header('Accept', 'application/json')
    if payload is not None:
        request.add_header('Content-Type', 'application/x-www-form-urlencoded')
    opener = opener or urllib.request.build_opener(NoRedirects())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise GatewayError('Provider response too large.')
        result = json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        raise GatewayError(f"Provider rejected request (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GatewayError('Could not reach the provider. Creation is not automatically retried.') from None
    except (ValueError, UnicodeError):
        raise GatewayError('Invalid provider response.') from None
    if not isinstance(result, dict) or not isinstance(result.get('sid'), str):
        raise GatewayError('Invalid provider message identity.')
    if not re.fullmatch(r'SM[0-9a-fA-F]{32}', result['sid']):
        raise GatewayError('Invalid provider message identity.')
    if message_sid and result['sid'] != message_sid:
        raise GatewayError('Provider returned a different message identity.')
    if result.get('status') not in {'accepted', 'scheduled', 'queued', 'sending', 'sent',
                                    'delivered', 'undelivered', 'failed', 'canceled'}:
        raise GatewayError('Unknown provider message status.')
    return result


def main(argv=None, *, environ=None, opener=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--send', action='store_true', help='Send one billable SMS to the configured consenting recipient.')
    group.add_argument('--status', metavar='MESSAGE_SID', help='Check status; sends no new message.')
    args = parser.parse_args(argv)
    if not args.send and not args.status:
        print('DRY RUN: no message sent and no network request made. Delivery NOT TESTED.')
        return 0
    try:
        settings = Settings.from_environ(os.environ if environ is None else environ)
        result = request_message(settings, args.status, opener)
        status = result['status']
        print('Message SID:', result['sid'], '| status:', status)
        if status == 'delivered':
            print('provider reports delivered. Confirm receipt with the consenting recipient; this is not proof it was read.')
            return 0
        if status in {'failed', 'undelivered', 'canceled'}:
            print('Verification failed:', status)
            return 1
        print('Provider accepted/processed the request; delivery unconfirmed. Use --status MESSAGE_SID later.')
        return 0
    except GatewayError as error:
        print('Verification error:', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
