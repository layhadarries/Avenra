<a id="readme-top"></a>

<div align="center">
  <img src="static/images/avenra-logo.png" alt="Avenra logo" width="240">
  <h1>Avenra</h1>
  <p><strong>A new avenue to support.</strong><br>
  A discreet safety and support prototype pairing the Clear Sky mobile app with an authorised staff dashboard.</p>
  <p>
    <a href="https://avenra-delta.vercel.app/survivor/">Open the app</a> ·
    <a href="https://avenra-delta.vercel.app/login">Open the dashboard</a> ·
    <a href="https://avenra-delta.vercel.app/survivor/install.html">Install guide</a>
  </p>
</div>

**A new avenue to support.** Avenra is a discreet, mobile-first safety and support prototype for people facing unsafe situations. It pairs **Clear Sky**, an installable survivor-facing Progressive Web App (PWA), with a role-based staff dashboard for authorised responders and support organisations.

Built for the FNB hackathon GBV track. The hosted demo is working, but Avenra is **not an emergency-response guarantee and is not approved for real survivor data or operational case management**. Use fictional names, contacts, incidents, notes and photographs in demos and testing.

<details>
  <summary>Table of contents</summary>
  <ol>
    <li><a href="#demo">Demo</a></li>
    <li><a href="#what-works-in-the-hosted-demo">What works</a></li>
    <li><a href="#technology-stack">Technology stack</a></li>
    <li><a href="#developer-setup">Developer setup</a></li>
    <li><a href="#verification">Verification</a></li>
    <li><a href="#roadmap-before-any-real-world-pilot">Future roadmap</a></li>
    <li><a href="#project-structure">Project structure</a></li>
    <li><a href="#further-reading">Further reading</a></li>
  </ol>
</details>

## Demo

- Dashboard: [avenra-delta.vercel.app/login](https://avenra-delta.vercel.app/login)
- Clear Sky PWA: [avenra-delta.vercel.app/survivor/](https://avenra-delta.vercel.app/survivor/)
- Install instructions: [avenra-delta.vercel.app/survivor/install.html](https://avenra-delta.vercel.app/survivor/install.html)
- Public app QR: [PNG](static/survivor/clear-sky-app-qr.png) · [SVG](static/survivor/clear-sky-app-qr.svg)

The QR opens the public app and does not enrol or authorise a device. Pairing requires a separate expiring, single-use invitation from authorised staff. Installation does not guarantee background execution while the app is closed. Offline capture and successful server delivery are distinct states.

## What works in the hosted demo

### Clear Sky PWA

- Discreet weather-style entry screen, PIN-protected app access and Quick Exit.
- Installable web app shell with service worker and public-only offline caching.
- Account-bound alert and diary queues, offline capture, retry and server-receipt checks.
- Trusted-contact management and opt-in Web Push notifications.
- Consent-aware location sharing and nearby support directory.
- Private diary notes and JPEG evidence photos with SHA-256 integrity receipts.
- Device pairing, recovery and explicit device disconnection.

### Staff dashboard

- Email invitations with one-use password setup, normal sign-in and global sign-out.
- Roles for administrators, responders and shelter staff.
- Explicit case assignments; an administrator role alone does not grant access to survivor cases.
- Alert triage, acknowledgement and consent-aware location display.
- Nearby support searches with 25 km and 50 km radius options.
- Referral request, acceptance, decline reason and placement-recording workflow.
- Shared diary access gated by assignment and current survivor consent.
- Filtered audit history and recorded access denials.

Service listings do not guarantee availability or placement. Staff and survivors must confirm details directly with each service.

### Hosted runtime

The dashboard is deployed on Vercel and uses Supabase PostgreSQL with verified TLS. Hosted diary photos are kept in private database storage; delivery uses a bounded worker endpoint invoked by Supabase Cron and Vault-managed credentials. The worker processes only opted-in Web Push jobs and does not fall back to SMS. The hosted scheduler heartbeat and phone acceptance checks have been confirmed for the demo.

## Technology stack

| Area | Technologies |
| --- | --- |
| Backend | Python, Flask, Flask-WTF, Gunicorn |
| Staff UI and PWA | HTML, CSS, vanilla JavaScript, Service Worker, IndexedDB, Web App Manifest |
| Local development database | SQLite |
| Hosted database | Supabase PostgreSQL, psycopg 3, additive SQL migrations, verified TLS |
| Hosting | Vercel Python runtime and CDN |
| Email invitations | Python `smtplib`, SMTP with STARTTLS or implicit TLS |
| Web Push | VAPID, `pywebpush`, encrypted subscriptions, Supabase Cron/`pg_net` and Vault |
| Image handling | Pillow JPEG validation, SHA-256 integrity hashes |
| Tests | Python `unittest`, Playwright browser tests, Node.js service-worker contract tests |

## Developer setup

Requirements: Python, Node.js for service-worker checks, and Fish shell for the commands below. Install the app dependencies and start the local server:

```fish
cd ~/Desktop/Avenra
make set-up
source .venv/bin/activate.fish
make run
```

The local app is at `http://127.0.0.1:5050`. It creates the schema without seeding demo accounts. Keep local database and upload paths separate from hosted production settings; do not copy production secrets into a development shell.

### Provision staff

Load the private operator runtime, then launch the guided account setup:

```fish
cd ~/Desktop/Avenra
source .venv/bin/activate.fish
source ~/.local/share/avenra-hosted/runtime.fish
make staff-setup
```

Choose admin, responder or shelter, enter the account details and confirm before the invitation is created and emailed. Responders can be assigned explicit case codes; shelter staff must be linked to an existing shelter ID. The email includes the Avenra logo embedded in the message and a plain-text fallback. SMTP acceptance does not prove inbox delivery. See [staff invitation operations](docs/staff-email-invitations.md).

Never put database URIs, SMTP credentials, VAPID private keys, invitation links or real survivor data in Git, logs, screenshots or chat.

## Verification

Run the Python suite and service-worker contract checks:

```fish
cd ~/Desktop/Avenra
source .venv/bin/activate.fish
make test
node tests/service-worker-contract.cjs
node tests/pwa-shell.cjs
```

Browser tests require the browser test dependencies and a Playwright Chromium installation:

```fish
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python tests/hosted_pwa_pairing_browser.py
```

Hosted integration and physical-device acceptance require the configured hosted environment. Local SQLite tests alone do not verify PostgreSQL, Vercel, email delivery, scheduler execution or phone behavior.

## Roadmap before any real-world pilot

The hosted demo is not the production-readiness finish line. Before using real survivor data, the team still needs to complete and document:

- Independent security review and a scoped penetration test, followed by remediation and retesting.
- A safeguarding and incident-response plan with named, trained people responsible for monitoring and follow-up.
- Privacy impact assessment, lawful basis and consent language review, retention/deletion policy, data-subject request process and breach-response workflow.
- Multi-factor authentication for staff, account recovery controls and least-privilege access review.
- Production-grade secrets/key lifecycle, access monitoring and audit-log retention review.
- Provider-level backups plus scheduled restore drills, disaster-recovery objectives and recovery ownership.
- Notification delivery, retry, rate-limit and escalation policies that clearly distinguish queued, provider-accepted, delivered and acknowledged states.
- Data migration/import procedures, operational service-directory verification and support ownership.
- Broader Android/browser/device accessibility testing and documented support limits.
- A controlled pilot plan with participant safety review, opt-in, consent withdrawal and a clear way to stop the pilot.

Do not represent app alerts as emergency-service dispatch, messages as read, provider acceptance as delivery, or referral acceptance as confirmed placement.

## Project structure

- `avenra/controllers/` — HTTP routes and CLI commands.
- `avenra/services/` — business rules, transaction boundaries and providers.
- `avenra/repositories/` — parameterised persistence operations.
- `avenra/models/` — domain objects.
- `templates/`, `static/js/`, `static/css/` — staff dashboard.
- `static/survivor/` — Clear Sky PWA, install materials and QR assets.
- `sql/` — additive hosted database migrations.
- `tests/` — unit, integration, browser and service-worker checks.
- `tools/` — deployment, setup, verification and operational utilities.
- `docs/` — security, governance, deployment and stage checkpoints.

## Further reading

- [Security requirements](docs/SECURITY_REQUIREMENTS.md)
- [Governance](docs/GOVERNANCE.md)
- [Vercel dashboard deployment](docs/vercel-dashboard.md)
- [PWA pairing checkpoint](docs/hosted-pwa-pairing-checkpoint.md)
- [Web Push configuration](docs/web-push.md)
- [Stage 6 deployment runbook](docs/stage-6-deployment-runbook.md)
- [Stage 6 data lifecycle and pilot gate](docs/stage-6-data-lifecycle-and-pilot-gate.md)
- [Staff email invitations](docs/staff-email-invitations.md)
