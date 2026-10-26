# Authentication and Twilio source update — verification, 2026-10-26

## Delivered

- Generic, rate-limited forgot-password flow with domain-separated, hashed,
  expiring, single-use reset links. Reset retains MFA/roles/assignments and
  invalidates sessions through auth-version changes. Reset URLs use fragments,
  cleared immediately by external JS; pages are private/no-store/no-referrer.
- Provider-neutral SMTP wizard retained; branded HTML now uses the actual subject
  and body for both invitations and password recovery, with escaped content.
- Existing Twilio transport integrated into the bounded authenticated hosted worker
  independently of Web Push. No channel fallback or uncertain-send retry added.
- Existing contacts default to SMS disabled. Owner-scoped boolean permission API,
  PWA enable/disable controls, audited changes, cancellation of historical pending
  jobs on preference changes, and dispatch-time permission checks.
- Additive private-schema SMS flag migration. No account/evidence/key deletion.
  The schema version remains 9 with an additive capability marker so old source
  version checks remain compatible. New source fails startup if the flag is absent.
- Developer SMS wizard, Make targets, isolated local release runner, browser
  recovery acceptance script and expanded README operations instructions.

## Checks actually run in this environment

- Full Python aggregate rerun: **508 tests passed in 420.051 seconds**.
  Afterwards, the final expanded focused suites passed: **8 recovery tests** and
  **6 SMS-permission tests**. Those additional assertions/tests are not falsely
  counted as part of the earlier aggregate run.
- Node: **42 passed, zero failed**.
- Notification worker: 9 passed; Stage 2 transport/notification contracts: 21
  passed; contact API: 8 passed; demo-isolation: 5 passed.
- Python compilation, new JavaScript syntax check, dependency consistency and
  changed-source whitespace checks passed.
- Bandit gate passed: 55 findings retained as informational lows/existing reviewed
  medium findings; no unreviewed medium/high finding accepted. This is not a claim
  of zero findings or an independent code/security review.
- Tracked credential-pattern gate passed. Pattern matching is not proof that every
  possible secret has been detected and does not scan provider accounts/history.
- Runtime resolution, advisory audit and CycloneDX SBOM coverage passed for all
  36 pinned runtime packages; no known advisories reported at audit time.
- Existing fixture resource-cleanup warnings remain, and a diary orphan-cleanup
  test emits its expected attention message. Results are not described as warning-free.
- The first aggregate run failed because existing synthetic SMS sender tests did
  not declare SMS permission. Those fixtures now explicitly opt in; the runtime
  denial guard was preserved, and new default-denial/withdrawal tests were added.
  The fresh aggregate pass supersedes the failed run.

## Not verified / not performed

- Chromium download returned truncated/unusable archives. Browser acceptance could
  not run here. `make release-check` requires these checks on the developer PC;
  failure/unavailability stops it. No browser pass is claimed for this patch.
- No live PostgreSQL migration or hosted rollout/probe was performed. The additive
  SQL must be applied to the intended private schema and hosted startup/queries
  verified before deployment. SQLite and SQL translation tests are not a live
  PostgreSQL integration test.
- No email, SMS or Web Push was sent, no provider setting changed, no paid resource
  purchased, no deployment made and no remote Git push performed here.
- No physical phone test, restore/rollback exercise, independent penetration test,
  privacy/safeguarding approval or real-survivor readiness certification occurred.

## Operational boundaries

SMS permission is the survivor's explicit attestation that the trusted contact
agrees, not independent recipient verification. Honour recipient opt-outs and
provider suppression rules. Each contact has one active channel under the existing
outbox model, so a Web Push contact is not simultaneously an SMS recipient.

The worker handles at most one job per enabled channel per tick. A minute schedule
can delay multi-contact notification over several minutes. Provider quotas,
network failures or project suspension can delay it further. Accepted is not
necessarily delivered/read; uncertain outcomes are not blindly retried. Avenra is
not an emergency-service dispatch guarantee. Keep fictional demo data until the
remaining documented operational/security/governance gates are independently met.

## Installer adaptation to committed Stage 12 work

The installer now accepts the CI and service-worker files from commit e3cb4df.
It retains Stage 12 CI jobs and full checkout history, adds the two recovery/
invitation browser commands, and increments the existing shell cache v25 to v26.
It does not replace index.html, render.evaluation.yaml or Stage 12 test/package
files. Prior runtime verification remains as recorded above; run release-check
on this combined tree before committing or deploying.
