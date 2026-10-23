# Stage 0 checkpoint — 23 October 2026

This is a development checkpoint for fictional evaluation, not approval to launch
with real survivor information or operate an emergency response service.

## Implemented and checked

- Structured `avenra/` package with controllers, services, repositories and models;
  `gunicorn app:app` remains the deployment entrypoint.
- Schema initialization, optional isolated evaluation seeds, startup secret/cookie
  guards, and preservation of account state across restarts.
- Staff email/password form with generic failures, CSRF tokens, validated identity
  display, role-aware navigation, fixed session expiry and POST sign-out.
- Initial staff pages render; shelter and referral tables use repository data.
  Alert triage, case evidence display and audit browsing remain explicit placeholders.
- Neutral Clear Sky PWA shell, consistent manifest/icons, responsive styles and
  offline shell caching. No credentials or private records are embedded in it.
- Service worker only caches allowlisted public shell resources; API requests,
  authenticated requests, writes, query strings and other origins bypass it.
- Browser session boundary clears displayed content on logout, expiry and case
  permission-revalidation failure. Server authorization remains essential.

## Verification

Run the commands in README.md. This checkpoint passed 37 Python tests, 4 Node
service-worker tests, the local Gunicorn startup/restart smoke check and Chromium
browser checks for login, staff navigation/sign-out and mobile offline opening.
Python verification used 3.12. Browser checks use a mobile viewport, not physical
Android hardware. Existing API regression tests do not prove every sensitive
access path is safe. No CI workflow is configured yet.

## Outstanding shared Stage 0 checks

- Render: neither a public deployment URL nor persistent storage/restore has been
  verified. Record the actual deployment URL and verification date here.
- Android: verify installation, standalone launch and offline reopening on the
  Samsung Galaxy Note 9 (Android 10, One UI 2.5), plus supported browser versions.
  Do not claim support for every Android version.
- SMS: no live provider call was made. Twilio is a provisional test channel only;
  app alert delivery is not connected to that CLI. Record a consenting-recipient
  delivery result here without phone numbers, tokens or message identifiers.
- Maskable icons, device-specific install presentation and browser accessibility
  need physical-device verification.

## Release blockers for real information

1. Replace shared backend demonstration credentials with individual survivor
   registration/enrolment, revocation and safe recovery.
2. Complete controlled web owner setup, independent staff invitation approvals,
   email/SMS verification, recovery and authentication abuse controls.
3. Enforce case/organisation/consent scope in every API, including consent reads;
   platform administrators must not grant themselves survivor access.
4. Validate and safely process evidence beyond file signatures; add meaningful
   corrupt-image and upload-limit tests. Complete private storage and encryption
   design, retention, deletion, restore and key recovery.
5. Implement alert-scoped, time-limited disclosures and revocation consistently.
   If operator-unreadable data is required, design end-to-end encryption explicitly.
6. Review response headers/CSP, logging and audit access/retention; do not describe
   the existing audit database as immutable or claim a CSP already exists.
7. Independent security and survivor-safety review, dependency checks and
   operational response agreements before a live pilot.

See SECURITY_REQUIREMENTS.md for the agreed access model. These blockers are
tracked requirements, not completed protections.
