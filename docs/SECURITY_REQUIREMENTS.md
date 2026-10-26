# Agreed security requirements

Status: design requirements unless explicitly verified in STAGE0_STATUS.md or
the stage evidence section below. No independent security certification implied.
Use test-driven development: reproduce the expected failure first, implement the
policy in services/repositories, then run targeted and full regression checks.
Use OWASP Top 10 and ASVS as review frameworks, not a certification claim.

## Stage 7 practical threat model and route/repository audit

Baseline: `fd282b9` (separate tap-location fix). Review performed in the local
fictional-data environment. Operators, provider administrators and the server's
database credential remain privileged; application RBAC does not constrain a
database owner. Real-data use remains blocked by the pilot gates.

### Assets, actors and trust boundaries

Assets: survivor identity linkage, device credentials, diary text/photo bytes,
location and accuracy/time, contact destinations, staff credentials/sessions,
consent epochs, audit events and notification delivery claims. Adversaries include
an abusive partner with a shared/unlocked or stolen phone, remote unauthenticated
clients, malicious/compromised staff, hostile uploads, replaying clients and
compromised integrations. Availability loss can be safety-significant even without
confidentiality loss; an alert receipt is not emergency dispatch.

1. **Phone → browser origin:** public weather assets and weather-provider calls
   are separate from private paired APIs. Browser permission is not sharing consent.
   Emergency GPS is memory-only; a signed device/owner/consent-epoch capability is
   needed for initial tap coordinates and late updates. Weather caches are never
   evidence of the survivor's current emergency position.
2. **Local UI → local storage:** IndexedDB queues carry an explicit owner and stable
   client ID; receipts must match before removal. Local PIN/WebAuthn entry controls
   are currently UI controls, **not server-verified evidence authorization**. An
   already paired unlocked phone or same-origin script can read private APIs.
   Existing offline notes/photos and queues are not meaningfully encrypted against
   browser-profile theft. Stage 9 must resolve keys/offline availability, not put a
   key next to ciphertext and claim protection. Quick Exit cannot erase OS snapshots.
3. **Browser → Flask:** device authority comes from an opaque HttpOnly cookie, not
   `X-Queue-Owner`; that header only detects wrong-owner retries. Staff authority is
   a signed, expiring session checked against active account/auth version. Device
   writes require exact Origin; staff writes also require session-bound CSRF.
   TLS and secure cookies are required in production. No frontend flag grants roles.
4. **Controllers → services → repositories:** controllers authenticate/parse,
   services enforce ownership/assignment, current consent, transitions and atomic
   audit writes; repositories bind SQL values. A role alone must not grant case
   access. Names, notes and workflow reasons are untrusted output; templates escape
   them and dynamic private UI uses text nodes, not HTML injection.
5. **Flask → DB/private media:** the server database credential can access private
   records, so PostgreSQL RLS/revoked public schema access supplements rather than
   replaces application checks. Local media names are server-generated; JPEG bytes
   are decoded/bounded and metadata rules enforced. Local reads reject symlinks and
   non-regular files and use bounded bytes, not public/static evidence paths.
6. **Queue/outbox → worker → provider:** durable unique alert/contact jobs, exclusive
   claim tokens and consent/recipient revalidation precede dispatch. Provider
   acceptance is not delivery; ambiguous transport is unknown, never silently
   resent as success. Worker bearer authority is independent of browser/staff
   authority. Public push enrollment is a narrow expiring capability with no case
   access. Push destinations are HTTPS allowlisted with public-address checks and
   redirects disabled. Providers, email inboxes and copied disclosures are outside
   application revocation control.
7. **Operator/CI → Vercel/Supabase/backups:** secrets must stay outside source and
   public build assets. Verified TLS and hostname validation must remain enabled.
   Backup keys need separate custody; row snapshots do not prove provider disaster
   recovery. Deployment, restore and security-review evidence is separately gated.

### Actual HTTP authority inventory

Inventory source: registered Flask `url_map`, plus controller/service calls; not
inferred from URL naming. GET implies HEAD; OPTIONS has no record mutation.

| Route family | Authority and data boundary audited |
|---|---|
| `/`, `/health`, `/static/*`, `/survivor/*` | Public shell only; no public upload directory. Health's evaluation-only fictional counts are not an operational readiness check. Survivor HTML does not itself establish private authorization. |
| `/login`, `/logout`, `/api/session`, `/evaluation*` | AuthController/AuthService → UserRepository. Password/session version/expiry, CSRF, evaluation fixture gate. Staff MFA and persistent login abuse controls are Stage 8 gaps. |
| `/activate` and staff CLI | Invitation digest, expiry, version, one-use transaction; immutable server role/scope; explicit CLI suspension. Email is an external trust boundary. MFA enrollment/recovery still required in Stage 8. |
| `/devices`, `/api/device-invites`, `/api/device/enroll`, `/api/device[/disconnect]` | Staff role + explicit case assignment for recovery; invite issuer version rechecked at consumption; opaque device cookie expiry/revocation. Fixed-window persistent pairing limit. No public first-case recovery by knowing a case code. |
| `/api/onboarding`, `/api/contacts*`, `/api/consents`, `/api/my-access` | Paired survivor scoped repositories; masked contacts; atomic consent/audit writes and owner-bound cursor/history. Push invitation subroute has separate recipient limits. |
| `/api/alerts`, `/<id>/status`, `/location-permission`, `/by-client/<id>/location` | Paired survivor + queue-owner match on creation and late updates; idempotent IDs, immutable retries; late fixes reauthorize inside transaction and cannot dispatch or change workflow. |
| `/api/alerts` GET, `/<id>/acknowledge`, `/<id>/workflow`, `/<id>/nearby-services`, `/cases*`, `/api/cases/<code>/access`, `/dashboard` | Staff roles and CaseAccessRepository; assignment-revocation checks on requests; consent redaction; optimistic workflow revision. Admin can manage grants but cannot read unassigned cases. All private HTML/API/photo responses no-store. |
| `/api/diary`, `/<id>`, `/<id>/photo`, `/<id>/share`, `/cases/diary-photo/<id>` | Survivor owner or staff role + assignment + active diary consent + per-entry share. Strict v2 JPEG/hash/field contracts, signed owner cursor. A local PIN is not an additional server boundary (known Stage 9 product/key issue). |
| `/api/referrals*`, `/referrals`, `/api/shelters*`, `/shelters` | ReferralService uses staff case assignment or exact shelter association and current referral consent; allowlisted transitions; capacity operations constrain shelter authority. Directory is not a placement promise. |
| `/api/audit-log`, `/audit-log` | Survivor scoped access history or authorized assigned staff filtering; no cross-case global audit dump. Untrusted search bound as values. |
| `/contact-push/*`, `/api/contact-push/*` | Capability acceptance + CSRF, contact browser binding for subscription management; ack token is narrow and expiring. Neutral payload, no case API authority. |
| `/api/worker/tick` | Dedicated bearer credential only, bounded processing, evaluation dispatch blocked; no job/recipient data returned. No real dispatch in security tests. |

### SQL review (not a grep-only injection claim)

All repository modules were inspected: user, alert, consent, contact, diary,
case_access, portal, referral, shelter, audit, access_history, push,
notification_outbox and base. Also inspected controller-owned device/invitation
queries, service-owned workflow/consent/storage queries, `db.py`, `schema.sql`,
`avenra/postgres.py` and `sql/001`–`003` migrations. Values travel as parameter
sequences; PostgreSQL translation operates on SQL text, not interpolated values.
Portal/referral/diary/audit filters assemble only application-owned predicates;
sort expressions are fixed. Audit action-prefix choices are fixed mappings.
Alert migration column names are a literal tuple; count-table identifiers now
require a repository-owned allowlist independent of configuration. Schema files
and trusted startup migrations are not HTTP input.

`test_stage7_boundaries.py` executes hostile email, alert search and audit filters
against SQLite while capturing actual SQL/parameters and translating those SQL
templates for PostgreSQL. It verifies no payload enters SQL text or expands the
result scope, and rejects an unapproved dynamic count identifier. Existing
PostgreSQL adapter tests check TLS/parameter contracts. **No live PostgreSQL
penetration test or independent injection assessment was performed.**

### Concrete fixes and verification scope

Failing-first tests reproduced oversized route/filter/body integers causing DB
overflow, coercible referral selectors, unrestricted count-table configuration
and local media symlink traversal. Fixes bound path IDs to positive signed-bigint,
pages to 10,000, filters/body IDs to valid identifiers; reject boolean/string/float
referral authority selectors; allowlist count tables; safely open bounded regular
media without following symlinks. Evidence is served from those bytes without a
second path open or conditional public validators.

The suite also covers revoked assignment, shelter role denials, escaped templates,
persistent pairing limits, missing worker credentials and no-store private errors.
Existing Stage 4/5 ownership, consent, cursor, JPEG and CSRF tests remain required.
JavaScript service-worker checks exclude private APIs, media, staff pages and
authenticated/query/write requests from shell caching.

Residual risks remain explicit: password-only staff authentication until Stage 8;
readable paired-browser APIs/offline profile until an appropriate Stage 9 key
design; notification uncertainty/retry/availability work in Stage 10; CSP/CI and
hosted configuration review in Stage 11; load/accessibility, external review and
physical-device release gates in Stage 12. Application checks cannot prevent an
authorized malicious staff member photographing disclosed data, a compromised
origin, OS-level access or volumetric upstream denial of service. No stage tag
authorizes real-data operation.

## Staff and platform owners

- All onboarding and account management should take place on the website.
- Initial owner setup requires a controlled, expiring, single-use bootstrap
  capability provisioned by the deployment owner. Public first-signup-wins is
  forbidden. Disabling/deleting an owner must never reopen bootstrap.
- Administrative staff request a person with verified contact details,
  organisation, role, scope and reason. An independently authorised platform
  approver accepts/rejects; nobody approves their own request.
- Invitations bind recipient, organisation, role and scope server-side; expire,
  are single use, and are delivered directly to the recipient. Resending/revoking
  invalidates the old invitation. Requesters see status, never invitation secrets.
- Recipients set their own password. Privileges are preset server-side and cannot
  be chosen or elevated through a public form.
- Staff sign-in uses a password plus an email or SMS code; no external
  authenticator application is required. Email is the preferred initial channel;
  SMS delivery may cost money and is vulnerable to number takeover. Email
  two-step verification is not a claim of phishing-resistant MFA.
- Codes expire promptly (target five minutes), are single use, attempt-limited
  and resend-limited, and never appear in logs. Protect account recovery and
  destination changes; require fresh verification for privileged changes.
- Platform approval authority does not imply access to survivor records.

## Survivors

- Survivors register themselves. Public registration can create only survivor
  accounts and must never accept a client-supplied staff role or case grant.
- Offer an app PIN with strict attempt limits and safe recovery. A short PIN
  must not be the sole remote credential or the sole encryption key.
- Offer device-supported WebAuthn/passkeys when available, using the device's
  own biometric or PIN verification. Do not collect facial/fingerprint templates.
  Browser/device support must be checked, including the target Note 9.
- Keep information private by default. Sending an alert grants only defined,
  time-limited information to assigned responders. Location requires explicit
  consent; diary/evidence sharing requires separate, selective permission.
- Check authorization on every request. Closing/revoking access blocks future
  reads and removes stale client displays; it cannot erase information already
  seen, copied or photographed.
- No automatic developer/admin access. If even operators must be unable to read
  stored private material, use an explicitly designed end-to-end encryption and
  selective-disclosure/key-recovery model, not login controls alone.

## Application boundaries

Use secure transport/cookies, server-side scoped permissions, CSRF protection for
staff writes, safe output encoding, parameterised queries, strict input and upload
validation, minimal logs, private storage, backups and tested restoration. Keep
private API responses out of service-worker/browser persistence. Protect against
authentication abuse, permission escalation and cross-organisation access with
negative tests. Operational response coverage must be stated honestly.

These requirements are not all implemented. Never use passing legacy tests or a
Stage 0 tag as evidence that real-data release blockers have been resolved.
## Stage 9 storage verification completion (2026-10-26)

The [private-storage/recovery design](stage-9-private-storage-and-recovery.md)
documents passphrase-encrypted diary queues, prompt-free public-key emergency
queues, RAM-only evidence grants, additive migration, retention tombstones/holds,
and isolated encrypted SQLite restore. These controls do not protect unlocked
memory, prove provider encryption/PITR, approve real survivor use, or replace
independent security/privacy review. The implementation at `4e1e2a6` passed
461 backend tests, 35 focused Stage 9 tests, 34 Node checks, dependency
consistency and the documented Chromium regressions. See the linked final
release evidence for failure history and remaining operational gates.
`stage-9-complete` records local engineering completion only; Stages 10–12
must not be described as completed by this release.
