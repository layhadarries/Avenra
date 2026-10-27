# Hash-verified Python dependencies

## Installation

Use a fresh virtual environment and the shared installer:

```sh
python -m venv .venv
.venv/bin/python tools/install_dependencies.py
# Browser-test environment:
.venv/bin/python tools/install_dependencies.py --profile dev
```

For scanners, create a separate environment and use `--profile security`.
`--profile webpush` installs only the optional Web Push dependency set.
`make set-up`, the Render build profiles, the Vercel custom build command and CI
use this installer. `tools/prepare_vercel_config.py` preserves that build command.
Host-managed dependency-install steps and the deployed inventory still need to
be checked in the actual provider build logs; local installation is not hosted
deployment evidence.

The runtime, browser-test, security-tool and build-tool dependency closures have
exact version pins and SHA-256 artifact hashes. `requirements.txt`,
`requirements-dev.txt` and `requirements-security.txt` include their respective
locks. The runtime keeps the same 37 package versions as before this change.

Wheels are required except for `http-ece==1.2.1`, whose upstream release provides
only a source archive. Its source hash is locked. The installer first installs
hash-verified `pip`, `setuptools`, `wheel` and `packaging`, then builds with
`--no-build-isolation` so pip does not fetch an unpinned build backend. It disables
the wheel cache, enforces `--require-hashes`, uses the public PyPI index and removes
inherited pip index/hash/trusted-host overrides. An explicit `PIP_CERT` CA bundle
is supported; certificate and hostname verification stay enabled.

Direct `pip install -r requirements.txt` verifies application artifact hashes,
but it does not provision the pinned source-build tools. Use the installer for
the complete controlled build path. A fresh environment matters: pip does not
rehash an already-installed package merely because its version satisfies a pin.

## Updating locks

1. Edit the relevant `requirements*.in` file deliberately. These inputs contain
   the complete exact closure, including transitive dependencies. Keep versions
   shared between profiles aligned. Update security advisories and compatibility
   evidence as part of a version change.
2. Generate hashes over verified HTTPS:

   ```sh
   python tools/lock_dependencies.py
   python tools/security_gate.py --lock-check
   ```

   `--profile runtime` (or `build`, `dev`, `security`, `webpush`) limits generation.
   `--check` compares PyPI's current non-yanked artifact hashes without rewriting.
   `SSL_CERT_FILE` can specify a trusted CA bundle for the metadata lookup.
3. Review the input and lock diff. The generator never resolves new versions or
   imports/builds downloaded packages. It records all non-yanked wheel hashes for
   each exact release, plus the explicitly allowed `http-ece` source hash.
   Newly published artifacts or yanked artifacts therefore require a reviewed
   lock change; generation is not part of ordinary installation.
4. Install each affected profile in a fresh environment. Pip must resolve every
   active transitive dependency from an explicit hashed pin, and `pip check` must
   pass. The lock/declaration gate independently rejects malformed or missing
   hashes, duplicate package names, unsafe options and undeclared lock changes.
5. Run the affected regression tests and the runtime resolution/audit/SBOM gates
   in `.github/workflows/verify.yml`. CI's regression matrix covers Linux Python
   3.12 (the declared hosted version) and 3.14. Other platform/Python combinations
   are not established by this evidence, even where wheel hashes are available.

Hashes detect artifact changes relative to the reviewed lock. They do not prove
that an upstream release is harmless or independently attest its provenance.
Changes to Python, OS libraries, the bootstrap installer supplied with Python,
Node dependencies and provider build infrastructure require their own evidence.

## Local verification — 2026-10-27

- Fresh Linux/Python 3.14.8 development and security environments installed with
  hash verification and passed `pip check`. The development profile built
  `http-ece` with the pinned backend and disabled build isolation.
- The complete Python regression suite passed **536 tests in 690.639 seconds**
  in the fresh development environment with provider credentials removed.
  Existing resource warnings remained; no test failed.
- The first scanner install rejected an omitted transitive dependency,
  `filelock`; the corrected complete lock passed the fresh install.
- A genuine locked wheel passed an offline pip dry run. Altering its bytes or
  omitting its hash made pip reject it before installation.
- Runtime dependency resolution, vulnerability-report coverage and CycloneDX
  coverage matched all 37 runtime pins; the completed runtime audit reported no
  known vulnerabilities. This is a point-in-time advisory result.
- An additional audit matched all 67 unique runtime/development/security/build
  pins with no known vulnerabilities. With `pip-audit --disable-pip --no-deps`,
  pass all four lock paths explicitly: the runtime include inside the development
  lock was not traversed by this scanner mode, and the coverage check caught it.
- Lock regeneration in check mode, declaration/hash validation, configuration
  parsing and the static scan gate passed. The static report retained 59 findings
  under the existing reviewed-medium/informational-low policy.
- PyPI artifact metadata confirms compatible Python 3.12 Linux x86_64 wheels for
  the 36 wheel-based runtime packages. Python 3.12 is unavailable locally, so its
  execution checks remain for the CI matrix; they have not been claimed as run.
