"""No real messages: transport is always mocked."""
import contextlib
import importlib
import io
import json
import unittest
import urllib.error


class SMSGatewayTests(unittest.TestCase):
    def setUp(self):
        self.sms = importlib.import_module('tools.sms_test')
        self.env = {'TWILIO_ACCOUNT_SID': 'AC' + 'a' * 32,
                    'TWILIO_AUTH_TOKEN': 'secret-that-must-not-be-printed',
                    'TWILIO_FROM_NUMBER': '+15005550006',
                    'TEST_RECIPIENT_PHONE': '+27821234567'}
        self.calls = []

    def opener(self, payload):
        calls = self.calls
        class FakeOpener:
            def open(self, request, timeout):
                calls.append(request)
                return io.BytesIO(json.dumps(payload).encode())
        return FakeOpener()

    def run_tool(self, args, env=None, opener=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.sms.main(args, environ=self.env if env is None else env, opener=opener)
        text = output.getvalue()
        self.assertNotIn(self.env['TWILIO_AUTH_TOKEN'], text)
        self.assertNotIn(self.env['TEST_RECIPIENT_PHONE'], text)
        return code, text

    def test_default_dry_run_has_no_network_or_credential_requirement(self):
        code, text = self.run_tool([], env={}, opener=self.opener({}))
        self.assertEqual(code, 0)
        self.assertIn('DRY RUN', text)
        self.assertEqual(self.calls, [])

    def test_missing_credentials_cannot_send(self):
        code, _ = self.run_tool(['--send'], env={}, opener=self.opener({}))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_invalid_south_african_number_cannot_send(self):
        env = dict(self.env, TEST_RECIPIENT_PHONE='+44000000000')
        code, _ = self.run_tool(['--send'], env=env, opener=self.opener({}))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_provider_queued_is_not_reported_as_delivery(self):
        code, text = self.run_tool(['--send'], opener=self.opener({'sid': 'SM' + 'b'*32, 'status': 'queued'}))
        self.assertEqual(code, 0)
        self.assertIn('delivery unconfirmed', text)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0].full_url.startswith('https://api.twilio.com/'))
        self.assertEqual(self.calls[0].method, 'POST')

    def test_status_check_does_not_send_another_message(self):
        code, text = self.run_tool(['--status', 'SM' + 'b'*32], opener=self.opener({'sid': 'SM' + 'b'*32, 'status': 'delivered'}))
        self.assertEqual(code, 0)
        self.assertIn('provider reports delivered', text)
        self.assertEqual(self.calls[0].method, 'GET')

    def test_undelivered_is_a_failure(self):
        code, text = self.run_tool(['--status', 'SM' + 'b'*32], opener=self.opener({'sid': 'SM' + 'b'*32, 'status': 'undelivered'}))
        self.assertEqual(code, 1)
        self.assertIn('undelivered', text)

    def test_invalid_message_sid_is_rejected_before_network(self):
        code, _ = self.run_tool(['--status', '../another-account'], opener=self.opener({}))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_provider_error_body_and_auth_are_not_printed(self):
        secret = self.env['TWILIO_AUTH_TOKEN']
        class ErrorOpener:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 401, 'Denied', {}, io.BytesIO(secret.encode()))
        code, text = self.run_tool(['--send'], opener=ErrorOpener())
        self.assertEqual(code, 1)
        self.assertIn('401', text)


if __name__ == '__main__':
    unittest.main()
