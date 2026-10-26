# Stage 11 release controls (verification in progress)

Baseline: `c649c22` / `stage-10-complete`. Local fictional-data engineering only.
No deployment, provider change, hosted migration, message or invitation is performed.

## Browser hardening

- Application responses receive Content Security Policy: default deny, same-origin
  scripts plus SHA-256 hashes of trusted shipped inline scripts, no inline event
  handlers or eval, no frames/objects/base changes, same-origin forms/workers and
  manifests. Images permit local data/blob derivatives. Only the three existing
  weather API origins are additional connection destinations.
- Hashes are computed from shipped static files, **never untrusted rendered HTML**.
  Styles still permit existing inline CSS; no strict-style isolation is claimed.
  This does not protect against a compromised same-origin script/server or replace
  output escaping. Existing contact-push pages retain their stricter own policy.
- HTTPS responses add one-year HSTS; local HTTP does not. Existing secure-cookie,
  origin/CSRF, no-store, MIME and frame protections remain. Proxy/CDN and custom
  domain configuration must be verified separately during approved deployment.
- Inline navigation handlers moved into the public shell's fixed destination
  allowlist. Quick Exit remains direct. Shell cache v24 uses explicit activation;
  old already-cached HTML does not magically receive new response headers.
- The direct development server now binds loopback unless `HOST` is explicitly
  set. Gunicorn deployment commands are unchanged. Development debug remains
  forbidden outside the development configuration.
- The obsolete synchronous SMS webhook/Telegram compatibility function cannot
  send or fall back, regardless of old environment variables. Real dispatch stays
  exclusively in explicit outbox workers. No provider settings were changed.

## CI, dependency coverage and scan gates

`.github/workflows/verify.yml` defines unprivileged push/PR/manual regression and
security jobs. GitHub Actions are pinned to commit SHAs; checkout does not persist
credentials. Jobs use no repository/live credentials, no deployment command and
no `pull_request_target`. All databases/providers/browser state are isolated fixtures.
It runs Python/Node/browser checks and generates dependency/static artifacts with
14-day retention, never environment dumps, browser storage or application logs.
Remote execution/branch-protection status must be recorded separately; adding a
workflow is not proof that a hosted run succeeded or that merging is prohibited.

`requirements-lock.txt` supplies all **36 exact Linux/Python 3.14 runtime pins**,
including the binary psycopg dependency. A dry-run resolver checks closure against
both the lock and declarations; audit and CycloneDX coverage must match the same
pins. This also supplies the previously missing file referenced by the disposable
Render evaluation build, without editing an unrelated local Render change.
It is a **version pin file, not a cryptographic hash lock**. Tools are isolated from
the runtime and pinned separately in `requirements-security.txt`.

`tools/security_gate.py` fails closed on:

- missing/malformed/empty scan reports, scanner errors or no source coverage;
- new medium findings and every high finding, including a purported high waiver;
- changed/expired reviewed finding fingerprints;
- skipped packages, reported advisories or incomplete audit/SBOM/runtime coverage;
- high-confidence credential patterns in tracked source (private PEMs, AWS access
  IDs, credentialed Postgres URLs), unavailable files or tracked symlinks.

The credential check is a limited pattern guard, **not comprehensive secret
discovery or a Git-history audit**. No findings are printed with matching values.
Branch protection, secret scanning service enforcement, artifact signing, a fully
hashed tool/runtime lock and provider account protections remain operator controls.

## Scan outcomes and review decisions

- `pip-audit==2.9.0`: **36 packages**, no skipped entries or known advisories in the
  completed report. The original resolver-based audit omitted a declared package;
  coverage checks caught the gap. The final audit uses the independently resolved
  complete pin set, not a silently incomplete report. Advisory services and
  packages are public metadata; no private configuration is submitted.
- CycloneDX JSON: **36 components**, exact name/version coverage verified. The
  report is generated outside the working tree, not a private-environment inventory.
- `bandit==1.9.4`: **53 findings: 5 medium, 48 low; 0 high; 0 scanner errors**.
  Medium findings are fixed/literal SQL table selectors and fixed HTTP loopback
  checks, reviewed with content fingerprints, reasons and expiry **2026-11-25**
  in `security/bandit-reviewed.json`. Low CLI subprocess/assert/fixture findings
  remain visible; they are not silently deleted from the report. The review was
  performed during engineering work, not by an independent penetration tester.
- An initial Bandit 1.8.6 run errored under Python 3.14 and is **not** valid scan
  evidence, even though it exited successfully. Pinning 1.9.4 and checking report
  errors/source coverage resolves that false-pass hazard. A separate SBOM-tool
  installation failed on its old lxml dependency; the final SBOM uses pip-audit's
  supported CycloneDX output instead, with explicit coverage verification.

## Verification / outstanding release gate

Failing-first tests in `test_stage11_controls.py` reproduced missing CSP/HSTS,
inline handlers, legacy transport attempts and absent CI/gates. Ten focused tests
now pass. Chromium injection tests prove new inline scripts/handlers are blocked;
trusted navigation, Quick Exit and encrypted diary still work. Test polling uses
CDP evaluation without disabling CSP, rather than Playwright's CSP-blocked string
poller. Stage 2 HELP, Stage 5 diary, Stage 9 vault and all 34 Node checks pass.
Full backend and remaining browser regression/CI evidence are pending; no Stage 11
completion tag is established by this checkpoint. Existing fixture resource
warnings, physical-device/independent review gaps and Stage 12 gates remain.
