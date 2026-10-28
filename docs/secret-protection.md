# Secret and private-file protection

## Local checks before sharing

Run once per clone (also included in `make set-up`):

```sh
make security-setup
```

This installs Gitleaks 8.30.1 from a SHA-256-pinned release and enables the tracked
`.githooks` directory. Existing custom hooks are preserved and require manual
integration. The scanner is stored under `.git/avenra-tools`, outside deployments.

- **Before commit:** scan the exact Git index, even when the working copy differs.
- **Before push:** scan the full reachable history of every ref being pushed,
  including secrets/files added and subsequently deleted.
- `make secrets-check` runs the staged and current-history checks manually.

Checks reject private environment files, key containers, database files/dumps,
backups/archives, uploads, browser authentication state, logs and scan artifacts.
The public `.env.example` and TLS CA certificate are allowed but still inspected.
Symlinks, submodules, oversized files, shallow history and scanner failures block
the check rather than silently reducing coverage.

Gitleaks' provider rules are extended for private-key headers, credentialed
database URLs and Supabase secrets. Git blobs are scanned under temporary names
so upstream filename exclusions cannot hide tokens inside lockfiles or SVGs.
Encoded text is decoded up to two levels. Inline suppression comments and local
ignore files cannot bypass the scan. The only added heuristic exceptions are
two exact, path-bound public code expressions documented in
`security/secret-scanner.toml`.

## Pipeline

The **Secret and private-file guard** job runs on every push, pull request and
manual workflow run, with full Git history and read-only repository permissions.
Regression and security jobs depend on it. Matches are never printed: only file
paths, line numbers and rule names are reported. Temporary reports are deleted;
no secret-scanner report is uploaded. Uploaded security artifacts are limited to
dependency/SBOM reports, not Bandit source snippets.

CI happens after a push. The local hooks provide the earlier check; also enable
GitHub **secret scanning/push protection** and require **Secret and private-file
guard** in the repository's branch/ruleset settings. Those hosted settings are
not changed by committing a workflow. Hooks can be bypassed, and pattern scans
cannot identify every private document, image, obfuscated secret or personal datum.

## When a check fails

Keep the reported value out of chat, logs and commits. Remove private files from
the index while retaining the local copy, and replace source credentials with
environment/secret-manager lookups. A secret committed earlier remains in history
after file deletion: revoke it and coordinate history cleanup before sharing.
Do not create a blanket baseline or exempt a whole test directory to make CI green.

Scanner updates require reviewing the pinned version and official release digests
in `security/gitleaks-release.json`, then exercising the focused guard tests.
Downloads use verified HTTPS; `SSL_CERT_FILE` can supply a trusted CA bundle.
