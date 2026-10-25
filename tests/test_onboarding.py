"""Synthetic account setup: authenticated, additive, atomic and replay-safe."""
import sqlite3
import unittest
from unittest.mock import patch

import test_avenra as fixtures
import test_hosted_pwa_contract as hosted


class OnboardingTests(unittest.TestCase):
    setUp = fixtures.avenraStagesTestCase.setUp
    tearDown = fixtures.avenraStagesTestCase.tearDown
    _login_staff = fixtures.avenraStagesTestCase._login_staff
    invite = hosted.HostedPWAContractTests.invite
    enroll = hosted.HostedPWAContractTests.enroll

    def save(self, data):
        return self.client.post('/api/onboarding', json=data, headers=self.survivor_headers)

    def details(self):
        return self.client.get('/api/onboarding', headers=self.survivor_headers)

    def test_private_device_required_and_responses_never_cached(self):
        self.assertEqual(self.client.get('/api/onboarding').status_code, 401)
        self.assertEqual(self.client.post('/api/onboarding', json={}).status_code, 401)
        self._login_staff()
        self.assertEqual(self.client.get('/api/onboarding').status_code, 401)
        self.assertIn('no-store', self.details().headers['Cache-Control'])

    def test_name_and_additions_preserve_existing_contacts_and_ids(self):
        before = self.details().json['contacts']
        response = self.save({'name': ' Fictional Nickname ', 'contacts': [
            {'name': 'Fictional contact', 'phone': '0821234567'},
        ]})
        self.assertEqual(response.status_code, 200, response.json)
        after = self.details().json
        self.assertEqual(after['name'], 'Fictional Nickname')
        self.assertTrue(all(row in after['contacts'] for row in before))
        self.assertEqual(len(after['contacts']), len(before) + 1)
        self.assertTrue(all('phone' not in row for row in after['contacts']))

    def test_retry_does_not_duplicate_or_replace_existing_contacts(self):
        payload = {'name': 'Fictional Name', 'contacts': [{'name': 'New Contact', 'phone': '0821234567'}]}
        self.assertEqual(self.save(payload).status_code, 200)
        before = self.details().json
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual(self.details().json, before)

    def test_invalid_fields_and_contacts_do_not_change_name_or_contacts(self):
        before = self.details().json
        for payload in [
            {'name': 'Changed', 'contacts': [{'name': 'Bad', 'phone': '123'}]},
            {'name': ''}, {'name': 'x' * 61}, {'name': 'bad\nname'},
            {'name': 4}, {'user_id': 999, 'name': 'Changed'},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.save(payload).status_code, 400)
                self.assertEqual(self.details().json, before)

    def test_storage_failure_rolls_back_name_and_contacts(self):
        before = self.details().json
        with patch('avenra.services.onboarding_service.AuditRepository.log', side_effect=sqlite3.OperationalError('fixture')):
            response = self.save({'name': 'Changed', 'contacts': [{'name': 'New Contact', 'phone': '0821234567'}]})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.details().json, before)

    def test_cross_origin_setup_is_rejected(self):
        headers = dict(self.survivor_headers, Origin='https://elsewhere.invalid')
        self.assertEqual(self.client.post('/api/onboarding', json={'name': 'Changed'}, headers=headers).status_code, 403)

    def test_paired_cookie_requires_origin_and_updates_only_its_owner(self):
        phone, _ = self.enroll(self.invite())
        before = self.details().json
        self.assertEqual(phone.post('/api/onboarding', json={'name': 'Fictional Paired User'}).status_code, 403)
        response = phone.post('/api/onboarding', json={'name': 'Fictional Paired User'}, headers={'Origin': 'http://localhost'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(phone.get('/api/onboarding').json['name'], 'Fictional Paired User')
        self.assertEqual(self.details().json, before)

    def test_audit_does_not_include_names_or_numbers(self):
        self.assertEqual(self.save({'name': 'Private Fictional Name', 'contacts': [
            {'name': 'Private Fictional Contact', 'phone': '0821234567'}
        ]}).status_code, 200)
        conn = fixtures.db.connect()
        try:
            row = conn.execute("SELECT detail FROM audit_log WHERE action='onboarding_saved' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertNotIn('Private Fictional', row['detail'])
            self.assertNotIn('0821234567', row['detail'])
        finally:
            conn.close()
