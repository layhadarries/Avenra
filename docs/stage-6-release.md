# Stage 6 release boundaries and operator runbook

## Scope

This delivery targets Stage 6A: a hosted fictional-data hackathon demonstration.
It is not a security certification, guaranteed rescue service, or approval to process real survivor evidence.
Stage 6B requires the partner, safeguarding, MFA, encryption/key custody, deletion/retention, recovery and independent review gates in `stage-6-data-lifecycle-and-pilot-gate.md`.
Do not label the entire project "100% secure" or pilot-ready because tests pass.

## Included engineering

Individual one-use device pairing, case recovery with explicit assignment checks, credential revocation, exact-origin writes, owner-bound offline queues, durable-receipt cleanup, a neutral installation page, stable public QR, private hosted diary photos, verified database TLS, bounded authenticated Web Push processing, hosted scheduler setup, encrypted row snapshots, and local/live acceptance tooling.

Private photo bytes are stored in `avenra.diary_objects` in the SAME database transaction as diary metadata and its audit event. No public bucket or evidence URL is created. Default object-byte budget is 80 MiB, maximum configured budget 100 MiB. Database overhead and other records count toward provider quotas too; monitor the actual project usage. This bounded demo choice is not an unlimited media storage architecture. Existing local photo files are not silently imported or discarded.

`verify-full` validates the database certificate and hostname. The public Supabase 2021 CA is bundled as Python data so serverless packaging cannot omit it. Its SHA-256 is `700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`. An operator can supply `PGSSLROOTCERT` for a project with a different CA; never weaken TLS to make a connection succeed.

## Local release checks

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
