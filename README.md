# Avenra

Avenra — “a new avenue” — connects people experiencing unsafe situations
with trusted contacts and authorised support staff.

The project combines a discreet survivor PWA, presented as **Clear Sky**,
with a role-based **Avenra staff dashboard**.

Developed for the FNB hackathon. This is an actively developed prototype,
not a guaranteed emergency-response service.

## Current status

The staff dashboard is hosted on Vercel:
https://avenra-delta.vercel.app/login

Hosted staff invitations, password creation, normal login and global
sign-out are working. The hosted database uses PostgreSQL through Supabase.

Individual PWA device pairing and server-side queue ownership checks are
implemented. Complete hosted PWA integration is still in progress.
The current public app URL must not be treated as a completed release.

## Features

### Survivor PWA — Clear Sky

- Discreet weather-style shell and Quick Exit.
- Persistent offline alert queue with retry and receipt checking.
- Trusted-contact management and opt-in Web Push invitations.
- Location-sharing and other consent controls.
- Private diary notes and JPEG photographs, with integrity hashes.
- Offline diary capture and verified upload receipts.
- Access history showing supported staff viewing events.
- Browser installation manifest, service worker and installation page.

### Staff dashboard

- Email invitations with single-use password-setup links.
- Role-based access for administrators, responders and shelter staff.
- Explicit case assignments; administrator status alone grants no case access.
- Alert triage, acknowledgement and consent-aware location display.
- Nearby service searches within 25 or 50 kilometres.
- Referral requests, acceptance, decline reasons and placement recording.
- Shared diary access subject to assignment and consent.
- Filtered audit history and access-denial recording.

Service listings do not promise available beds or confirmed placement.
Availability must be confirmed directly with the service.

## Hosting and installation

- Staff dashboard: `/login`
- Survivor app: `/survivor/`
- Installation instructions: `/survivor/install.html`
- Authorised staff pairing controls: `/devices`

Private pairing links expire after ten minutes and work once.
The public QR opens the app; it does not grant account access.

QR assets:
- `static/survivor/clear-sky-app-qr.png`
- `static/survivor/clear-sky-app-qr.svg`

Installing the PWA does not guarantee background execution while closed.
Offline capture and online delivery are different states.

Vercel does not automatically run the project's persistent notification
workers. Hosted notification dispatch needs a separately configured runner.

## Local development — Fish

Use Python, Node.js and a virtual environment.

```fish
cd ~/Desktop/Avenra
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install -r requirements.txt

# Keep this local session separate from hosted configuration.
set -e DATABASE_URL PUBLIC_BASE_URL VERCEL VERCEL_ENV
set -gx APP_ENV development
set -gx COOKIE_SECURE 0
set -gx DATABASE_PATH "$PWD/avenra-local.sqlite3"
set -gx UPLOADS_DIR "$PWD/local-uploads"
set -gx SECRET_KEY (python -c 'import secrets; print(secrets.token_urlsafe(48))')

python -m flask --app app run --port 5050
```

Normal startup creates the local schema without seeding demonstration
accounts. Keep the same secret and paths when restarting.

The application does not automatically load `.env` files.
Never commit database files, uploads, secrets or private backups.

Staff provisioning and email configuration are documented in
[Staff invitations](docs/staff-email-invitations.md).

## Verification

Work test-first: reproduce the missing behaviour, implement it, then run
the relevant regression checks.

```fish
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/service-worker-contract.cjs
```

Browser checks require the development dependencies and Chromium:

```fish
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python tests/hosted_pwa_pairing_browser.py
```

Tests use fictional data. Passing local SQLite tests does not establish
that the hosted PostgreSQL deployment has passed integration testing.

## Remaining release work

- Bind queued alerts and diary entries to their original accounts.
- Block mismatched or unbound legacy records without deleting them.
- Complete hosted PWA identity and recovery flows.
- Configure durable, private hosted diary storage.
- Restore PostgreSQL certificate verification with the correct CA.
- Verify hosted notification dispatch independently of a developer laptop.
- Complete installed-phone testing over Wi-Fi, mobile data and reconnects.
- Validate backup restoration, access controls and operational limits.

Current Vercel diary writes remain blocked until durable private storage
is configured. Use fictional incident data while release gates remain open.

## Architecture

- `avenra/controllers/` — HTTP routes and request handling.
- `avenra/services/` — application behaviour and transaction boundaries.
- `avenra/repositories/` — parameterised database access.
- `avenra/models/` — domain models.
- `static/survivor/` — Clear Sky PWA.
- `templates/` and `static/js/` — staff interface.
- `sql/` — hosted database migrations.
- `tests/` — API, regression, browser and service-worker checks.
- `tools/` — provisioning, deployment and verification utilities.

## Further documentation

- [Governance](docs/GOVERNANCE.md)
- [Security requirements](docs/SECURITY_REQUIREMENTS.md)
- [Hosted dashboard](docs/vercel-dashboard.md)
- [Device pairing checkpoint](docs/hosted-pwa-pairing-checkpoint.md)
- [Web Push](docs/web-push.md)
- [Deployment runbook](docs/stage-6-deployment-runbook.md)
- [Data lifecycle and pilot gate](docs/stage-6-data-lifecycle-and-pilot-gate.md)