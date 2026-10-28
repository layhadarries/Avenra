"""Reject credentials and private artifacts in exact staged/committed Git blobs.

Source, scanner output and reports stay in a private temporary directory. Output
contains only paths, line numbers and rule IDs, never matches or secret values.
"""
import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.install_gitleaks import scanner_binary

MAX_BLOB = 20 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
PRIVATE_DIRECTORIES = frozenset({
    '.aws', '.ssh', '.vercel', '.venv', 'venv', 'env', 'node_modules',
    'uploads', 'evaluation-uploads', 'backups', 'private-backups',
    'test-results', 'playwright-report', 'blob-report', 'security-reports',
})
PRIVATE_NAMES = frozenset({
    '.npmrc', '.pypirc', '.netrc', '.pgpass', '.my.cnf', 'credentials.json',
    'service-account.json', 'service_account.json', 'cookies.txt', 'cookies.json',
    'storage-state.json', 'storage_state.json', 'auth.json', 'runtime.fish',
    'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519',
})
PRIVATE_GLOBS = (
    '*.key', '*.p12', '*.pfx', '*.p8', '*.pkcs12', '*.jks', '*.keystore',
    '*.db', '*.db-*', '*.sqlite', '*.sqlite-*', '*.sqlite3', '*.sqlite3-*',
    '*.dump', '*.backup', '*.bak', '*.log', '*.tfstate', '*.tfstate.*',
    '*.zip', '*.tar', '*.tgz', '*.gz', '*.bz2', '*.xz', '*.7z', '*.rar',
)


class ScanError(Exception):
    """Content-free failure safe to show in CI."""


def git(repo, *args, input=None):
    result = subprocess.run(['git', *args], cwd=repo, input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise ScanError('Git data unavailable; scan refused')
    return result.stdout


def private_artifact(name, data=b''):
    path = PurePosixPath(name)
    parts = [part.lower() for part in path.parts]
    base = path.name.lower()
    if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in name:
        return 'unsafe-path'
    if any(part in PRIVATE_DIRECTORIES for part in parts[:-1]):
        return 'private-directory'
    if (base.startswith('.env') or base.endswith('.env')) and name != '.env.example':
        return 'environment-file'
    if base in PRIVATE_NAMES or any(fnmatch.fnmatchcase(base, pattern) for pattern in PRIVATE_GLOBS):
        return 'private-artifact'
    if data.startswith(b'SQLite format 3\x00') or re.search(rb'(?m)^-- PostgreSQL database dump\r?$', data[:4096]):
        return 'database-dump'
    return None


def entries(repo, revision=None):
    command = ('ls-tree', '-r', '-z', '--full-tree', revision) if revision else ('ls-files', '--stage', '-z')
    result = []
    for record in git(repo, *command).split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, middle, last = meta.decode('ascii').split()
        if revision:
            oid = last
        else:
            oid = middle
            if last != '0':
                raise ScanError('Unmerged index entries must be resolved before scanning')
        result.append((name.decode('utf-8'), mode, oid))
    return result


def history_entries(repo, revision):
    if git(repo, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise ScanError('Full history is required; fetch the complete repository before scanning')
    commits = git(repo, 'rev-list', revision).decode('ascii').splitlines()
    if not commits:
        raise ScanError('No commits available to scan')
    unique = set()
    for commit in commits:
        unique.update(entries(repo, commit))
    return sorted(unique)


def scan(repo, *, staged=False, revision='HEAD', binary=None):
    binary = binary or scanner_binary(ROOT)
    items = entries(repo) if staged else history_entries(repo, revision)
    findings = []
    mapping = {}
    total = 0
    with tempfile.TemporaryDirectory(prefix='avenra-secret-scan-') as temporary:
        private = Path(temporary)
        snapshot = private / 'blobs'
        snapshot.mkdir(mode=0o700)
        # Use Git object bytes, not working files (which may differ from the index).
        # Suffix every path so scanner defaults cannot silently skip lockfiles/SVGs.
        for name, mode, oid in items:
            rule = private_artifact(name)
            if mode not in ('100644', '100755'):
                rule = 'unscanned-symlink-or-submodule'
            if rule:
                findings.append({'file': name, 'rule': rule})
                continue
            size = int(git(repo, 'cat-file', '-s', oid))
            if size > MAX_BLOB:
                findings.append({'file': name, 'rule': 'file-exceeds-scan-limit'})
                continue
            total += size
            if total > MAX_TOTAL:
                raise ScanError('History exceeds the scan budget; a complete review is required')
            data = git(repo, 'cat-file', 'blob', oid)
            rule = private_artifact(name, data)
            if rule:
                findings.append({'file': name, 'rule': rule})
                continue
            relative = oid + '/' + name + '.scan'
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if data.startswith((b'\xff\xfe', b'\xfe\xff')):
                data = data.decode('utf-16').encode('utf-8')
            target.write_bytes(data)
            mapping[relative] = name
        report = private / 'findings.json'
        env = {key: value for key, value in os.environ.items() if not key.startswith('GITLEAKS_')}
        command = [str(binary), 'dir', str(snapshot), '--config', str(ROOT / 'security/secret-scanner.toml'),
                   '--redact=100', '--no-banner', '--log-level=error', '--exit-code=10',
                   '--ignore-gitleaks-allow', '--gitleaks-ignore-path', str(private / 'no-ignores'),
                   '--max-decode-depth=2', '--report-format=json', '--report-path', str(report)]
        result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=240, check=False)
        if result.returncode not in (0, 10) or not report.is_file():
            raise ScanError('Credential scanner failed; sharing is blocked')
        records = json.loads(report.read_text())
        if not isinstance(records, list) or (result.returncode == 10 and not records):
            raise ScanError('Credential scanner returned an incomplete report')
        for record in records:
            location = Path(record['File'])
            relative = str(location.relative_to(snapshot)) if location.is_absolute() else location.as_posix()
            if relative not in mapping or not isinstance(record['StartLine'], int):
                raise ScanError('Credential scanner returned an unknown location')
            rule = record['RuleID']
            if not re.fullmatch(r'[a-z0-9-]+', rule):
                raise ScanError('Credential scanner returned an invalid rule')
            findings.append({'file': mapping[relative], 'line': record['StartLine'], 'rule': rule})
    # Several historic versions may contain the same finding; never output content.
    unique = {json.dumps(finding, sort_keys=True) for finding in findings}
    return [json.loads(value) for value in sorted(unique)], len(items)


def push_revisions(stream):
    revisions = []
    for line in stream:
        fields = line.split()
        if len(fields) != 4 or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', fields[1]):
            raise ScanError('Invalid Git push input; scan refused')
        if set(fields[1]) != {'0'}:
            revisions.append(fields[1])
    return list(dict.fromkeys(revisions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--staged', action='store_true')
    modes.add_argument('--history', action='store_true')
    modes.add_argument('--pre-push', action='store_true')
    args = parser.parse_args()
    try:
        revisions = push_revisions(sys.stdin) if args.pre_push else ['HEAD']
        binary = scanner_binary(ROOT)
        count = 0
        all_findings = []
        for revision in revisions:
            findings, checked = scan(ROOT, staged=args.staged, revision=revision, binary=binary)
            all_findings.extend(findings)
            count += checked
        for finding in all_findings[:100]:
            print(json.dumps(finding, sort_keys=True))
        if all_findings:
            print(f'Secret/privacy check failed: {len(all_findings)} findings. Values are hidden.', file=sys.stderr)
            return 1
        print(f'Secret/privacy check passed: {count} Git file versions checked')
        return 0
    except (ScanError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Secret/privacy scan unavailable or incomplete. Run make security-setup and use a full Git checkout; sharing is blocked.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
