# Staff email invitations

The operator provisions accounts using Flask CLI. Admin, responder and shelter accounts all use the same email -> password setup -> dashboard flow. No temporary password, public registration or evaluation login is needed. This does not add a delegated administration UI or allow admins to grant permissions through a public API.

## Configuration

Run commands against the same DATABASE_PATH and application environment as the hosted dashboard. Set these in the host's private environment settings, not in Git:

- PUBLIC_BASE_URL: the stable public HTTPS origin, e.g. https://staff.example.org (no path/query/fragment).
- SMTP_HOST, SMTP_PORT (usually 587 with STARTTLS, or 465 with implicit TLS).
- SMTP_TLS_MODE: starttls (default), or ssl.
- SMTP_USERNAME, SMTP_PASSWORD: the provider's SMTP credentials or app password.
- SMTP_FROM: an authorised sender address.
- SECRET_KEY: the existing persistent application secret. Do not regenerate it for each CLI invocation.
- APP_ENV=production and COOKIE_SECURE=1 on the hosted deployment. Keep evaluation routes disabled.

Use a sender/domain authorised by the provider. Configure its SPF/DKIM requirements and check spam folders. SMTP acceptance is not proof of inbox delivery. Do not post SMTP passwords or invitation links in chat, logs, screenshots or issue trackers.

## Invite staff (Fish)

```fish
cd ~/Desktop/Avenra
source .venv/bin/activate.fish

# Admin account: no private case access unless explicitly granted.
python -m flask --app app staff-invite \
    --email admin@example.org --name 'Admin name' --role admin --org 'Organisation name'

# Case staff: repeat --case-code to assign additional existing cases.
python -m flask --app app staff-invite \
    --email colleague@example.org --name 'Colleague name' --role responder \
    --org 'Organisation name' --case-code SP-1042

# Shelter staff: use the real shelter ID from your database.
python -m flask --app app staff-invite \
    --email shelter@example.org --name 'Shelter colleague' --role shelter \
    --org 'Organisation name' --shelter-id 1
```

All addresses and identifiers above are examples. Omit case grants when the person should have none. The recipient cannot select their own role or assignments.

Resend using the identical account details. Resending invalidates previous pending links. Active/configured accounts cannot be overwritten through this command. Delivery failure revokes the new link; correct SMTP settings and resend. Do not retry automatically in a loop.

## Recipient flow

A plain-text welcome email contains a clickable HTTPS URL. Its secret is in the URL fragment, keeping it out of HTTP request URLs. The page removes the fragment from the current history entry, asks for password and confirmation, then consumes the invitation and enables the account transactionally. It signs the person in to their authorised staff landing page. GET requests and email scanners do not consume invitations.

Links expire after 24 hours and can be used once. Passwords need 15–128 characters and a sufficiently strong zxcvbn score. Each invitation stores only a SHA-256 token digest, account version and expiry. The password is stored as a Werkzeug password hash. Existing role, case grants and shelter scope remain server-controlled.

## Disable access

```fish
python -m flask --app app staff-disable --email colleague@example.org
```

This disables sign-in, increments the account version to invalidate sessions, revokes pending invitations, and records an audit event. It preserves records and grants for review; it does not delete the account.

## Verification

```fish
python -m unittest discover -s tests -p test_staff_invitations.py -v
python tests/staff_invitation_browser.py
```

Tests use temporary synthetic accounts and mocked email delivery. They do not send email. Before inviting real staff, verify one actual email delivery against the hosted HTTPS URL, including normal sign-in after sign-out, expiry/resend, and intended access. No actual email provider or hosted origin has been configured by this patch.

Authenticator MFA enrollment, password recovery and delegated organisation administration are separate follow-up work. This onboarding flow alone is not approval for real survivor data. Invitations grant the configured role, but an admin role alone never grants access to every case.
