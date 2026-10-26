# Security engineering evidence matrix (OWASP Top 10 & ASVS)

This matrix records implemented controls and automated verification evidence across Stages 5 and 6A. It is engineering verification evidence, not a formal external security certification.

## Stage 9 private-storage follow-up (2026-10-26)

Baseline `46c791e`; design, operator commands, migration/key custody and limits:
[Stage 9 private storage and recovery](stage-9-private-storage-and-recovery.md).
Memory-only `X-Vault-Unlock` replaces reusable evidence cookies. **35 focused
Python tests**, **34 Node checks**, and `pip check` pass. Chromium vault,
encrypted-alert, ownership queues, Stage 5 diary, weather-tap, Stage 2 HELP,
Stage 3 case and Stage 4 audit scripts pass. Full backend regression passed
**461 tests in 747.584 seconds** on implementation `4e1e2a6`. Focused Python,
Node, dependency consistency and both Stage 9 browser scripts were rerun before
the completion tag and passed. Running many crypto/browser suites concurrently exposed timing
failures; affected HELP/vault scripts passed again in isolation. This is not
evidence of physical-device performance.
The first aggregate run executed 459 tests with 14 failing assertions because
the database-free diary replay mock fabricated retention tombstones. Its fixture
now explicitly reports no tombstone; all 12 replay tests and all 48 Stage 4 tests
pass. The fresh 461-test pass supersedes that failed run; the prior run must not
be reported as a full pass. `stage-9-complete` records the bounded local
engineering scope described in the release evidence, not hosted rollout,
provider DR, independent review or real-data approval. Existing resource-cleanup
warnings remain. Stages 10–12 remain separate, incomplete work.

## Stage 8 identity follow-up (2026-10-26)

Baseline: `8c4683d` / `stage-7-complete`. See
[staff MFA/recovery and rollout boundaries](staff-email-invitations.md#mandatory-staff-mfa-and-recovery-stage-8).
All records/providers are isolated fixtures; no real email/notification, live DDL,
provider-setting change or deployment is part of this evidence.
Full Python regression passed **426 tests**; the 15 new MFA checks, 30 Node checks,
`pip check` and six Chromium scripts (invitation, weather-tap, Stage 2 HELP,
Stage 5 diary, Stage 3 case and Stage 4 audit) passed. Fixture resource-cleanup
warnings remain; this is not a warning-free or hosted acceptance result.

| Requirement | Check | Actual result | Limits |
|---|---|---|---|
| Mandatory staff MFA | `test_stage8_mfa.py`; password/activation/evaluation challenge cannot authorize staff until MFA; no legacy password-only session | Focused tests pass after failing-first reproduction | TOTP is not phishing-resistant; evaluation fixture access still requires MFA, and is forbidden on hosted/production runtime |
| Enrollment, replay and recovery | Five-minute version-bound one-use challenges; PyOTP counter reuse, recovery-code replay/concurrency, audit rollback, confirmed-secret/cookie checks | Focused checks pass; only encrypted secrets/digests retained | Recovery codes shown once; lost response can require operator recovery; clock synchronization required |
| Reset and revocation | Explicit CLI confirmation + non-sensitive verification reference; auth-version invalidation, suspension/expiry checks, non-staff session rejection | Focused checks pass | Independent identity verification is a required human process, not technically attested by a CLI flag |
| Invitations and least privilege | Existing expiry/resend/single-use/concurrent activation tests now complete real MFA; assignment/role/device tests retained | Invitation suite and Chromium invitation acceptance passed | No real invitation or external inbox delivery tested |
| Persistent abuse/privacy | Keyed account/address counters, bounded cardinality/saturation/expiry, generic auth errors, no rejected-email logging, private/no-store MFA HTML | Focused and HTTPS CSRF checks pass | Targeted/shared-IP lockout and upstream DDoS remain possible |
| Production/key guard | Missing/malformed separate encryption key fails startup; evaluation production mismatch rejected; additive version-7 migration | Local configuration tests pass | No hosted migration/key provisioning or PostgreSQL rollout exercised |
| Emergency and offline regression | Weather-tap, Stage 2 HELP, Stage 5 diary Chromium scripts; Node contracts | Browser scripts and 30 Node checks pass through real staff MFA | Emulation/injected GPS, no physical phone or independent review |

## Stage 7 engineering follow-up (2026-10-26)

Threat model, trust-boundary flows and route/repository review are in
[`SECURITY_REQUIREMENTS.md`](SECURITY_REQUIREMENTS.md#stage-7-practical-threat-model-and-routerepository-audit).
Baseline was `fd282b9`; tests use isolated fictional records with outbound providers
disabled. This follow-up does not claim completion of later stages or real-data approval.
Full Python regression: 411 tests passed (existing fixture resource warnings remain).
Stage 4 audit and staff-invitation Chromium browser scripts also passed.

| Requirement | Check | Actual result | Limits |
|---|---|---|---|
| Concrete malformed-input fixes | `test_stage7_boundaries.py`: route/filter/body overflow, referral coercion | 13 focused tests pass after failing-first reproduction | SQLite; translated SQL templates, not a live hosted DB assessment |
| Injection boundaries | Captured actual repository SQL/bindings, hostile email/search/case filters, rejected dynamic table identifier | Payloads remain parameters; no scope expansion or table destruction | Manual repository/control-flow review supplements tests; not a penetration-test claim |
| Private local media | No-follow bounded regular-file read and byte-based private serving | Symlink regression and existing diary browser acceptance pass | Server/root compromise remains outside this protection |
| Ownership, roles, escaping, abuse, privacy | Assignment revocation, shelter denials, escaped staff name, persistent pairing limit, worker auth; Node shell-cache exclusions | Focused suite and 30 Node checks pass | Staff MFA/local encryption remain later-stage gaps |
| UX/security regression | `stage3_case_browser.py`, `stage5_pwa_browser.py`, `weather_tap_browser.py` | Chromium acceptance passed, including consent/revocation and offline paths | Emulation/injected GPS, not physical phones; WebKit host libraries unavailable |

| Task ID | Control / OWASP ASVS Area | Commit / Baseline | Environment | Harness / Browser | Expected Outcome | Actual Outcome | Result | Owner | Retest Date |
|---|---|---|---|---|---|---|---|---|---|
| `T5.1-VAL` | Strict input validation, no type coercion, authority selector rejection (`POST /api/diary`) | `Stage 5 v2` | Python 3.14 / SQLite (`unittest`) | `tests/test_stage5_diary_retries.py` | Non-boolean `shared`, non-string `note`, or client-supplied `user_id`/`case_code`/`owner_id` rejected with `400` | `400 Bad Request` (`invalid_authority_selector`, `shared_must_be_boolean`, `invalid_note`); zero DB writes | PASS | Tazio | 2026-10-25 |
| `T5.1-IMG` | JPEG decode, pixel/dimension bounds (1,280 px, 2 MiB v2), EXIF/XMP/ICC/COM metadata rejection | `Stage 5 v2` | Python 3.14 / Pillow (`unittest`) | `tests/test_stage5_diary_images.py`, `tests/test_stage5_diary.py` | Fake headers, truncated JPEGs, >1,280 px, >2 MiB (`413`), and EXIF/COM segments (`400`) rejected | All malformed/metadata-bearing images rejected before storage; clean JPEGs accepted byte-for-byte | PASS | Tazio | 2026-10-25 |
| `T5.1-HASH` | Canonical SHA-256 digests (`note_sha256`, `photo_sha256`, `entry_fingerprint`) & replay conflict detection | `Stage 5 v2` | Python 3.14 (`unittest`) | `tests/test_stage5_diary_retries.py`, `tests/test_stage5_diary.py` | Mismatched digest -> `422 hash_mismatch`; modified note/share/time under existing `client_id` -> `409 client_id_conflict`; identical retry -> `200 OK` | `422`, `409`, and `200` returned deterministically; Unicode & CRLF->LF canonicalised | PASS | Tazio | 2026-10-25 |
| `T5.2-DUR` | Atomic receipt durability (`fsync`, post-write checksum verify, rollback & orphan quarantine) | `Stage 5 v2` | Python 3.14 (`unittest`) | `tests/test_stage5_diary_storage.py` | Disk/DB/audit failure returns `503 diary_storage_unavailable`, rolls back DB row, and deletes/quarantines orphan file | `503` returned on simulated `fsync`, DB, and audit failures; corrupt/missing photo on replay returns `503` | PASS | Tazio | 2026-10-25 |
| `T5.3-ACL` | Object-level access control (IDOR prevention), dual-gate consent, per-entry share/unshare, signed cursor | `Stage 5 v2` | Python 3.14 (`unittest`) | `tests/test_stage4_diary_access.py`, `tests/test_case_workspace.py` | Cross-survivor detail/photo/share/cursor rejected (`404`/`400`); shelter role (`403`) & unassigned admin/responder (`404`) blocked; unshare/withdrawal hides entry & updates `access_signature` | All cross-owner and unauthorized staff requests blocked without logging false `diary_viewed` / `diary_photo_viewed` events | PASS | Tazio | 2026-10-25 |
| `T5.3-DOM` | DOM XSS prevention, `Cache-Control: private, no-store`, and workspace clearing on revocation | `Stage 5 v2` | Python 3.14 (`unittest`) | `tests/test_case_workspace.py`, `tests/test_stage4_diary_access.py` | All private responses include `Cache-Control: private, no-store`; `case-workspace.js` renders via `textContent` and clears on `portal.onClear` | Verified `private, no-store` header on API, photo, and case pages; no `innerHTML` used for untrusted fields | PASS | Tazio | 2026-10-25 |
| `T6.1-SSRF` | Web Push endpoint allowlist, HTTPS/port 443 enforcement, no redirects, and DNS rebinding IP check | `Stage 6A` | Python 3.14 (`unittest`) | `tests/test_webpush.py` | Private (`10.0.0.1`, `192.168.1.1`), loopback (`127.0.0.1`, `::1`), and cloud metadata (`169.254.169.254`, `fe80::1`) IPs and non-allowlisted hosts rejected | `validate_subscription` and `verify_public_endpoint_dns` reject all non-global IPs and untrusted hosts | PASS | Tazio | 2026-10-25 |
| `T6.1-CSRF` | Staff CSRF protection, same-origin `Origin` enforcement, session rotation (`auth_version`), and rate limiting | `Stage 6A` | Python 3.14 (`unittest`) | `tests/test_avenra.py`, `tests/test_webpush.py`, `tools/check_stage0.py` | Missing/invalid CSRF token -> `400`; cross-origin write -> `403`; push invite >5/hr -> `429`; test push >1/min -> `429` | All cross-origin and unauthenticated/CSRF-missing writes rejected; rate limits enforced | PASS | Tazio | 2026-10-25 |
