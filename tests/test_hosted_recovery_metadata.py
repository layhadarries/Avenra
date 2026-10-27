"""Recovery inventory checks use fictional exports and never contact a provider."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_hosted_recovery import fetch_metadata, main, summarize


class HostedRecoveryMetadataTests(unittest.TestCase):
    def metadata(self):
        return {'pitr_enabled': True, 'walg_enabled': True,
                'backups': [{'status': 'COMPLETED', 'inserted_at': '2026-10-27T10:00:00Z',
                             'private_provider_field': 'fictional-sensitive-value'}],
                'physical_backup_data': {'earliest_physical_backup_date_unix': 1793008800,
                                         'latest_physical_backup_date_unix': 1793095200}}

    def test_metadata_never_attests_a_restore_or_measured_recovery(self):
        report = summarize(self.metadata())
        self.assertTrue(report['backup_availability_observed'])
        self.assertTrue(report['pitr_enabled'])
        self.assertFalse(report['recovery_verified'])
        self.assertEqual(report['restore_drill'], 'not_performed')
        self.assertIsNone(report['measured_rpo_seconds'])
        self.assertIsNone(report['measured_rto_seconds'])
        self.assertNotIn('fictional-sensitive-value', json.dumps(report))

    def test_missing_inventory_or_invalid_window_cannot_pass(self):
        invalid = [None, {}, {'pitr_enabled': True, 'walg_enabled': True}]
        for field, value in (('pitr_enabled', 'true'), ('backups', {}),
                             ('physical_backup_data', {'earliest_physical_backup_date_unix': 20,
                                                       'latest_physical_backup_date_unix': 10})):
            document = self.metadata()
            document[field] = value
            invalid.append(document)
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ValueError):
                summarize(document)

    def test_enabled_pitr_without_backup_data_is_not_availability_evidence(self):
        report = summarize({'pitr_enabled': True, 'walg_enabled': True, 'backups': []})
        self.assertFalse(report['backup_availability_observed'])
        self.assertFalse(report['recovery_verified'])

    def test_export_is_offline_and_output_excludes_unrecognized_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private-export.json'
            path.write_text(json.dumps(self.metadata()))
            output = io.StringIO()
            with patch('tools.check_hosted_recovery.build_opener') as transport, redirect_stdout(output):
                self.assertEqual(main(['--from-json', str(path)]), 0)
            transport.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(report['source'], 'operator_export')
            self.assertNotIn('fictional-sensitive-value', output.getvalue())

    def test_missing_credentials_fail_without_a_network_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('tools.check_hosted_recovery.build_opener') as transport:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['--project-ref', 'a' * 20]), 2)
            transport.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['metadata_status'], 'blocked')

    def test_provider_request_uses_get_verified_tls_and_refuses_redirects(self):
        payload = json.dumps(self.metadata()).encode()
        with patch('tools.check_hosted_recovery.build_opener') as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.read.return_value = payload
            self.assertEqual(fetch_metadata('a' * 20, 'fictional-token'), self.metadata())
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.full_url, 'https://api.supabase.com/v1/projects/' + 'a' * 20 + '/database/backups')
            redirect, https = factory.call_args.args
            self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://example.invalid'))
            self.assertTrue(https._context.check_hostname)


if __name__ == '__main__':
    unittest.main()
