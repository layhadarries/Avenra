# Web Push notifications

This is an opt-in alternative to SMS, with no automatic SMS fallback. A phone number alone cannot receive Web Push. The recipient must accept a one-use invitation and grant browser notification permission. Hosting, data, device availability and browser push services still have costs/limitations; no emergency delivery guarantee is made.

## Implementation

- Explicit `AVENRA_WEBPUSH_ENABLED=1`; disabled otherwise.
- Survivor/device authority can invite only their own saved contacts. Up to five invitations per contact per hour. Links expire in 24 hours, are hashed in the DB, and become unusable after acceptance or replacement.
- Share the fragment link manually with an independently checked contact. Possession of this link proves access to the link, not ownership of a phone number or a verified legal identity. No names, case IDs or location are disclosed on the contact page.
- Contact POSTs use session-bound CSRF tokens. HTTPS also requires an exact same-origin Origin header. Referrer suppression remains enabled without disabling the other staff forms' HTTPS checks.
- Browser management cookie is HttpOnly and SameSite=Strict; HTTPS uses a Secure `__Host-` cookie. Subscriptions are Fernet-encrypted using a separate key outside the repository. Subscription endpoints and keys never appear in public API results or audit details.
- Only HTTPS FCM, Mozilla and Apple endpoints with valid P-256/auth keys are allowed. No arbitrary URLs, credentials, custom ports or redirects; provider calls have a timeout, no automatic retry and bounded responses.
- Push notifications contain only a neutral title/message and a narrowly scoped acknowledgement link. No GPS, case code, survivor name or incident details go onto the lock screen.
- Existing atomic outbox, idempotency and five-alert-batches/hour limit are reused. Accepting an invitation cancels old pending jobs for that contact, rather than sending historical alerts. New alerts in push mode queue only for opted-in contacts. SMS and Push workers claim only their own channels.
- Provider acceptance remains `accepted`, not `delivered` or `acknowledged`. Explicit acknowledgement is recorded separately and counted on authorised dashboards. It never acknowledges the staff alert or grants access to case data.
- A recipient can revoke this browser's subscriptions. Removed contacts cascade their invites/subscriptions. 404/410 provider responses deactivate expired subscriptions. Revocation cannot recall a push already handed to the provider.
- Timed-out sends and stale claims become unknown; do not blindly resend them. Push TTL is five minutes; acknowledgement links expire after a day.

## Local verification

1. Install `requirements.txt`; run `test_webpush.py`, the complete test suite, and `tests/webpush_browser.py`. That browser test uses a fake push subscription and sends no external notification.
2. Generate private files outside Git: `python tools/webpush_keys.py ~/.config/avenra-webpush-local` (refuses existing keys). Keep the private directory backed up; key loss prevents decryption and may require re-enrollment.
3. Export `AVENRA_WEBPUSH_ENABLED=1`, `WEBPUSH_KEY_DIR` to that absolute directory, and `WEBPUSH_SUBJECT=mailto:YOUR_REAL_CONTACT_EMAIL`.
4. For the controlled phone-only test, keep `APP_ENV=evaluation`, `AVENRA_SMS_ENABLED=0`, a separate temporary evaluation DB, and explicitly set `AVENRA_PUSH_SELF_TEST=1`. This permits an opted-in browser to request one neutral test/minute; it does not permit evaluation alert jobs to dispatch.
5. Start Flask on localhost:5050, connect Android via USB and `adb reverse tcp:5050 tcp:5050`. In `/survivor/setup.html`, use your own test contact's “Invite for notifications” button. Open the complete localhost fragment link on the phone, accept, then tap “Send one test notification”. Confirm the notification physically appears. Do not share your invitation token, keys or subscription with support chats.
6. Provider acceptance alone is not a pass. Record the actual device/browser, arrival and behaviour while backgrounded. Disable `AVENRA_PUSH_SELF_TEST` when done.

## Normal dispatch

Use `python -m avenra.runtime` on the same host/disk as SQLite. With Web Push enabled, runtime starts the push worker outside evaluation mode. `python -m avenra.webpush_runner` alone is a dry run; `--send --max-jobs 1` explicitly processes one job. Stop legacy SMS workers and keep SMS disabled if no SMS is intended.

Fictional evaluation databases remain blocked from automatic external alert dispatch even if APP_ENV is changed. A manually triggered neutral self-test is the only exception and has separate explicit enablement, an opted-in browser cookie and CSRF protection. Do not delete the evaluation marker to bypass this guard.

## Release gates

Do not use this checkpoint with real survivor data. Individual survivor credentials still replace the shared evaluation device token in a later authentication change. Production requires verified HTTPS/trusted-proxy configuration, secure secret storage/backups, abuse monitoring, revocation/recovery procedures, accessibility/device checks and appropriate partner operations. Browser push availability, network connectivity and OS restrictions can prevent delivery. The contact subscription is encrypted at rest, but that does not encrypt the entire existing case database or the survivor's pending IndexedDB queue.
