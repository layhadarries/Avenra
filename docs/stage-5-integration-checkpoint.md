# Stage 5 Integration Checkpoint: Evidence Diary, Durable Receipts & Consent Gates

## 1. Repository Baseline & Scope

- **Repository:** `https://github.com/layhadarries/Avenra`
- **Branch:** `main`
- **Baseline Commit SHA (prior to final integration fixes):** `8315f13b8e2a5dba4610eb95594301167233d4ea`
- **Authoritative Specifications Verified:**
  - `Avenra-Tazio-Stages-5-and-6.md` (`T5.0`–`T5.4`)
  - `Avenra-Zulayha-Stages-5-and-6.md` (`Z5.0`–`Z5.5`)
  - [`docs/stage-5-contract.md`](stage-5-contract.md)
  - [`docs/stage-4-integration-checkpoint.md`](stage-4-integration-checkpoint.md)
- **Stage 5 vs Stage 6 Scope Boundary:**
  - Stage 5 delivers the complete offline-first Evidence Diary, durable storage & checksum verification, idempotent upload/replay contract (`v1` legacy + `v2` multipart/JSON), survivor own-entry inspection & per-entry sharing toggle, dual-gated staff case workspace integration, and Quick Exit / BFCache / visibility hygiene.
  - Stage 6A (hosted infrastructure deployment) and Stage 6B (individual survivor device enrollment, mandatory staff MFA, key-recovery architecture, and real-survivor pilot gate) remain strictly separate. **Stage 5 is for fictional evaluation data only and must not be used with real survivor data.**

---

## 2. Summary of Completed Work (`T5.0`–`T5.4` & `Z5.0`–`Z5.5`)

### 2.1 Backend Validation, Canonical Integrity & Idempotency (`T5.0`, `T5.1`)
- **Contract & Additive Migration:**
  - Frozen v2 contract documented in [`docs/stage-5-contract.md`](stage-5-contract.md).
  - Additive schema migrations up to version `4` in [`db.py`](../db.py) and [`schema.sql`](../schema.sql) add `captured_at`, `received_at`, `note_sha256`, `photo_sha256`, `entry_fingerprint`, `contract_version`, `idx_diary_user_client`, and the owner-scoped unique index `uq_diary_user_client` (`UNIQUE(user_id, client_id) WHERE client_id IS NOT NULL`) without resetting or deleting existing Stage 1–4 records.
- **Validation & Canonical Digests ([`avenra/models/diary.py`](../avenra/models/diary.py), [`avenra/services/diary_service.py`](../avenra/services/diary_service.py)):**
  - Rejects client-supplied authority selectors (`user_id`, `case_code`, `owner_id`, `survivor_id`) with `400 invalid_authority_selector`.
  - Normalises note line endings (`\r\n` and `\r` to `\n`), trims outer whitespace, enforces max 4,000 canonical characters, and computes `note_sha256`.
  - Enforces v2 photo bounds ($\le$ 2 MiB -> `413 photo_too_large`, max dimension 1,280 px, max pixels $1,280 \times 1,280$, full Pillow decode + `load()`, and zero EXIF/XMP/ICC/COM metadata -> `400 prohibited_photo_metadata`) while preserving v1 4 MiB legacy queued record compatibility.
  - Verifies `file_hash`, `note_sha256`, `photo_sha256`, and canonical `entry_fingerprint` (`422 hash_mismatch` on mismatch).
  - Separates device-reported `captured_at` from server-generated `received_at`.
  - Handles concurrent identical uploads via `BEGIN IMMEDIATE` and `sqlite3.IntegrityError` replay recovery (`201` on creation, `200` on identical replay, `409 client_id_conflict` on any payload or owner mismatch).

### 2.2 Durable Storage & Orphan Recovery (`T5.2`)
- Implemented [`DiaryStorageBackend`](../avenra/services/diary_service.py), [`LocalDiaryStorage`](../avenra/services/diary_service.py), and [`PrivateObjectDiaryStorage`](../avenra/services/diary_service.py).
- Writes photo bytes to server-generated `diary_<uuid4>.jpg`, flushes and `fsync`s file + directory, and verifies post-write SHA-256 digest and size before committing the database row and `audit_log` event.
- Rolls back and deletes/quarantines (`.quarantine`) unreferenced objects on any storage, database, or audit failure, and provides `DiaryService.reconcile_orphans()`.

### 2.3 Survivor Own-Entry Access & Consent-Aware Staff Workspace (`T5.3`)
- Added survivor endpoints in [`DiaryController`](../avenra/controllers/diary_controller.py):
  - `GET /api/diary?limit=<1..50>&cursor=<signed_token>` (metadata receipts only; HMAC-signed owner-bound cursor).
  - `GET /api/diary/<int:entry_id>` (own-entry detail with `note` and `photo_url`; logs `survivor_diary_entry_viewed`).
  - `GET /api/diary/<int:entry_id>/photo` (hash-verified photo stream; logs `survivor_diary_photo_viewed`).
  - `POST /api/diary/<int:entry_id>/share` (transactional per-entry `shared` update; logs `diary_entry_shared` / `diary_entry_unshared`).
- Enforced `Cache-Control: private, no-store` on all responses via [`apply_security_headers()`](../avenra/security.py).
- Updated [`PortalRepository.access_signature`](../avenra/repositories/portal_repository.py), [`templates/cases.html`](../templates/cases.html), and [`static/js/case-workspace.js`](../static/js/case-workspace.js) so staff view shared entries only when both `diary_sharing` consent and `entry.shared` are active, using safe `textContent` rendering and immediate redaction via `portal.onClear`.

### 2.4 Survivor PWA Offline Capture, Receipt Verification, Detail Viewer & Quick Exit (`T5.4`, `Z5.1`–`Z5.5`)
- Updated [`static/survivor/diary.html`](../static/survivor/diary.html) and [`static/survivor/diary.js`](../static/survivor/diary.js):
  - Canonical CRLF-to-LF note normalisation (`canonicalNote`), `computeNoteSha256`, and sorted-key JSON `computeEntryFingerprint` matching Python byte-for-byte.
  - Client-side Canvas downscaling ($\le$ 1,280 px) + binary JPEG segment sanitiser (`stripJpegMetadataSegments`) stripping all `APP1`–`APP15` (EXIF, XMP, ICC profile) and `COM` segments before computing `photo_sha256` and storing the `Blob` in IndexedDB (`clear-sky-diary-queue`).
  - `multipart/form-data` v2 upload for photo entries and JSON v2 upload for note-only entries (with v1 JSON fallback for legacy queued records), without recompressing photos on retry.
  - Full v2 receipt verification (`verifyReceipt`) before removing queued items from IndexedDB, plus `cleanup_pending` recovery if local deletion fails after a verified receipt.
  - Distinct status handling for permanent errors (`401` -> `auth_expired`, `400`/`403`/`409`/`413`/`422` -> `needs_attention`) vs transient errors (`503`/network -> `upload_failed`), halting infinite automatic retry loops on permanent errors.
  - Survivor own-entry detail viewer (`#diary-entry-detail`) fetching `/api/diary/<id>` and `/api/diary/<id>/photo` into revocable `blob:` URLs, plus per-entry share/unshare controls (`/api/diary/<id>/share`) with server-state refresh on uncertain network timeouts.
  - Hardened `quickExit()` (`Escape` key, `#quick-exit-btn`, `pagehide`, `visibilitychange`) clearing unsaved inputs, revoking all preview/detail `blob:` URLs, clearing DOM entries, preserving IndexedDB queues, and calling `location.replace('/survivor/cover.html')`.
- Fixed regressions in [`static/survivor/privacy.js`](../static/survivor/privacy.js) (restored `clearPrivate()` and `#access-more` / `#privacy-refresh` listeners), [`static/survivor/index.html`](../static/survivor/index.html) (restored `#quick-exit` and unchecked `#share-alert-location`), [`static/survivor/queue.js`](../static/survivor/queue.js) (fixed `migrateLegacy` to open `'cape-weather-queue'` instead of deleting from `'clear-sky-queue'`), and [`static/survivor/cover.html`](../static/survivor/cover.html) (included `shell.js` and `queue.js`, removed automatic geolocation prompt and `localStorage` usage on load).
- **Branding Standardisation Resolution:** Standardized across all PWA pages, `manifest.json`, `service-worker.js`, and tests on **`Clear Sky`** (superseding the earlier working title "Cape Weather" in initial planning docs, while `queue.js` retains read-only migration from `'cape-weather-queue'` for backward compatibility).

---

## 3. Verification Evidence & Test Results

All automated verification suites were executed and passed:

| Suite | Command | Result |
| :--- | :--- | :--- |
| Python Unit & Integration Tests | `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v` | **PASS (291 tests, 0 failures, 0 errors)** |
| Stage 0 Security & Gunicorn Smoke Check | `.venv/bin/python tools/check_stage0.py` | **PASS** |
| Node PWA Shell & Service Worker Contract | `node --test tests/pwa-shell.cjs tests/service-worker-contract.cjs` | **PASS (5 tests, 0 failures)** |
| Stage 1 Staff Dashboard Browser Suite | `.venv/bin/python tests/stage1_dashboard_browser.py` | **PASS** |
| Stage 2 Survivor PWA Alert & Queue Browser Suite | `.venv/bin/python tests/stage2_pwa_browser.py` | **PASS** |
| Stage 3 Staff Case Workspace Browser Suite | `.venv/bin/python tests/stage3_case_browser.py` | **PASS** |
| Stage 4 Staff Audit Log Browser Suite | `.venv/bin/python tests/stage4_audit_browser.py` | **PASS** |
| Stage 4 Combined PWA Privacy & Consent Browser Suite | `.venv/bin/python tests/stage4_pwa_browser.py` | **PASS** |
| Stage 5 End-to-End PWA Diary & Staff Sync Browser Suite | `.venv/bin/python tests/stage5_pwa_browser.py` | **PASS** |
| Git Whitespace & Formatting Check | `git diff --check` | **PASS (0 issues)** |

---

## 4. Samsung Galaxy Note 9 Physical Device Acceptance Protocol (`Z5.1`–`Z5.5`)

- **Automated Mobile Emulation Status:** **PASS** — Verified in headless Chromium mobile emulation (`412×846` / `390×844` touch viewport, service worker active, offline mode, IndexedDB persistence across tab close/reopen, Canvas JPEG compression & segment stripping, and Quick Exit).
- **Physical Samsung Galaxy Note 9 Hardware Status:** **NOT TESTED (BLOCKED on physical device access in CLI environment)**.
- **Reproducible Note 9 Manual Acceptance Checklist (Before Physical Device Sign-Off):**
  1. Connect the Samsung Galaxy Note 9 (Android 10 / One UI 2.5, Samsung Internet or Chrome Mobile, `412×846` CSS viewport) to the local evaluation server over HTTPS/port-forwarding.
  2. Open `/survivor/diary.html`, attach a camera/gallery photo (> 3 MB with EXIF GPS data), verify preview shows `1280×...px, EXIF metadata stripped` and compressed size $\le$ 2 MB.
  3. Enable Airplane Mode, tap **Save to Diary**, confirm badge reads `Saved on phone (Pending upload)`, close the browser tab completely, and reopen `/survivor/diary.html` while still in Airplane Mode to verify IndexedDB persistence.
  4. Disable Airplane Mode, tap **Refresh & retry uploads**, confirm badge transitions to `Saved to account (Receipt #<id>)`, tap **View entry** to inspect the note and authenticated photo, and toggle **Share with responder** / **Make private**.
  5. Tap **Quick exit** (`< 400 ms` target), confirm immediate redirect to `/survivor/cover.html` with Back button not exposing the diary view.

---

## 5. Stage 6 Handoff & Remaining Pilot Gates

- **Stage 6A (Hosted Deployment):** Configure production TLS/HSTS, Gunicorn behind reverse proxy, private object storage (`PrivateObjectDiaryStorage`), and automated encrypted backups (`docs/stage-6-deployment-runbook.md`).
- **Stage 6B (Real-Survivor Pilot Gate):** Replace prototype `X-Device-Token` (`demo-device`) with individual per-device enrollment and revocable pairing, enforce mandatory staff MFA, complete client-side at-rest encryption key management, and complete physical Note 9 device sign-off (`docs/stage-6-data-lifecycle-and-pilot-gate.md`, `docs/stage-6-security-evidence-matrix.md`).
