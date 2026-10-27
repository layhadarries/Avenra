# Hosted PostgreSQL recovery evidence

## Current result — 2026-10-27

**Blocked; hosted recovery remains unverified.** This session has an application
database connection but no Supabase Management API backup-read token, provider
backup export or isolated restore target. No hosted restore was performed.
The operator selected private backup-read access as the next step and confirmed
that an isolated restore target is not yet available.
Backup/PITR configuration, backup availability, required-key recovery and measured
RPO/RTO have not been established. Local SQLite restore tests do not establish them.

The read-only check returned a blocked result on 2026-10-27 because the required
configuration was absent. Six offline tests passed for metadata validation,
content-free output, verified TLS, redirect rejection and missing-access behavior;
they also passed within the 536-test full suite. These tests use fictional exports.

## Read-only backup inventory

Provision `SUPABASE_ACCESS_TOKEN` privately with the provider's `backups_read`
permission and set `SUPABASE_PROJECT_REF`. Then run:

```sh
python tools/check_hosted_recovery.py
```

Alternatively inspect a privately stored export of the Management API's
`GET /v1/projects/{ref}/database/backups` response:

```sh
python tools/check_hosted_recovery.py --from-json /private/path/backup-metadata.json
```

The command uses verified TLS, rejects redirects, makes only the inventory GET
request and emits allowlisted flags, counts and UTC timestamps. It excludes raw
provider fields, credentials, database contents and project identifiers. Exit 2
means unavailable/invalid metadata or no observed backup availability. Exit 0 means
backup availability was observed; `recovery_verified` remains false until an
actual independently recorded restore drill is completed. An operator export's
inspection time is not proof of when the provider produced that export.

## Isolated restore drill and measurements

1. Record the provider's actual backup/PITR window, backup identifier, target UTC
   time and recovery objectives. Preserve the provider evidence privately. A PITR
   flag or a backup listing alone does not prove that WAL replay succeeds.
2. Provision a separate restore target and an isolated application environment.
   Use fictional test records. Arrange worker/cron suppression and outbound-deny
   controls **before** restoring: copied `pg_cron`, `pg_net`, database webhooks,
   Vault credentials or queued jobs can send traffic without Flask running.
   Set `AVENRA_SMS_ENABLED=0`, `AVENRA_WEBPUSH_ENABLED=0` and
   `AVENRA_PUSH_SELF_TEST=0`; omit live SMTP, Twilio and Web Push credentials.
3. Use the provider's documented restore-to-new-project procedure for the chosen
   backup type. The in-place PITR restore endpoint operates on its named project;
   it is not an isolated-target check. Record restore start and completion times.
4. Verify the target identity and TLS before running application checks. Verify
   schema migrations, constraints, row counts and stored photo SHA-256 values.
   Compare fictional markers before/after the chosen recovery point to show which
   acknowledged writes survived and which were correctly excluded.
5. Recover separately held application keys through the normal custodian process.
   Exercise MFA, encrypted subscriptions and retained offline queue keys with
   fictional fixtures. A database backup alone cannot recover external secrets.
   Verify any private files or Storage API objects separately from database rows.
6. Reconcile retention holds, deletion tombstones and revoked accounts/devices
   against records newer than the recovery point before any resumed service.
   Confirm case authorization and consent enforcement on the restored application.
7. Record measured loss relative to the last acknowledged fictional write and the
   time from the declared recovery start to successful application acceptance.
   Report these measured values against the chosen RPO/RTO objectives, along with
   failed checks. A successful provider restore completion is only one milestone.

Keep identifiers, private backup exports, keys and restored data outside Git.
Commit only the content-free outcome, test scope, timings and an evidence reference.
`tools/stage6_restore.py` handles a legacy bounded encrypted row-snapshot format;
it does not exercise provider PITR and is not a substitute for this drill.

## Provider references

- [Supabase backup inventory API](https://supabase.com/docs/reference/api/v1-list-all-backups)
- [Backups, PITR and their coverage](https://supabase.com/docs/guides/platform/backups)
- [Restore to a new project](https://supabase.com/docs/guides/platform/clone-project)

The provider documents that database backups exclude Storage API object bytes,
custom-role passwords may require reprovisioning, and deleting a project also
deletes its provider backups. Retain an independently controlled recovery copy
and key custody appropriate to the chosen recovery objectives.
