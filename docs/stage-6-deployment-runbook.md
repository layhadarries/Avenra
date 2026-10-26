# Stage 6A Deployment Runbook, Monitoring & Restore Report

## 1. Hosted Architecture & Free-Tier Disclosures

| Component | Configuration / Profile | Operational & Free-Tier Constraints |
|---|---|---|
| **Public Fictional Evaluation (`render.evaluation.yaml`)** | `APP_ENV=evaluation`, `COOKIE_SECURE=1`, Gunicorn (`1` worker, `4` threads), `/tmp` SQLite + uploads | Free web service sleeps on inactivity (cold start 15–50 s) and `/tmp` is ephemeral across restarts/redeploys. Outbound SMS and alert Web Push dispatch are hard-disabled (`NotificationWorker` and `PushWorker` refuse to run when `EVALUATION_MODE` or `evaluation_fixture` is set). |
| **Persistent Single-Host Profile (`render.yaml`)** | `APP_ENV=production`, `COOKIE_SECURE=1`, `python -m avenra.runtime`, mounted disk at `/var/data` | Requires a persistent disk mount (`DATABASE_PATH=/var/data/avenra.sqlite3`, `UPLOADS_DIR=/var/data/uploads`). Do not run multi-instance SQLite writers against local ephemeral storage. |
| **Private Object Storage Adapter (`PrivateObjectDiaryStorage`)** | `DiaryService(..., storage_backend=PrivateObjectDiaryStorage(client, bucket))` | Enforces post-upload SHA-256 verification and orphan quarantine/reconciliation. Never expose a public bucket URL; photos are streamed exclusively through authenticated Flask routes with `Cache-Control: private, no-store`. |

## 2. Environment Separation & Secret Hygiene

Required environment variables for `APP_ENV=production`:
- `SECRET_KEY`: cryptographically random string $\ge$ 32 characters (enforced at startup in [`AvenraApplication._configure_app`](../avenra/application.py)).
- `APP_ENV`: `production` (disables `/evaluation` one-click role sign-in and disables table counts on `/health`).
- `COOKIE_SECURE`: `1` (enforces `Secure`, `HttpOnly`, `SameSite=Lax` staff session cookies and `__Host-avenra_push_browser` `SameSite=Strict` contact cookies).
- `DEVICE_TOKEN` is **not** a production survivor credential: production ignores
  the development `X-Device-Token` path. Use individually issued expiring pairing
  invitations and the resulting revocable HttpOnly device cookie.
- Current source also requires a separate valid `STAFF_MFA_ENCRYPTION_KEY` and
  `OFFLINE_QUEUE_PRIVATE_KEY_PEM` in operational/hosted runtime. Preserve retired
  queue keys and the Stage 9 custody requirements; do not regenerate keys to make
  startup pass. Vercel requires the privately configured Supabase `DATABASE_URL`
  with verified TLS and separately approved additive schema rollout.
- `AVENRA_WEBPUSH_ENABLED`: set to `1` only when `WEBPUSH_KEY_DIR` (`0700` permissions) and `WEBPUSH_SUBJECT` (`mailto:...`) are configured.

Current production startup and requests refuse a database with the evaluation
marker or legacy seeded `@avenra.demo` identities. Both workers refuse those
databases in operational runtime before claiming jobs; marked evaluation jobs
remain disabled in every environment. Production seeding is forbidden. Separation
is database-wide, not a cosmetic label or a reporting filter. Do not remove a
marker, rename accounts, delete rows or reuse an evaluation database to bypass the
guard. Establish a separate operational database and approved provenance review.
Arbitrary unmarked data inserted outside application controls still requires an
operator's provenance review; these checks are not a classifier for real people.

## 3. Content-Free Health & Operational Monitoring (`T6.2`)

- **Health Endpoint (`GET /health`):**
  - In `production` and `development`, returns strictly `{"status": "ok"}` with `Cache-Control: private, no-store`—no case codes, user counts, or personal data are exposed.
  - Table counts are emitted only when `APP_ENV=evaluation` AND `seed.is_evaluation_database()` confirms the disposable evaluation fixture marker.
- **Outbox & Storage Checks:**
  - Inspect queue health without reading message bodies or notes:
    - Pending/stale outbox jobs: `SELECT channel, status, reason_code, COUNT(*) FROM notification_outbox GROUP BY channel, status, reason_code;`
    - Stale claim recovery: `NotificationWorker.recover_stale(max_age_seconds=900)` marks claims older than 15 minutes as `unknown` (`notification_recovery` audit event) without auto-retrying delivery.
    - Diary orphan reconciliation: `DiaryService().reconcile_orphans(uploads_dir)` quarantines unreferenced `diary_*.jpg` files without deleting committed evidence.
- **Investigation Ownership:**
  - Backend, database, storage, and worker incidents: **Tazio**.
  - Survivor PWA shell, offline IndexedDB queue, and service-worker caching incidents: **Zulayha**.

## 4. Backup, Restore Drill & Rollback Procedure

### 4.1 Online Backup & Restore Drill Report
Historical SQLite/v3 evidence below is not a current hosted restore acceptance.
For current encrypted SQLite archives, separate key custody, additive schema and
retention/tombstone compatibility, follow
[the Stage 9 design](stage-9-private-storage-and-recovery.md). Provider PostgreSQL
backup/PITR and an approved hosted restore drill remain separate pre-pilot gates.

1. **Consistent SQLite Backup:** Use SQLite's online backup API (`sqlite3 <DB_PATH> ".backup '/path/to/backup.sqlite3'"`) so active WAL/journal state is captured atomically.
2. **Upload Directory Snapshot:** Archive `UPLOADS_DIR` (`diary_*.jpg`) alongside the database snapshot and verify every row in `diary_entries` (`WHERE photo_path IS NOT NULL`) against its recorded `photo_sha256` / `file_hash` via `LocalDiaryStorage.verify_object()`.
3. **Verified Restore Drill:**
   - Restored migrated v3 database + `uploads/` into an isolated temporary directory.
   - Confirmed schema version `3`, user accounts, active/revoked `consents`, `alerts`, `referrals`, `audit_log`, and `diary_entries` integrity digests matched pre-backup state.

### 4.2 Rollback Separation (Application Code vs Database Schema)
- **Application Code Rollback:** The original SQLite/v3 instructions are historical. For current Vercel/Supabase alias rollback, use section 6 below. Additive tables do not make every older client safe: never roll back to code that bypasses MFA, vault guards, tombstones or queue encryption. Preserve the Stage 9 key/retention requirements.
- **Database Restore:** Never run `rm` or `seed.reset()` on a non-evaluation database (`seed.py` refuses to reset any database lacking the `evaluation_fixture` marker). If a migration or storage corruption requires full restoration, stop the web/worker processes, restore the verified `.backup` database and `uploads/` snapshot into a new directory, verify `PRAGMA integrity_check` and photo SHA-256 digests, and switch `DATABASE_PATH` / `UPLOADS_DIR`.

## 5. Alert-response operations (pre-pilot, not a coverage commitment)

**Monitoring owner, coverage hours/timezone, shift handover and out-of-hours
fallback: UNRESOLVED pre-pilot decisions.** The technical incident owners above
are not a promise of alert monitoring. No response-time target, dispatch partnership
or staffed emergency service has been established by these engineering checks.

### Implemented workflow versus trained human process

Only active admin/responder accounts with current explicit case assignment may
triage that case. An administrator role alone is insufficient. Staff sign-in/MFA,
session expiry and CSRF still apply to workflow writes. Shelter staff handle their
scoped referral workflow, not general alert triage.

1. **Monitor and verify (human):** open the authenticated dashboard, refresh and
   inspect the assigned alert/case and server receipt time. Check whether device
   capture/location times are stale or clock-skewed. An alert is a report, not
   independent confirmation of an incident. Use only an approved safe contact
   method/time agreed with the survivor; that operational protocol is unresolved.
2. **Acknowledge (app):** dashboard acknowledgement uses
   `POST /api/alerts/<id>/acknowledge`. It records staff acknowledgement and history;
   it does not prove a contact message was delivered or help arrived.
3. **Assign/escalate (API + human):** `POST /api/alerts/<id>/workflow` accepts
   `action: "assign"` plus `assignee_id`, or `action: "escalate"` plus a nonempty
   `reason`, with the current integer `revision` from the alert listing. Assignees
   must be active eligible staff with case access. A stale revision returns 409:
   refresh and review rather than blind overwrite. These API actions are not
   dashboard buttons. Escalation records a timestamp/reason; a trained person must
   contact the designated escalation recipient. The app does not dispatch them.
4. **Refer (app + human):** the case workspace can search services and send a
   consent-permitted referral. Staff must confirm availability and suitability
   directly. A sent or accepted referral is not a confirmed place; recording a
   placement is a separate action. Do not invent beds or bypass a service denial.
5. **Close (API + human):** workflow `action: "resolve"`, current `revision` and
   nonempty `reason` require prior acknowledgement and no sent/accepted referral.
   Placement recording can also resolve an alert through the referral workflow.
   A trained person decides whether closure is appropriate under the approved
   safeguarding protocol. A resolved row is not proof the person is safe.

For API operations use the authenticated staff session, the existing exact-origin
rules and `X-CSRFToken`; never paste credentials or tokens into runbooks/tickets.
Retain the returned record IDs, not evidence text or coordinates in general logs.

### Exceptional reports and access problems

- **No location:** continue triage; missing GPS does not prevent an alert receipt.
  Do not substitute the weather place, an IP lookup or a guessed address. Establish
  a safe way for the person to provide location only if their consent permits it.
- **Stale/inaccurate location:** inspect recorded accuracy and device capture time;
  map distances are estimates from the report, not live tracking. Clearly tell the
  human responder that the position is unconfirmed. Do not overwrite the original
  report to imply a current fix. Late GPS is bounded and best-effort.
- **Duplicate report:** compare IDs, receipts and workflow history; retries of one
  client ID are not independent incidents. Keep every original row and prior
  acknowledgement. Human escalation/closure should explain the relationship
  without suppressing later legitimate alerts.
- **Apparent accidental alert:** an assigned admin/responder can submit workflow
  `{"action":"accidental","reason":"<minimal non-sensitive follow-up>"}`.
  This is an annotation, not a status transition or cancellation. It appends
  `alert_history` and an `alert_accidental` audit link with staff identity and
  server time. The same staff/alert/reason retry returns the original event ID/time;
  a changed reason returns 409 rather than rewriting it. Access is rechecked even
  on retries. It is available after resolution too. No messages are recalled, no
  delivery attempt/acknowledgement is changed and later alerts are unaffected.
  Verification of the report and any safe follow-up remain human responsibilities.
- **Consent withdrawn/access denied:** stop the disallowed disclosure or operation.
  Do not bypass assignment, role or entry-sharing requirements, copy cached private
  content, regrant consent on someone's behalf or treat consent withdrawal as
  deletion. Ask the authorised access/safeguarding owner to resolve the issue using
  minimal identifiers. Application revocation cannot recall external copies.
- **Service unavailable/declines:** record the implemented decline/placement state
  accurately and follow the trained escalation protocol to seek another service.
  Do not promise admission. Escalation directory and safe contact details are
  unresolved pre-pilot inputs.
- **Provider/scheduler failure:** distinguish failed, unknown and pending jobs.
  Inspect content-free queue/heartbeat metadata; notify the technical owner through
  the agreed incident channel. Never reset an unknown/accepted job to pending to
  manufacture delivery or retry through a different channel. Uncertain acceptance
  may mean a message was sent. Human fallback requires a separately approved safe
  protocol; there is no automatic SMS fallback in the hosted Web Push worker.

### What each state can establish

| Observation/state | What it establishes (and does not establish) |
|---|---|
| Saved on this phone | Local durable storage committed; not server receipt. |
| Queued/waiting to send or confirm | A local queue record remains; network retry may be needed, including after a lost receipt. Not delivery. |
| Received by Avenra | A matching server alert receipt exists. Not provider acceptance or human response. |
| Outbox pending/processing | Server job waiting/claimed; not delivery. |
| Provider accepted | Provider accepted a request. Not a displayed/read notification or contact response. |
| Delivered | No general end-to-end delivered state is established by the current worker. Do not infer it from acceptance or an empty queue. |
| Recipient acknowledged | A valid contact-push acknowledgement is separate from staff acknowledgement; it is not proof of responder attendance. |
| Acknowledged/in progress | Staff acknowledgement/workflow has been recorded; no arrival or safety guarantee. |
| Resolved | Staff/referral workflow marked the alert resolved; not independently verified safety. |
| Failed/unknown/cancelled | Rejected, uncertain, or stopped server job as recorded; do not rewrite history to claim delivery. |

Staff must not present Avenra as emergency-service dispatch, guarantee rescue or
service availability, equate queued with delivered, or treat an accidental
annotation as permission to ignore future reports. Public weather content must
not expose previous alerts; discreet feedback is confined to the active tap flow.

### Required decisions before a real pilot

UNRESOLVED: named accountable monitoring and safeguarding owners; coverage hours
and timezone; staffing/backup rota and handover; safe survivor contact protocol;
validated operational contacts and escalation ladder (including out-of-hours);
local emergency-service guidance; duplicate/accidental verification and closure
policy; provider-outage fallback and incident channel; service-directory owners;
training, consent/privacy/retention approvals, independent review and physical-phone
acceptance. Supply approved details before operational use. Do not invent them.

## 6. Vercel release identity and rollback (operator approval required)

The linked project uploads the local checkout with Vercel CLI; Git HEAD alone is
not proof of the uploaded bytes. Historical deployment/preparation instructions
must not be run automatically: `stage6_hosted.py --prepare` changes hosted data and
configuration and is **not** a read-only verification command. New rollout requires
separate approval, schema/key compatibility checks and a reviewed source manifest.

Read-only inspection (syntax checked with CLI 65.2.0):

```text
npx --yes vercel@65.2.0 inspect https://avenra-delta.vercel.app --json
npx --yes vercel@65.2.0 list --environment production --status READY --json
npx --yes vercel@65.2.0 inspect <candidate-immutable-deployment-url> --json
```

Keep full metadata private; record only immutable deployment ID/URL, verified source
SHA, verification time and safe results. Never dump build/runtime logs or environment
variables. READY is build status, not a known-good safety or source-identity verdict.
Select the last known-good deployment using prior source/route/security verification
evidence, not just the most recent READY item. Verify its MFA/vault/queue/retention
compatibility and retained key custody against the current additive database first.
If the candidate's source or compatibility cannot be established, stop.

After separate operator approval only, restore the project deployment using
`npx --yes vercel@65.2.0 rollback <verified-immutable-deployment-url>`. If restoring
only the explicit public alias is the approved operation, the actual CLI syntax is
`npx --yes vercel@65.2.0 alias set <verified-immutable-deployment-url> avenra-delta.vercel.app`.
Do not execute either placeholder command until the exact candidate has been chosen
and verified. Do not redeploy an old Git tag as a substitute for restoring verified
immutable bytes. Preserve database rows, tombstones, audit history and all required
old/new keys; do not run down-migrations or reset delivery jobs. Alias rollback does
not undo hosted migrations or already-delivered messages.

After restoration, repeat alias inspection and confirm it resolves to that exact
ID; repeat HTTPS public route checks, signed-out private API/photo/page protection
and `private, no-store`, CSP, and worker missing/invalid-credential rejection.
Authenticated worker dry-run/source checks require the operator's private runtime
and must never dispatch. `stage6_hosted.py --verify` additionally requires its
matching local acceptance manifest and clean committed source; do not bypass those
checks. Verify the public alias, not just the immutable URL. Stop if any critical
check or identity comparison fails. Alias restoration, prior cache/client versions,
database compatibility and real-device behavior need explicit operational evidence.

### Follow-up inspection, 2026-10-26 (not release verification)

- Local base HEAD: `c7ee21432d9d767374d1cb4b1ca035d33b94cdab`, with intentional
  uncommitted user work and these follow-up changes. There is **no single committed
  SHA for the tested working tree**; the base SHA must not be described as its exact
  verified source. This inspection preceded the later explicit source-only
  commit/push and `v1.0.1` tag authorisation; no migration or deployment is authorised.
- Public alias inspected: `https://avenra-delta.vercel.app` →
  `dpl_C6wUvj8fEi5GK7FYVAsmT1WMC8Lu`, immutable URL
  `https://avenra-jcoxy9v7x-tazio0s-projects.vercel.app`, READY/production.
  Inspection exposes neither `gitCommitSha` nor `githubCommitSha`.
- Anonymous checks: `/login`, `/survivor/` return 200; `/evaluation` 404;
  `/dashboard` and `/cases/diary-photo/1` redirect to sign-in; `/api/device`,
  `/api/diary`, `/api/diary/1`, `/api/diary/1/photo`, `/api/alerts`
  return 401 with `private, no-store` (the private redirects are no-store too).
  Worker POST with missing or invalid bearer
  returns 401 and `private, no-store`. These are bounded anonymous checks, not a
  claim of authenticated evidence access or provider/phone verification.
- Source mismatch evidence: public `tap-alert.js` SHA-256
  `5f98ddc92a9838ea519f413abd3c080f2974da7bd7b85b8356fe7efb3cd1bbff`,
  and `shell.js` SHA-256
  `415649fb78734b452aaa79aaf20c62cc85980b4cc508afb3786fa1b81c47f84b`
  differ from both base HEAD and the working tree; `/survivor/storage-vault.js`
  returns 404. The alias cannot be attested as this source release.
- **BLOCKED:** deployed-source identity does not match; a compatible verified
  last-known-good rollback target and actual alias-restoration verification have
  not been established. CLI syntax inspection is not a rollback drill. Do not
  claim item 8/release verification or deploy past these gates. The user later
  explicitly authorised a source-only follow-up commit/push and new `v1.0.1` tag
  despite these blockers, leaving pre-existing work uncommitted. That permission
  does not attest the hosted release, approve an alias change/migration, or mark
  Stage 12 complete. Existing Stage 7–12 tags must remain untouched. A separately
  approved operator action/result is required for hosted verification/rollback.
