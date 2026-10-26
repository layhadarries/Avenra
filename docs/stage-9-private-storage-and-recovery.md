# Stage 9: private offline storage and isolated recovery

Baseline: `46c791e` (`stage-8-complete`). Engineering work only; not permission
to onboard survivors, deploy, change providers or run hosted migrations.
Release status: **Stage 9 local engineering gates complete** (2026-10-26).
Verified implementation: `4e1e2a6`; the release adds only completion evidence.
The `stage-9-complete` tag covers this bounded engineering scope, not hosted
rollout, provider disaster recovery, independent review or real-data approval.

## Protection and remaining exposure

- Diary notes and derivative photos in IndexedDB use AES-256-GCM, fresh 96-bit
  nonces and owner/client/purpose-bound associated data. A random 256-bit data
  key is wrapped with a separate 15–128-character vault passphrase using
  PBKDF2-SHA256 (600,000 iterations, random 128-bit salt) and AES-GCM. Only the
  wrapped key persists. Initial online setup enforces passphrase strength.
- Keys and the server evidence grant live only in page memory. Server setup and
  unlock verify the passphrase and issue a random `X-Vault-Unlock` grant, stored
  hashed server-side and bound to owner, paired device and credential version
  for 900 seconds. Copied cookies alone do not unlock evidence. Lock revokes
  the exact grant, so delayed old lock requests cannot revoke a newer unlock.
  Page hide/visibility loss/Quick Exit clears keys, grant and rendered evidence.
  Offline-only unlock cannot mint a server grant: reconnect asks for the
  passphrase again. A lost passphrase cannot recover unsent passphrase-encrypted
  records; device recovery is not passphrase recovery.
- Emergency capture never invokes the vault or prompts. RSA-OAEP-SHA256 wraps
  a random AES-256-GCM key for each queued payload. Optional location is sealed
  separately and omitted from transport if consent is revoked or unknown.
  Missing public-key cache still permits a minimal GPS-free record with unknown
  capture time. Late GPS remains a separate authorized update, not an alert replay.
- Existing diary migration uses compare-before-write IndexedDB transactions.
  Storage/quota/crypto failure retains the original. Foreign/unbound records are
  public-key sealed without adopting an owner, deleting or sending them. Known
  owners can rewrap opaque records only with server-verified vault authority;
  unbound owner `0` is not recoverable through survivor APIs. Legacy plaintext
  remains exposed until a successful migration: this is not retroactive erasure.
- Visible queue owner/client IDs, sizes and ciphertext counts remain metadata.
  Same-origin malicious JavaScript, an unlocked page, OS screenshots, original
  gallery photos, browser/OS backups and a compromised server are not protected
  by this feature. RSA sealing is transport-at-rest protection, **not end-to-end
  encryption against the application server**. Primary server notes/photos are
  still readable by the application; provider disk/KMS controls require separate
  operational evidence. No forensic deletion or court certification is claimed.

## Additive rollout and key custody (not performed)

1. Use only an approved maintenance plan, an independently verified backup and
   separate key custody. Never change an existing key to make startup pass.
2. Apply `sql/005_survivor_vault.sql` then `sql/006_retention_controls.sql` for a
   separately approved PostgreSQL rollout. SQLite initialization is additive;
   schema versions 8 and 9 retain existing records. Neither SQL migration was
   executed against a hosted database for this work.
3. `tools/queue_keys.py --output <private-new-key-file>` creates a 3072-bit RSA
   key without overwrite (owner-only mode). Provision `OFFLINE_QUEUE_PRIVATE_KEY_PEM`
   through a secret manager, not a repository or log. Retain previous private
   keys separately in `OFFLINE_QUEUE_RETIRED_KEYS_JSON` (up to five); pending
   queues may still need them. Tests verify a rotated active key cannot decrypt
   old records without the retained key. Key retirement requires an approved
   queue-age/recovery policy, not merely a successful deployment.
4. Backups must not contain private queue keys, MFA/subscription keys, runtime
   environment files or backup encryption keys. Custodians must inventory and
   exercise restoration of those keys separately. File separation is not KMS,
   independent custody or a proven hosted key-recovery process.
5. Rollback must preserve additive tables, wrapped keys, ciphertext and tombstones.
   Do not deploy an older client that writes plaintext or bypasses vault guards.
   No destructive down-migration is provided. Pause an unsafe release rather
   than downgrade confidentiality; an actual hosted rollback drill is outstanding.

## Retention/deletion: explicit operator action only

There is no public destructive maintenance endpoint or automatic deletion schedule.
An active assigned admin identity is rechecked against current database authority.
Use a non-sensitive approval ticket reference, not a survivor name or incident note.

```text
flask --app app retention --actor-id <admin-id> --case-code <case> --kind diary --before <aware-UTC-cutoff>
```

The default is a read-only, content-free preview. Scope is at most 100 records;
use repeated exact `--entry-id` selectors for larger cases. Apply requires the
unchanged `--confirm-plan <preview-hash>`, `--verification-reference <ticket>`
and `--apply`. Hosted/production writes additionally require
`--allow-hosted-apply`; this flag does not constitute organizational approval.
`retention-hold` records/releases audited holds. `retention-media` previews
pending cleanup; explicit apply handles at most ten jobs per invocation.

Diary deletion commits audit, logical deletion, replay tombstone and media jobs
together. Media cleanup rechecks holds, remaining references, safe names and
checksums; failures remain visible/retryable. Database-photo deletion and audit
commit together. Local unlink and database audit cannot be one atomic operation:
an interrupted cleanup is reconciled as already absent on retry, not evidence of
forensic erasure. Backups/browser copies remain separate retention obligations.

Resolved-alert location purge preserves the alert, workflow, outbox, consent
epochs and audit, and excludes alerts with pending/processing notification jobs.
Late-location callbacks cannot resurrect purged coordinates. Unknown/ambiguous
receipt times are not invented; aware times are compared in UTC. Consent
withdrawal stops disclosure but is not deletion, and a hold does not grant access.
Account-wide deletion, backup expiry and a legally approved retention schedule
are not implemented by these bounded record-level commands.

## Isolated SQLite/storage restore drill

`tools/isolated_backup.py` supports `generate-key`, `create` and `restore`.
Create needs `--source-sqlite`, `--uploads`, `--archive`, `--key-file`.
Restore needs `--archive`, `--key-file`, `--target` and explicit `--isolated`.
The CLI requires the key outside the archive directory and owner-only permissions.
Keep archives and keys out of the working tree; no private bytes are printed.

Snapshots use SQLite backup under a writer reservation and a bounded authenticated
Fernet archive. They retain exact rows/timestamps, database-backed photos,
referenced files and retained quarantine/orphan bytes. Restore authenticates the
archive, validates manifest/checksums and database integrity, and refuses existing
targets. Incomplete copies keep `RESTORE_INCOMPLETE`; successful targets keep
`ISOLATED_RESTORE_DO_NOT_DEPLOY`. The application refuses both marked targets.
No worker/provider is invoked. Runtime budget is 128 MiB, not a large production
backup facility. Protect the host temporary directory/disk: the SQLite snapshot
exists in a private temporary directory before archive encryption.

This is **local SQLite/private-storage engineering evidence only**, not PostgreSQL
PITR, Supabase provider backup acceptance, independent key custody, multi-region
recovery, or a measured production RPO/RTO. Production restore/rollback approval
and reapplication of deletion/hold policy to old backups remain operator gates.

## Evidence and release gate

Failing-first tests exposed plaintext queue storage, missing retention/restore
controls, unsafe timestamp classification, malformed restore manifests, blocked
legacy plaintext and cookie-only evidence access. Focused Python, Node and
Chromium suites exercise their fixes, real receipt IDs, migration failure/retry,
revocation/foreign-owner boundaries and isolated restore fidelity.

See `tests/test_stage9_*.py`, `tests/storage-vault.cjs`,
`tests/stage9_vault_browser.py` and `tests/stage9_alert_queue_browser.py`.
### Final release evidence

| Gate | Result |
|---|---|
| Full backend regression | `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`: **461 tests passed**, 747.584 seconds; existing unclosed-file/database resource warnings remain |
| Focused Stage 9 backend | **35 tests passed**, including grant ownership/expiry/revocation, retained-key rotation, generation/no-overwrite, tombstones/holds/audit rollback, malformed archive rejection and exact isolated restore fidelity; rerun passed before tagging |
| JavaScript contracts | `node --test tests/*.cjs`: **34 checks passed**, including maximum-size legacy photo encryption/reopen; rerun passed before tagging |
| Runtime dependency consistency | `.venv/bin/pip check`: passed; not a vulnerability scan or SBOM |
| Stage 9 Chromium acceptance | Vault and encrypted-alert browser scripts rerun and passed on the verified implementation; copied cookies cannot read evidence, grants are not persisted, offline reopen/migration failures preserve records, revoked GPS is omitted and minimal capture remains available |
| Existing browser regressions | Stage 5 diary, weather-tap, Stage 2 HELP, hosted ownership diary/alert queues, Stage 3 case and Stage 4 audit passed during Stage 9 verification |
| Review and release hygiene | Reviewed crypto/key lifecycle, API guards, additive migrations, retention/restore failure handling and bounded operator tools; staged diff whitespace/credential-pattern checks passed, no private runtime artifacts included; unrelated configuration/package files excluded |

The first aggregate run (459 tests) failed on 14 assertions because a generic
database-free replay mock fabricated retention tombstones. The fixture now
explicitly reports no tombstone; the fresh **461-test pass** supersedes that
failed run, without changing production tombstone checks. Excessive concurrent
crypto/browser runs also exposed timing failures; affected HELP/vault scripts
passed separately. No physical-device performance claim follows from those runs.

Chromium `156.0.8078.4` mobile/touch emulation and injected lifecycle/GPS are not
physical Android/iPhone testing. WebKit host libraries, independent security,
privacy/safeguarding review and real operational approval remain outstanding.
Stages 10–12 are not completed by this release. No hosted migration, deployment,
live provider change or real invitation/notification was performed.
