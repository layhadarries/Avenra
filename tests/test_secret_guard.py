"""Exercise real secret scanning against disposable Git repositories only."""
import base64
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.check_secrets import ROOT, ScanError, private_artifact, push_revisions, scan
from tools.install_gitleaks import scanner_binary, verified_bytes


class SecretGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = scanner_binary(ROOT)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='avenra-guard-test-')
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fictional scanner fixture')
        self.git('config', 'user.email', 'scanner@example.invalid')
        self.git('config', 'core.hooksPath', '/dev/null')
        self.git('config', 'commit.gpgSign', 'false')
        self.write('README.md', 'Fictional repository.\n')
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'Fictional fixture')

    def check(self, **kwargs):
        return scan(self.repo, binary=self.binary, **kwargs)[0]

    def token(self):
        # Deliberately fictional, assembled to avoid committing a token-shaped literal.
        return 'gh' + 'p_' + 'Q7w9E2r4T6y8U1i3O5p7A9s2D4f6G8h1J3k5'

    def test_staged_bytes_are_checked_even_when_working_file_is_clean(self):
        self.write('settings.py', 'value = "' + self.token() + '"\n')
        self.git('add', 'settings.py')
        self.write('settings.py', '# A clean working copy must not hide the staged token.\n')
        findings = self.check(staged=True)
        self.assertTrue(any(item['file'] == 'settings.py' for item in findings))
        self.assertNotIn(self.token(), str(findings))

    def test_removed_private_files_still_fail_history_and_other_push_refs(self):
        self.git('checkout', '-qb', 'fixture-leak')
        self.write('.env.local', 'FICTIONAL=placeholder\n')
        self.commit()
        self.git('rm', '-q', '.env.local')
        self.commit()
        tip = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'HEAD~2')
        self.assertEqual(self.check(revision='HEAD'), [])
        revisions = push_revisions(['refs/heads/fixture-leak ' + tip + ' refs/heads/fixture-leak ' + '0' * 40])
        findings = self.check(revision=revisions[0])
        self.assertTrue(any(item['file'] == '.env.local' for item in findings))

    def test_tokens_in_lockfiles_and_encoded_values_are_not_skipped(self):
        encoded = base64.b64encode(self.token().encode()).decode()
        self.write('package-lock.json', '{"fixture": "' + self.token() + '"}\n')
        self.write('encoded.txt', 'fixture=' + encoded + '\n')
        self.git('add', '-A')
        files = {item['file'] for item in self.check(staged=True)}
        self.assertIn('package-lock.json', files)
        self.assertIn('encoded.txt', files)

    def test_private_keys_and_inline_suppressions_cannot_pass(self):
        header = '-----BEGIN ' + 'ENCRYPTED PRIVATE KEY-----'
        self.write('notes.txt', header + '\nfictional bytes\n')
        self.write('other.py', 'value = "' + self.token() + '" # gitleaks:allow\n')
        self.git('add', '-A')
        findings = self.check(staged=True)
        self.assertTrue(any(item['file'] == 'notes.txt' for item in findings))
        self.assertTrue(any(item['file'] == 'other.py' for item in findings))
        self.assertNotIn(self.token(), str(findings))

    def test_private_artifacts_and_public_certificate_boundary(self):
        for name in ('.env.local', 'nested/.env', 'uploads/photo.png', 'backup.zip',
                     'state.sqlite3', 'storage-state.json', 'private.key', 'bundle.p12'):
            with self.subTest(name=name):
                self.assertIsNotNone(private_artifact(name))
        self.assertEqual(private_artifact('renamed.txt', b'SQLite format 3\x00'), 'database-dump')
        self.assertEqual(private_artifact('dump.txt', b'--\n-- PostgreSQL database dump\n'), 'database-dump')
        self.write('.env.example', 'DATABASE_URL=\n')
        self.write('certificates/root.crt', (ROOT / 'certificates/supabase-root.crt').read_text())
        self.git('add', '-A')
        self.assertEqual(self.check(staged=True), [])

    def test_unscanned_symlinks_and_incomplete_history_fail(self):
        (self.repo / 'reference').symlink_to('README.md')
        self.git('add', 'reference')
        self.assertTrue(any(item['rule'] == 'unscanned-symlink-or-submodule' for item in self.check(staged=True)))
        head = self.git('rev-parse', 'HEAD')
        (self.repo / '.git/shallow').write_text(head + '\n')
        with self.assertRaises(ScanError):
            self.check(revision='HEAD')

    def test_scanner_integrity_and_push_input_fail_closed(self):
        with self.assertRaises(ValueError):
            verified_bytes(b'not the pinned scanner archive')
        with self.assertRaises(ScanError):
            push_revisions(['refs/heads/main --all refs/heads/main ' + '0' * 40])
        self.assertEqual(push_revisions(['delete ' + '0' * 40 + ' remote ' + 'a' * 40]), [])


if __name__ == '__main__':
    unittest.main()
