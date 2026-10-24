# Stage 5 Integration Checkpoint: Evidence Diary, Durable Receipts & Consent Gates

## Summary of Completed Backend & Staff Workspace Work (`T5.0`–`T5.4`)

1. **Contract & Additive Migration (`T5.0`, `T5.1`, `T5.4`):**
   - Updated [`docs/stage-5-contract.md`](stage-5-contract.md) to freeze the v2 upload/receipt contract (`multipart/form-data` binary upload + `application/json` legacy/v2 queue compatibility).
   - Added additive schema migration version `3` in [`db.py`](../db.py) and [`schema.sql`](../schema.sql) for `note_sha256`, `photo_sha256`, `entry_fingerprint`, `contract_version`, and `idx_diary_user_client` without resetting existing users, consents, alerts, or audit records.
   - Enforced strict input validation in [`DiaryService`](../avenra/services/diary_service.py):
     - Rejects client-supplied authority selectors (`user_id`, `case_code`, `owner_id`, `survivor_id`) with `400 invalid_authority_selector`.
     - Canonicalises note text (`\r\n` and `\r` normalised to `\n`, outer whitespace stripped, max 4,000 characters) and computes `note_sha256`.
     - Enforces v2 photo limits ($\le$ 2 MiB -> `413 photo_too_large`, max dimension 1,280 px, full Pillow decode + `load()`, and zero EXIF/XMP/ICC/comment metadata -> `400 prohibited_photo_metadata`) while preserving 4 MiB legacy v1 queue compatibility.
     - Computes and verifies `photo_sha256`, `file_hash`, and canonical `entry_fingerprint` (`422 hash_mismatch` on mismatch).
     - Separates device-reported `captured_at` from server-assigned `received_at`.

2. **Durable Storage & Idempotent Replay (`T5.2`):**
   - Implemented [`DiaryStorageBackend`](../avenra/services/diary_service.py), [`LocalDiaryStorage`](../avenra/services/diary_service.py), and [`PrivateObjectDiaryStorage`](../avenra/services/diary_service.py).
   - Writes photo bytes to a unique server-generated object name (`diary_<uuid4>.jpg`), flushes and `fsync`s file + directory, and verifies post-write SHA-256 digest and byte size before committing the SQLite row and `audit_log` event inside a `BEGIN IMMEDIATE` transaction.
   - Removes or quarantines (`.quarantine`) orphan objects if the database transaction fails, and provides `DiaryService.reconcile_orphans()` for interrupted cleanup.
   - Replaying the same `client_id` and identical canonical payload verifies the stored object on disk/storage and returns `200 OK` with the original receipt (`503 diary_storage_unavailable` if the underlying object is missing or corrupted; `409 client_id_conflict` if any payload field or owner differs).

3. **Survivor Own-Entry Access & Consent-Aware Staff Workspace (`T5.3`):**
   - Added survivor endpoints in [`DiaryController`](../avenra/controllers/diary_controller.py):
     - `GET /api/diary?limit=<1..50>&cursor=<signed_token>`: HMAC-signed, owner-bound cursor pagination returning metadata receipts only (no raw note text).
     - `GET /api/diary/<int:entry_id>`: own-entry detail with `note` and `photo_url`.
     - `GET /api/diary/<int:entry_id>/photo`: authenticated photo streaming after SHA-256 verification.
     - `POST /api/diary/<int:entry_id>/share`: transactional per-entry `shared` toggle (`diary_entry_shared` / `diary_entry_unshared`).
   - Enforced `Cache-Control: private, no-store` across all diary, case, and API responses in [`avenra/security.py`](../avenra/security.py).
   - Updated [`PortalRepository.access_signature`](../avenra/repositories/portal_repository.py), [`templates/cases.html`](../templates/cases.html), and [`static/js/case-workspace.js`](../static/js/case-workspace.js) so assigned staff view shared diary entries safely via `textContent`, and open screens clear immediately on consent withdrawal, per-entry unsharing, case unassignment, or session expiry.

## Automated Verification Commands (Fish-Compatible)

```fish
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | tee /tmp/avenra-stage5-unit.log
.venv/bin/python tools/check_stage0.py
git diff --check
```

## Known Prototype Limitations Carried into Stage 6

- Survivor device authentication in the evaluation prototype still uses the shared `X-Device-Token` header (`demo-device` default unless overridden by `DEVICE_TOKEN`). Individual per-device enrollment and revocable pairing are gated under Stage 6B before any real survivor pilot.
- Staff accounts use password + session rotation + CSRF protection; mandatory staff MFA is required before Stage 6B pilot sign-off.
