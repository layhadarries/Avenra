"""Referral retries must recheck consent before returning existing data."""
import unittest
from contextlib import closing

import test_avenra
import test_referral_requests as fixtures


class ReferralRetryConsentTests(unittest.TestCase):
    setUp = fixtures.ReferralRequestTests.setUp
    tearDown = fixtures.ReferralRequestTests.tearDown
    _login_staff = fixtures.ReferralRequestTests._login_staff
    _staff_post = fixtures.ReferralRequestTests._staff_post
    request_referral = fixtures.ReferralRequestTests.request_referral

    def withdraw(self):
        response = self.client.post('/api/consents', headers=self.survivor_headers,
                                    json={'item': 'shelter_referral_sharing', 'active': False})
        self.assertEqual(response.status_code, 200)

    def test_same_request_after_withdrawal_returns_no_referral(self):
        self.assertEqual(self.request_referral().status_code, 201)
        self.withdraw()
        response = self.request_referral()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json, {'error': 'referral_consent_required'})

    def test_other_shelter_retry_after_withdrawal_does_not_reveal_active_referral(self):
        self.assertEqual(self.request_referral().status_code, 201)
        self.withdraw()
        with closing(test_avenra.db.connect()) as conn:
            other = conn.execute('SELECT id FROM shelters WHERE id != ? LIMIT 1', (self.shelter_id,)).fetchone()[0]
        response = self._staff_post('/api/referrals', json={'alert_id': self.alert_id, 'shelter_id': other})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json, {'error': 'referral_consent_required'})

    def test_regrant_restores_idempotent_receipt_without_duplicate(self):
        original = self.request_referral().json['referral']['id']
        self.withdraw()
        self.assertEqual(self.request_referral().status_code, 403)
        response = self.client.post('/api/consents', headers=self.survivor_headers,
                                    json={'item': 'shelter_referral_sharing', 'active': True})
        self.assertEqual(response.status_code, 200)
        retry = self.request_referral()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json['referral']['id'], original)
        self.assertTrue(retry.json['already'])
        with closing(test_avenra.db.connect()) as conn:
            count = conn.execute('SELECT COUNT(*) FROM referrals WHERE alert_id=?', (self.alert_id,)).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
