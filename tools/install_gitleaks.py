"""Install the checksum-pinned scanner in Git's private metadata directory."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import ssl
import subprocess
import tarfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD = 32 * 1024 * 1024


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('Scanner download requires verified HTTPS')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def release():
    manifest = json.loads((ROOT / 'security/gitleaks-release.json').read_text())
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    target = platform.system().lower() + '_' + str(arch)
    if target not in manifest['archives']:
        raise ValueError('Pinned scanner supports Linux/macOS x64 and arm64')
    return manifest['version'], target, manifest['archives'][target]


def cache_directory(repo=ROOT):
    result = subprocess.run(['git', 'rev-parse', '--git-path', 'avenra-tools'],
                            cwd=repo, capture_output=True, check=True, text=True)
    path = Path(result.stdout.strip())
    return (path if path.is_absolute() else repo / path) / ('gitleaks-' + release()[0])


def verified_bytes(archive):
    if hashlib.sha256(archive).hexdigest() != release()[2]:
        raise ValueError('Scanner archive checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
        member = bundle.getmember('gitleaks')
        if not member.isfile() or member.size > 64 * 1024 * 1024:
            raise ValueError('Invalid scanner archive member')
        with bundle.extractfile(member) as stream:
            return stream.read()


def scanner_binary(repo=ROOT):
    directory = cache_directory(repo)
    binary = directory / 'gitleaks'
    archive = directory / 'release.tar.gz'
    if binary.is_symlink() or archive.is_symlink():
        raise ValueError('Scanner cache must not contain symlinks')
    if archive.stat().st_size > MAX_DOWNLOAD:
        raise ValueError('Scanner archive exceeds the size limit')
    expected = hashlib.sha256(verified_bytes(archive.read_bytes())).digest()
    if binary.stat().st_size > 64 * 1024 * 1024 or hashlib.sha256(binary.read_bytes()).digest() != expected:
        raise ValueError('Installed scanner differs from the pinned release')
    return binary.resolve()


def install(repo=ROOT):
    version, target, _ = release()
    directory = cache_directory(repo)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    archive = directory / 'release.tar.gz'
    if archive.exists():
        return scanner_binary(repo)
    url = f'https://github.com/gitleaks/gitleaks/releases/download/v{version}/gitleaks_{version}_{target}.tar.gz'
    opener = build_opener(HTTPSRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(url, timeout=60) as response:
        content = response.read(MAX_DOWNLOAD + 1)
    if len(content) > MAX_DOWNLOAD:
        raise ValueError('Scanner download exceeds the size limit')
    binary = verified_bytes(content)
    # Extract just the verified regular binary, never archive paths or links.
    for path, data, mode in ((directory / 'gitleaks', binary, 0o700), (archive, content, 0o600)):
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(mode)
    return scanner_binary(repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hooks', action='store_true', help='Enable the repository commit/push checks locally.')
    args = parser.parse_args()
    try:
        install()
        if args.hooks:
            current = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT,
                                     capture_output=True, text=True, check=False)
            if current.returncode not in (0, 1) or current.stdout.strip() not in ('', '.githooks'):
                raise ValueError('Existing hooksPath requires manual integration')
            hooks = subprocess.run(['git', 'rev-parse', '--git-path', 'hooks'], cwd=ROOT,
                                   capture_output=True, text=True, check=True)
            directory = Path(hooks.stdout.strip())
            if not directory.is_absolute():
                directory = ROOT / directory
            if not current.stdout.strip() and any((directory / name).exists() for name in ('pre-commit', 'pre-push')):
                raise ValueError('Existing Git hooks require manual integration')
            subprocess.run(['git', 'config', '--local', 'core.hooksPath', '.githooks'], cwd=ROOT, check=True)
        print('Pinned Gitleaks installed' + ('; commit and push checks enabled' if args.hooks else ''))
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError):
        parser.exit(1, 'Scanner setup failed; verify trusted CA/network access, cache integrity and existing hooks. No checks were bypassed.\n')


if __name__ == '__main__':
    main()
