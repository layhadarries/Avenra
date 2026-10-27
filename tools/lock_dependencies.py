"""Record PyPI artifact hashes for reviewed exact pins without executing packages.

This is not a resolver. Fresh hash-checked installs and the runtime closure gate
must pass after regeneration. Existing versions are never upgraded implicitly.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPSConnection
import json
from pathlib import Path
import re
import ssl

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'runtime': ('requirements.in', 'requirements-lock.txt', None),
    'build': ('requirements-build.in', 'requirements-build-lock.txt', None),
    'dev': ('requirements-dev.in', 'requirements-dev-lock.txt', 'requirements-lock.txt'),
    'security': ('requirements-security.in', 'requirements-security-lock.txt', None),
    'webpush': ('requirements-webpush.in', 'requirements-webpush.txt', None),
}
SOURCE_ONLY = frozenset({'http-ece'})


def exact_pins(text):
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z0-9-]+)==([A-Za-z0-9_.+-]+)', line)
        if not match or match[1] in pins:
            raise ValueError('Inputs must contain unique canonical names and exact versions')
        pins[match[1]] = match[2]
    if not pins:
        raise ValueError('Empty dependency input')
    return pins


def artifact_hashes(name, version, context):
    connection = HTTPSConnection('pypi.org', context=context, timeout=30)
    try:
        connection.request('GET', f'/pypi/{name}/{version}/json', headers={'Accept': 'application/json'})
        with connection.getresponse() as response:
            if response.status != 200:
                raise ValueError('PyPI metadata lookup failed')
            payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError('PyPI metadata exceeds the read limit')
        document = json.loads(payload)
    finally:
        connection.close()
    info = document['info']
    canonical = re.sub(r'[-_.]+', '-', info['name']).lower()
    if canonical != name or info['version'] != version:
        raise ValueError('Package metadata does not match its exact pin')
    kind = 'sdist' if name in SOURCE_ONLY else 'bdist_wheel'
    hashes = set()
    for artifact in document['urls']:
        if artifact.get('yanked') or artifact['packagetype'] != kind:
            continue
        digest = artifact['digests']['sha256']
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid SHA-256 in package metadata')
        hashes.add(digest)
    if not hashes:
        raise ValueError('No permitted non-yanked artifacts for an exact pin')
    return sorted(hashes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, action='append')
    parser.add_argument('--check', action='store_true', help='Compare without writing locks.')
    args = parser.parse_args()
    profiles = args.profile or list(PROFILES)
    # Honors SSL_CERT_FILE for an operator-provided CA bundle; verification stays on.
    context = ssl.create_default_context()
    inputs = {profile: exact_pins((ROOT / PROFILES[profile][0]).read_text()) for profile in profiles}
    pins = sorted({pin for values in inputs.values() for pin in values.items()})
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(zip(pins, pool.map(lambda pin: artifact_hashes(*pin, context), pins)))
    for profile in profiles:
        source, destination, include = PROFILES[profile]
        lines = [f'# Generated from {source} by tools/lock_dependencies.py; review hash changes.',
                 '# Wheels only, except the explicitly permitted http-ece source archive.',
                 '--require-hashes', '--only-binary=:all:']
        if SOURCE_ONLY.intersection(inputs[profile]):
            lines.append('--no-binary=http-ece')
        if include:
            lines.append('-r ' + include)
        for name, version in sorted(inputs[profile].items()):
            lines.append('')
            lines.append(f'{name}=={version} \\')
            values = hashes[name, version]
            lines.extend('    --hash=sha256:' + value + (' \\' if index < len(values) - 1 else '')
                         for index, value in enumerate(values))
        content = '\n'.join(lines) + '\n'
        target = ROOT / destination
        if args.check:
            if target.read_text() != content:
                raise ValueError('Dependency lock differs: ' + destination)
        else:
            target.write_text(content)
        print(f'{destination}: {len(inputs[profile])} exact pins, SHA-256 hashes recorded')


if __name__ == '__main__':
    main()
