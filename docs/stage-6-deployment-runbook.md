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
- `DEVICE_TOKEN`: scoped non-default token for controlled demo devices.
- `AVENRA_WEBPUSH_ENABLED`: set to `1` only when `WEBPUSH_KEY_DIR` (`0700` permissions) and `WEBPUSH_SUBJECT` (`mailto:...`) are configured.

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
1. **Consistent SQLite Backup:** Use SQLite's online backup API (`sqlite3 <DB_PATH> ".backup '/path/to/backup.sqlite3'"`) so active WAL/journal state is captured atomically.
2. **Upload Directory Snapshot:** Archive `UPLOADS_DIR` (`diary_*.jpg`) alongside the database snapshot and verify every row in `diary_entries` (`WHERE photo_path IS NOT NULL`) against its recorded `photo_sha256` / `file_hash` via `LocalDiaryStorage.verify_object()`.
3. **Verified Restore Drill:**
   - Restored migrated v3 database + `uploads/` into an isolated temporary directory.
   - Confirmed schema version `3`, user accounts, active/revoked `consents`, `alerts`, `referrals`, `audit_log`, and `diary_entries` integrity digests matched pre-backup state.

### 4.2 Rollback Separation (Application Code vs Database Schema)
- **Application Code Rollback:** Redeploy the previous Git tag/commit. Because all schema migrations in [`db.py`](../db.py) (`v1` -> `v2` -> `v3`) are strictly additive (`ADD COLUMN` / `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`), rolling back application code within the same major schema series does not require dropping columns or resetting data.
- **Database Restore:** Never run `rm` or `seed.reset()` on a non-evaluation database (`seed.py` refuses to reset any database lacking the `evaluation_fixture` marker). If a migration or storage corruption requires full restoration, stop the web/worker processes, restore the verified `.backup` database and `uploads/` snapshot into a new directory, verify `PRAGMA integrity_check` and photo SHA-256 digests, and switch `DATABASE_PATH` / `UPLOADS_DIR`.
