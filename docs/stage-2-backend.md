# Stage 2 backend and dashboard checkpoint

Five trusted contacts maximum. Contact reads expose masked numbers. Existing contact IDs may be submitted without a phone to preserve that recipient. Invalid/foreign IDs and invalid complete lists are rejected. Unchanged phone numbers retain recipient IDs and queued jobs; removing a recipient removes its linked jobs.

Alert creation, notification jobs and creation audit commit together. Queued does not mean sent. Workers claim jobs atomically and commit before external calls. Outcomes are accepted, failed, unknown or cancelled; accepted does not mean delivered or read. Provider identifiers are stored privately for investigation/status verification. The authenticated delivery-status reconciliation path is still future work; this stage does not claim verified end-to-end delivery tracking.

Five distinct notification alert batches per survivor per rolling hour are attempted. Each batch can notify at most five contacts. Later alerts are still stored and displayed; their contact jobs are cancelled with rate_limited and shown as skipped. Failures/unknown attempts consume the budget. Existing jobs for a permitted alert share its reservation. This is a notification limit, not an alert-creation throttle.

Location consent and recipient ownership are rechecked before preparing the message. An already transmitted message cannot be recalled. There remains a small read-to-send race; no claim of immediate external revocation is made. Provider POSTs are not automatically retried and there is no Telegram/global-chat fallback. Unknown outcomes and abandoned processing claims require investigation rather than blind resending.

Default runner: `python -m avenra.notification_runner` is dry run, without opening a database or sending anything. Real processing requires APP_ENV=development or production, AVENRA_SMS_ENABLED=1, explicit existing DATABASE_PATH and Twilio credentials in the environment. `python -m avenra.notification_runner --send --max-jobs 1` processes at most one job. `--watch` runs continuously. Stop it with Ctrl+C. Never enable sending with fictional recipients.

`python -m avenra.runtime` supervises Gunicorn and, only when AVENRA_SMS_ENABLED=1, the worker on the same host and SQLite filesystem. It exits if either child exits unexpectedly. No separate Render service or paid resource is provisioned by this patch. Deployment costs and provider charges must be checked independently. SQLite web/worker processes must share one disk; do not horizontally scale this arrangement.

The runtime must be started with an explicit DATABASE_PATH. Production still uses the existing device-token evaluation shortcut and is not ready for real survivor deployment. Individual survivor authentication, approved staff onboarding/MFA, broader security assessment and operational safeguarding remain release gates.

Pressed time is device-reported and unverified. Missing/timezone-ambiguous device time is unknown. The server records receipt time independently. A delay badge does not prove the phone was offline.

PWA files and tests are owned by the teammate and are not changed by this batch. Existing integrated PWA failures must remain documented. Run all backend tests, dashboard browser checks, and Stage 0 startup checks before a checkpoint; repeat the phone/provider delivery checks with a consenting recipient before claiming real delivery.
