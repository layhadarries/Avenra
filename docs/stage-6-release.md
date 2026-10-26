# Stage 6 release boundaries and operator runbook

## Scope

This delivery targets Stage 6A: a hosted fictional-data hackathon demonstration.
It is not a security certification, guaranteed rescue service, or approval to process real survivor evidence.
Stage 6B requires the partner, safeguarding, MFA, encryption/key custody, deletion/retention, recovery and independent review gates in `stage-6-data-lifecycle-and-pilot-gate.md`.
Do not label the entire project "100% secure" or pilot-ready because tests pass.

## Included engineering

### Weather tap location follow-up (local verification, no deployment)

Tap alerts start the existing durable queue without awaiting GPS or a dialog.
The setup has a separate, default-off emergency-GPS option; existing opt-ins do
not silently gain it. Active server location consent is also required. Weather
search/cache coordinates are never used. One-shot GPS runs only after a gesture,
with a 10-second acquisition timeout; there is no watcher or continuous tracking.

A genuine in-memory fix may accompany the next alert if it is at most 120 seconds
old, at most 10 seconds ahead and accurate within 1,000 metres. Accuracy and capture
time are retained. Initial tap coordinates require a 120-second signed permission
bound to owner, paired device cookie and current consent audit epoch. Withdrawal
and regrant invalidate the earlier permission, including within one second.
Consent audit epoch evidence must be preserved by any future retention tooling.

After a matching durable receipt, an optional memory-only fix uses
`POST /api/alerts/by-client/<client_id>/location`. The server rechecks active device,
owner, consent, permission, exact fields and fix bounds under the write transaction.
The update window is ten minutes from server creation. Exact replay is a no-op;
older/conflicting timestamps are rejected. Only location columns and a
coordinate-free audit event change: no second alert, workflow change or notification.
The durable queue payload is never rewritten to add a late fix.

Backgrounding, local preference changes, account changes, denial and offline use
discard optional in-flight work. Late location is best-effort, not a durable second
queue: closing/backgrounding the page or losing connectivity can lose the update,
without losing the emergency alert. A fix already disclosed cannot be recalled.
Already-queued initial fixes are stripped or rejected if consent/permission is no
longer valid; the alert itself still saves without coordinates.

Evidence: `tests/test_alert_location_update.py`, `tests/emergency-location.cjs`,
`tests/weather_tap_browser.py`, and existing Stage 2 HELP and Stage 5 diary browser
checks. Chromium 156 mobile/touch emulation used injected GPS and fictional local
accounts, not real GPS, physical phones or external notification delivery.
WebKit remains blocked by missing host libraries. Stages 7–12 are not covered by
this follow-up and no stage completion is implied.

Local verification on 2026-10-25 passed 398 Python tests, 30 Node checks and
the weather-tap, Stage 2 HELP and Stage 5 diary Chromium acceptance scripts.
The Python suite still emits resource-cleanup warnings from test fixtures;
these are not presented as warning-free results. No deployment was performed.

Individual one-use device pairing, case recovery with explicit assignment checks, credential revocation, exact-origin writes, owner-bound offline queues, durable-receipt cleanup, a neutral installation page, stable public QR, private hosted diary photos, verified database TLS, bounded authenticated Web Push processing, hosted scheduler setup, encrypted row snapshots, and local/live acceptance tooling.

Private photo bytes are stored in `avenra.diary_objects` in the SAME database transaction as diary metadata and its audit event. No public bucket or evidence URL is created. Default object-byte budget is 80 MiB, maximum configured budget 100 MiB. Database overhead and other records count toward provider quotas too; monitor the actual project usage. This bounded demo choice is not an unlimited media storage architecture. Existing local photo files are not silently imported or discarded.

`verify-full` validates the database certificate and hostname. The public Supabase 2021 CA is bundled as Python data so serverless packaging cannot omit it. Its SHA-256 is `700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`. An operator can supply `PGSSLROOTCERT` for a project with a different CA; never weaken TLS to make a connection succeed.

## Local release checks

### Eight-item follow-up working tree (2026-10-26; not Stage 12)

This bounded follow-up preserves the intentional pre-existing Stage 12/package/
configuration work. The only overlap edited here is adding two browser commands
to the already-modified CI workflow; its existing checks are retained. Existing
HELP accessibility text and public-shell cache v25 are unchanged in the working
directory and excluded from the follow-up commit, along with the user's other
in-progress files. No Stage 7–12 tag, deployment, hosted migration or provider
setting is changed. The user subsequently explicitly authorised a **source-only
follow-up commit/push and new `v1.0.1` tag despite the hosted-source/rollback
blockers**. This overrides only the earlier instruction not to push source; it
does not pass release verification or permit deployment/operational use. The
committed snapshot retains the prior public-shell cache version: deploying these
changes requires a separately reviewed cache update, not inclusion of the user's
uncommitted cache bump without approval.

| Item | Current behavior / evidence |
|---|---|
| 1: weather status | Feedback is visible only in the current active tap flow. Leaving/hiding the page, opening a modal or using ordinary weather controls ends the display flow. Reload/new-page/return does not restore old status or polling. Only the existing queued-attempt owner/client-ID hint is retained to prevent a reopened gesture from duplicating that queued attempt; completed receipt/timestamp metadata is removed. Queue records and server/audit/responder state are untouched. `tap-status.cjs` and `weather_tap_browser.py` cover local save versus receipt, reload/reopen, exact queue retention, retry identity and acknowledgement preservation. The detector and emergency GPS rules are unchanged. |
| 2: evidence access | Already implemented by Stage 9: server-verified passphrase grant plus owner scope, or staff role + assignment + selective sharing + current consent. No replacement authorization architecture was added. `test_stage9_vault_access.py` now also exercises real direct JPEG bytes under signed-out, locked, own/foreign-grant and expired-grant access. Existing `test_stage4_diary_access.py` covers staff unshared/revoked-consent/revoked-assignment boundaries. Older security-document UI-only claims are corrected. |
| 3: Quick Exit | Existing vault clearing/queue encryption retained. Home alert text is cleared before departure; privacy no longer re-fetches private history on restoration after exit. Its persistent display-only exit marker returns reopening privacy pages to the disguised entry; successful existing PIN/device entry clears that marker, never grants evidence API authority. `followup_privacy_browser.py` covers exact encrypted diary queue preservation, reload/new tab, meaningful Back/Forward history, deliberate re-entry and injected persisted-pageshow handling. |
| 4: accidental follow-up | Existing workflow API accepts the distinct `accidental` annotation through `PortalService`/`PortalRepository`; no schema change or dashboard redesign. Tests verify active role/assignment, CSRF/sign-out denial, revoked assignment even on retry, four concurrent retries yielding one event, original alert/delivery/ack/history/audit preservation, post-resolution annotation and atomic audit-failure rollback. No delivery cancellation or suppression of later alerts. |
| 5: demo isolation | Production startup/requests and both workers reject evaluation markers and legacy seeded identities. Seeding refuses operational runtime; no existing data is deleted or relabelled. Isolated tests prove production reports cannot expose the fixture, workers cannot claim/send its jobs and a separate operational-database fixture still reports and calls only a fake sender. No live delivery or hosted database change is performed. |
| 6: weather boundary | No weather implementation changes. `weather_data_boundary_browser.py` runs mocked Open-Meteo forecasts/search and disclosed BigDataCloud GPS locality, verifies no weather mutation of users/alerts/diary/audit or coordinate-bearing first-party requests, and checks GPS-free HELP plus diary/audit separation. Existing weather/tap/GPS tests retain separate emergency permission/consent behavior. |
| 7: operations | The existing deployment runbook now documents actual app/API versus human triage, escalation, assignment, closure, accidental/duplicate/location/provider/access cases and honest delivery states. Monitoring owner/hours, safe contacts/escalation ladder and other unresolved pre-pilot decisions are explicitly unresolved. |
| 8: release identity | **BLOCKED**, not complete: the public alias points to `dpl_C6wUvj8fEi5GK7FYVAsmT1WMC8Lu`, lacks source-SHA metadata and serves mismatching scripts/missing vault asset. Anonymous private/no-store/worker rejection probes passed, but do not attest authenticated evidence controls or matching source. Verified known-good rollback/actual alias-restoration evidence is absent. See the deployment runbook's exact ID/URL, fingerprints, safe probes and operator-only rollback procedure. The later explicit source-only push/tag authorisation does not resolve this gate. |

Local verification on the final executable working tree (not hosted CI):

| Check | Observed result |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | **499 passed**, 380.353 seconds. Includes the intentional pre-existing acceptance tests; existing fixture resource warnings remain. |
| `node --test tests/*.cjs` | **42 passed**, including unchanged gesture/emergency-location contracts and the new stale-status/interaction/retry checks. |
| Every current `tests/*browser.py` script | **24 scripts passed** in the final sweep, supplemented by reruns of the enhanced Quick Exit test and the final weather-tap/weather/CSP tests after the last display/test adjustments. Chromium emulation and isolated fictional databases/fake providers only. Running pre-existing Stage 12-named checks does not complete Stage 12. |
| `tools/security_gate.py` with pinned isolated `requirements-security.txt` tooling | Passed static/credential gate: **53 findings retained, 5 reviewed medium, 48 low, zero high or scanner errors**. New/untracked source and package files also passed the limited credential-pattern check; this is not a comprehensive secret/history audit. |
| Documented dry-run runtime resolution, strict pip-audit and CycloneDX gates | **36 exact runtime packages/components**, closure and audit/SBOM coverage matched, no reported advisories/skips. `.venv/bin/python -m pip check` passed. |
| `npm audit --audit-level=moderate` and `npm audit --prefix tools/a11y --audit-level=moderate` | Both passed with zero reported vulnerabilities; user package/lock files were not edited. |
| `tools/build_vercel_assets.py` | Passed in an isolated copy of the actual current static working tree: **63 public assets** matched byte-for-byte; no generated repository artifacts or deployment. |
| Diff / release hygiene | `git diff --check` passed; complete changed-source/test/docs and existing user diffs reviewed. At this initial verification checkpoint nothing was staged, committed, pushed, tagged or changed on the hosted runtime. The later source-only push/tag authorisation is recorded above; release identity/rollback remain blocked. |

Browser limits: Chromium 156 mobile/touch emulation and synthetic GPS/lifecycle
events are not physical-phone acceptance. The Quick Exit test permits BFCache
(rather than Playwright's default disable flag), but Chromium did **not** restore
the protected privacy document from BFCache in the observed run. Real Back/Forward
and explicit persisted-event branches are tested; actual BFCache, browser crash/tab
restoration and OS-specific behavior still need device evidence. Quick Exit cannot
erase OS snapshots, screenshots, gallery originals, clipboard content or external
copies. Do not present it as forensic erasure or a guarantee against browser/OS
compromise. Pending alert/diary queues are never deleted as an exit mechanism.

Test-history disclosures: the initial new tests failed for the expected missing
controls before their fixes. The aggregate weather regression also exposed a test
race: night-time repaint could precede receipt of the new clear forecast. Its test
now waits for both night and clear atmosphere before asserting the moon; no weather
code or visual assertion was removed. An added explicit-weather-refresh scenario
also required restoring a normal GPS-denial fixture after the earlier deliberately
throwing emergency-only stub. The static gate initially rejected the moved legacy
seed query's line-number fingerprint; the unchanged literal-table query was
re-reviewed and only that fingerprint/reason updated, with its expiry unchanged.
No high/medium finding, auth check, CSP or release gate was weakened.

These local checks do not complete Stage 12, independent review, approved
safeguarding/privacy/key custody, monitoring coverage, hosted rollout/rollback,
physical-device acceptance or readiness for real survivor/emergency operations.

### Historical Stage 6 updater

The following updater notes describe that historical delivery, not instructions
for this follow-up. Do not run a source-replacing updater against intentional
in-progress user work or bypass the blocked release-identity gate.

Run the supplied updater with `--apply --verify --commit --push` from main.
It backs up changed source, refuses unrelated edits, uses the repository venv, runs the full Python suite and browser/service-worker checks, and stages only reviewed paths. It does not deploy, migrate hosted data, or send messages.

The updater deliberately replaces the known in-progress diary ownership functions with the final tested implementation, preserving a private source backup. Unrelated changes outside those functions are refused. Do not delete or reset a database to bypass a failed check.

## Hosted preparation and deployment

1. Activate the venv and source the PRIVATE hosted runtime. Do not paste that runtime into chats.
2. `python tools/stage6_hosted.py --prepare` makes an encrypted row snapshot, applies additive pairing/private-photo schema, checks real PostgreSQL generated IDs, blob roundtrip and rollback, and updates Vercel configuration through stdin. It preserves the existing database URI, staff identities, login secret, accounts and evidence. It creates persistent push keys only if no configured keys exist. Existing incomplete key directories are refused.
3. `npx vercel@65.2.0 deploy --prod --logs` deploys only after local acceptance and hosted preparation succeed.
4. `python tools/stage6_hosted.py --verify` checks the public HTTPS routes, unauthenticated private boundaries and authenticated worker dry run. It does NOT claim to test an authenticated survivor journey or physically received push.
5. `python tools/stage6_hosted.py --schedule` repeats live verification then configures pg_cron + pg_net to call the worker once per minute. The token is stored in Supabase Vault and never embedded in cron SQL. Enable these supported extensions on the existing project only; do not upgrade to paid plans automatically. If permissions or availability block setup, STOP and report the failure instead of marking notifications operational.
6. With the laptop OFF, complete the real-phone checklist, then record it using `python tools/stage6_status.py --record-phone-checks`. Answer only checks physically performed. Pending checks mean Stage 6A is incomplete.

The scheduler handles at most one push outbox job per invocation. It does not send SMS, guarantee immediate delivery, or automatically retry an uncertain provider outcome. Provider acceptance is distinct from notification receipt or reading. Scheduled work may be delayed or stopped by provider quotas, project pausing, platform availability or network conditions.

## Operations and rollback

Current alert-response procedures, unresolved staffing decisions, Vercel alias
rollback and the blocked follow-up release-identity check are maintained in
[the deployment runbook, sections 5–6](stage-6-deployment-runbook.md#5-alert-response-operations-pre-pilot-not-a-coverage-commitment).
Historical Stage 6 completion evidence below does not attest later working trees
or the current hosted source.

Pause only the Avenra scheduler with `python tools/stage6_hosted.py --disable-scheduler`. Do not disable a shared extension or other jobs.
For device loss: revoke the old credentials and issue a recovery invitation for the ORIGINAL assigned case. Do not create a new case as a recovery workaround. Recovery invalidates previous credentials on successful consumption; committed queues remain bound to their original account.

Keep the encrypted row snapshots AND a separately protected copy of their key under an operator-controlled backup policy. Snapshot encryption/readback is verified; a snapshot is not proof of a provider disaster-recovery restore. Perform a separate isolated restore drill before real-data use. Do not copy live production data to unprotected test environments.

Additive schema can remain during a source/deployment rollback. Preserve push encryption/VAPID keys, the login secret, invitation/device state and database rows. An uncertain notification must not be resent by resetting its job to pending.

## Completion evidence

- Full local Python and browser suites passed on the exact committed build.
- Hosted verified-TLS and transactional probes passed.
- Public and private live HTTP probes passed on the deployed build.
- Scheduler enabled and its invocation confirmed with safe status metadata.
- Physical installed-phone tests passed with no developer laptop/USB/tunnel.
- No open blocker, real incident record, unsupported safety promise or unresolved data-loss case.

An updater cannot perform the last physical check for you or supply professional governance sign-off. The tooling leaves those gates explicitly pending.

### Isolated restore drill

`tools/stage6_restore.py ENCRYPTED_SNAPSHOT --key PRIVATE_BACKUP_KEY` restores rows into an already-migrated EMPTY private schema using a separately configured restore-test `DATABASE_URL`. It refuses populated targets, preserves constraints, restores identity sequences and verifies photo digests. Never point a restore drill at the live database. This command must actually pass on a separate target before claiming a completed restore drill.
