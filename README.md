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

The experimental weather four-tap alert saves without waiting for GPS. Optional
one-shot emergency GPS requires a separate setup opt-in and active sharing consent;
it never uses a selected weather place. Late fixes are best-effort authenticated
updates, not new alerts or repeat notifications. See
[release boundaries](docs/stage-6-release.md#weather-tap-location-follow-up-local-verification-no-deployment)
for limits and local test evidence; this follow-up has not been deployed.

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

The dashboard is deployed on Vercel and uses Supabase PostgreSQL with verified TLS. Hosted diary photos are kept in private database storage; delivery uses a bounded worker endpoint invoked by Supabase Cron and Vault-managed credentials. The original hosted worker processes opted-in Web Push jobs. This source update adds separately enabled, permission-gated Twilio SMS; configure and verify it before claiming hosted SMS works. Neither channel falls back to the other. The hosted scheduler heartbeat and phone acceptance checks have been confirmed for the demo.

## Technology stack

| Area | Technologies |
| --- | --- |
| Backend | Python, Flask, Flask-WTF, Gunicorn |
| Staff UI and PWA | HTML, CSS, vanilla JavaScript, Service Worker, IndexedDB, Web App Manifest |
| Local development database | SQLite |
| Hosted database | Supabase PostgreSQL, psycopg 3, additive SQL migrations, verified TLS |
| Hosting | Vercel Python runtime and CDN |
| Invitations and password recovery | Python `smtplib`, SMTP with STARTTLS or implicit TLS |
| Optional emergency SMS | Twilio Programmable Messaging, explicit trusted-contact permission and durable outbox |
| Web Push | VAPID, `pywebpush`, encrypted subscriptions, Supabase Cron/`pg_net` and Vault |
| Image handling | Pillow JPEG validation, SHA-256 integrity hashes |
| Tests | Python `unittest`, Playwright browser tests, Node.js service-worker contract tests |

## Developer setup

Local Stage 8 code now requires staff TOTP verification after password sign-in or
invitation activation. Hosted rollout is **not performed**: it first requires the
additive MFA migration and a separately provisioned encryption key. See
[staff identity and recovery operations](docs/staff-email-invitations.md#mandatory-staff-mfa-and-recovery-stage-8).

Requirements: Python, Node.js for service-worker checks, and Fish shell for the commands below. Install the app dependencies and start the local server:

```fish
cd ~/Desktop/Avenra
make set-up
source .venv/bin/activate.fish
python tools/prepare_dashboard.py
source ~/.local/share/avenra-dashboard/runtime.fish
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
- [Stage 7 threat model and route/repository audit](docs/SECURITY_REQUIREMENTS.md#stage-7-practical-threat-model-and-routerepository-audit)
- [Governance](docs/GOVERNANCE.md)
- [Vercel dashboard deployment](docs/vercel-dashboard.md)
- [PWA pairing checkpoint](docs/hosted-pwa-pairing-checkpoint.md)
- [Web Push configuration](docs/web-push.md)
- [Stage 6 deployment runbook](docs/stage-6-deployment-runbook.md)
- [Stage 6 data lifecycle and pilot gate](docs/stage-6-data-lifecycle-and-pilot-gate.md)
- [Staff email invitations](docs/staff-email-invitations.md)

## Developer account, email and SMS operations

### Configure your own sending email

The operator chooses the SMTP provider and authorised sender. No Gmail dependency
is required. Use a dedicated transactional mailbox; enable provider MFA and create
an app password or SMTP credential if that provider requires one. Do not use an
ordinary mailbox password where the provider requires an app password.

```fish
cd ~/Desktop/Avenra
source .venv/bin/activate.fish
# Only if you have not already created the private operator runtime:
# python tools/prepare_dashboard.py
python tools/configure_staff_mail.py
if test -f ~/.local/share/avenra-hosted/runtime.fish
    source ~/.local/share/avenra-hosted/runtime.fish
else
    source ~/.local/share/avenra-dashboard/runtime.fish
end
make staff-setup
```

For hosted accounts, use the hosted runtime connected to the hosted database.
A local SQLite account will not appear on Vercel. Never mix a local account database
with invitation links pointing to the hosted application.

The mail wizard asks for the public HTTPS origin, SMTP host, port, TLS mode,
username, authorised From address and hidden credential. Typically port 587 uses
STARTTLS; port 465 uses implicit TLS (`ssl`). Follow your provider's settings.
Credentials stay in a private mode-0600 operator file, outside Git. Configure SPF,
DKIM and DMARC for your sending domain where supported. SMTP acceptance is not
proof of inbox delivery. Invitation and recovery email include the Avenra logo.

`make staff-setup` prompts for admin/responder/shelter, email, name, organisation
and the role's access information. Assigned case codes are existing survivor case
identifiers, not passwords. Shelter users need an existing shelter ID. No user
can choose their own role or case permissions through an invitation. The invitee
opens the emailed link, chooses a password and completes authenticator MFA.
Keep recovery codes privately. Admin status does not bypass case assignment.

### Password reset and MFA recovery

Use **Forgot your password?** on the sign-in page. Eligible active staff receive a
15-minute single-use reset link. Resetting preserves authenticator enrollment,
roles and assignments, revokes existing sessions and requires normal password +
MFA login. Login/reset responses do not disclose registered accounts. Resending
invalidates previous links. Disabled and unactivated accounts cannot use reset
links to activate themselves. No reset secret is stored in browser local storage.

A lost authenticator uses saved recovery codes or the existing operator-only
`staff-mfa-reset` command after independently verifying identity. Email possession
alone does not remove MFA. Never put reset/invitation URLs in screenshots or logs.

### Twilio emergency SMS setup

1. Create a Twilio account and follow its SMS onboarding at
   <https://www.twilio.com/docs/usage/trials/try-out-sms>. Obtain the Account SID,
   Auth Token and an SMS-capable Twilio sender number. Trial restrictions vary;
   verify the intended recipients and check account-specific restrictions before
   testing. Upgrade only if you choose to pay for the needed capability.
2. Allow **South Africa only** under Messaging Geographic Permissions for this
   deployment: <https://www.twilio.com/docs/messaging/guides/sms-geo-permissions>.
   Review sender registration requirements and set billing/usage alerts. This
   adapter deliberately accepts only South African `+27` recipient numbers.
3. Run the private wizard. It validates formats, asks before enabling billable
   SMS, and does not send anything:

```fish
python tools/configure_sms.py
if test -f ~/.local/share/avenra-hosted/runtime.fish
    source ~/.local/share/avenra-hosted/runtime.fish
else
    source ~/.local/share/avenra-dashboard/runtime.fish
end
python tools/sms_test.py  # dry run: no network and no message
```

4. In the PWA's trusted-contact setup, explicitly enable emergency SMS only after
   the contact agrees. Existing contacts default to **disabled**. The checkbox/
   button is the survivor's attestation of permission, not independent recipient
   verification. Respect recipient opt-outs and Twilio suppression rules. Remove
   or disable the contact immediately if permission is withdrawn.
5. An optional real test is billable. Use only a consenting recipient:

```fish
read --prompt-str 'Consenting test recipient (+27...): ' TEST_RECIPIENT_PHONE
set -gx TEST_RECIPIENT_PHONE "$TEST_RECIPIENT_PHONE"
python tools/sms_test.py --send
set -e TEST_RECIPIENT_PHONE
# To check the returned message ID without sending another SMS:
# python tools/sms_test.py --status SM...your-returned-message-id...
```

The worker independently processes at most one Web Push and one SMS job per tick;
each channel must be enabled explicitly. A contact has one active channel in the
existing model: a Web Push contact is not also sent SMS for the same alert. SMS is never an automatic fallback for
Web Push. Current SMS opt-in and location-sharing consent are rechecked before
sending. No diary text/photos are sent. Provider acceptance is not delivery or
reading. Uncertain sends are not automatically retried, avoiding duplicate alerts.
The existing per-survivor notification budget still applies. Do not reset old jobs
to pending to test the integration: that can resend historic alerts.

### Hosted upgrade (preserve existing keys and records)

Back up first using the existing hosted runbook. Apply the additive
`sql/010_contact_sms_opt_in.sql` to the **private avenra schema** after migrations
1–9, before deploying this source. It adds an opt-in flag without opting anyone in.
Do not reset the database. Hosted startup requires the new column. The major schema version remains 9;
a capability marker records this additive upgrade, preserving the previous source's
version check for rollback. Leave the new column and marker in place on rollback.
Provision the existing mandatory staff MFA/queue-encryption keys using the existing
Stage 8/9 runbooks if not already configured; do not replace working keys.

The private local runtime is not automatically uploaded to Vercel. Set these
Production environment variables through Vercel's environment editor or CLI:
`PUBLIC_BASE_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS_MODE`, `SMTP_USERNAME`,
`SMTP_FROM`, `SMTP_PASSWORD`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM_NUMBER`, and `AVENRA_SMS_ENABLED=1`. Treat passwords and tokens as
secrets. Keep `AVENRA_WEBPUSH_ENABLED` as already configured. Preserve
`SECRET_KEY`, MFA/queue/push keys, database TLS and worker credentials. Redeploy
only after tests pass. The existing authenticated minute scheduler handles both
channels; do not create a second schedule. Confirm a fresh heartbeat and actual
recipient receipt with fictional data before a demonstration.

### Release limits

This patch is not independent penetration-test certification or real-survivor
operational approval. Provider setup, real email/SMS delivery, hosted migrations,
physical-phone behavior, safeguarding ownership and restore/rollback exercises
must be verified in their actual environments. Automated local tests cannot
supply those results. See the included verification report for checks actually run.

Run `make release-check` after installing `requirements-dev.txt` and
`requirements-security.txt` and Chromium. The runner strips provider credentials
from its subprocesses, runs all Python and Node tests, security gates and twelve
local browser journeys, and stops on a failed or unavailable check. It does not
deploy, apply hosted migrations, or prove actual provider delivery.
