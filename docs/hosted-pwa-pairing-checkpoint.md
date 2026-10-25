# Hosted PWA: individual pairing checkpoint

Baseline: main 1e05d06. This is the first implementation checkpoint, not the final hosted-PWA release.

## Included

- Staff with responder/admin authority can create a ten-minute private link from `/devices`. The eventual new case is explicitly assigned to the issuing staff member; no general case-access expansion.
- Opening a link does not consume it. The phone clears its fragment, then an explicit Connect action exchanges it for a 30-day opaque HttpOnly, SameSite=Strict cookie (Secure in the HTTPS configuration).
- Database stores SHA-256 digests of high-entropy invitation and device secrets. Pairing is transactional with its audit event. One concurrent attempt can consume a link; disabled issuers cannot enroll a device.
- Exact-origin checks for enrollment and cookie-authenticated API writes. Cookie failures never fall back to the demo header. Hosted and production configurations reject the shared demo header.
- Persistent rate limits: 20 pairing submissions per IP digest per ten minutes; 10 new invitations per staff member per ten minutes. Forwarded headers supplied by clients are not trusted. A shared proxy IP can make the limit more restrictive.
- Neutral install page, public QR assets, mobile layout, operator revocation, and a fix for schema-qualified PostgreSQL INSERT generated IDs.
- New accounts start with all optional consents inactive. Credentials are never included in API response bodies, SQL values interpolated into query strings, or public QR codes.

## Local verification

Use the existing venv. Run `python -m unittest discover -s tests -p 'test_*.py' -v`, `python tests/hosted_pwa_pairing_browser.py`, and `node tests/service-worker-contract.cjs`. New JS files must pass `node --check`. Fixtures isolate the database and do not send invitations or provider messages.

The test database is synthetic SQLite. PostgreSQL translation has regression coverage with a mocked connection. A real hosted PostgreSQL integration check remains necessary.

## Deployment gate: do not deploy this checkpoint by itself

1. Bind existing and new alert/diary queues to their originating identity. Preserve unbound legacy records but block sending them under newly paired credentials. Pairing must not silently reassign another person's pending data.
2. Remove or replace hardcoded demo headers throughout PWA clients and give missing/expired/revoked identity a clear recovery flow. This checkpoint intentionally rejects demo authority on hosted servers.
3. Wire durable private hosted diary storage; current Vercel diary writes stay blocked. No public bucket or public evidence URLs.
4. Restore verified PostgreSQL TLS with the correct CA; verify real hosted transactions and case isolation. Use fictional test incidents only.
5. Apply the additive `sql/002_device_enrollment.sql` to the private hosted schema as part of the coordinated deployment. It adds three RLS-protected tables and does not reset users, cases or app migration version 6. Do not apply it to a different schema or treat it as a database reset.
6. Complete live HTTPS, laptop-off, installed phone, Wi-Fi/mobile-data, offline/reconnect, expiry, revocation and notification-worker acceptance. Installing a PWA does not guarantee closed-app background execution.

## Operator revocation

In the correctly configured server environment: `python -m flask --app app device-revoke --case-code EXACT_CASE_CODE`.
This revokes all enrolled device credentials for that exact case and retains case records. This checkpoint does not implement re-pairing to an existing case, device recovery, automatic credential refresh, or deletion of pending local data. Do not issue a new-account invitation as a substitute for recovery.

## QR

`static/survivor/clear-sky-app-qr.png` and `.svg` encode only `https://avenra-delta.vercel.app/survivor/`. This stable public URL opens the app; it does not create an identity or guarantee installation readiness. Private enrollment links must not be published alongside the QR.
