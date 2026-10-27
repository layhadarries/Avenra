"""Install reviewed hashes, using pinned build tools for the http-ece source build."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCKS = {
    'runtime': 'requirements-lock.txt',
    'dev': 'requirements-dev-lock.txt',
    'security': 'requirements-security-lock.txt',
    'webpush': 'requirements-webpush.txt',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=LOCKS, default='runtime')
    args = parser.parse_args()
    # Do not inherit alternate indexes, trusted-host bypasses or hash overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PIP_')}
    env['PIP_CONFIG_FILE'] = os.devnull
    if os.environ.get('PIP_CERT'):
        env['PIP_CERT'] = os.environ['PIP_CERT']
    command = [sys.executable, '-m', 'pip', '--disable-pip-version-check',
               'install', '--no-cache-dir', '--require-hashes',
               '--index-url', 'https://pypi.org/simple']
    if args.profile != 'security':
        subprocess.run(command + ['-r', 'requirements-build-lock.txt'],
                       cwd=ROOT, env=env, check=True)
    subprocess.run(command + ['--no-build-isolation', '-r', LOCKS[args.profile]],
                   cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
