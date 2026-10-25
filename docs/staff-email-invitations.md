# Staff email invitations

The operator provisions accounts using Flask CLI. Admin, responder and shelter accounts all use the same email -> password setup -> authenticator enrollment -> workspace flow. No temporary password, public registration or evaluation login is needed. This does not add a delegated organisation-administration UI. These Stage 8 changes are locally verified only until an explicitly approved hosted migration/key rollout occurs; no deployment is part of this work.

## Configuration

Run commands against the same DATABASE_PATH and application environment as the hosted dashboard. Set these in the host's private environment settings, not in Git:

- PUBLIC_BASE_URL: the stable public HTTPS origin, e.g. https://staff.example.org (no path/query/fragment).
- SMTP_HOST, SMTP_PORT (usually 587 with STARTTLS, or 465 with implicit TLS).
- SMTP_TLS_MODE: starttls (default), or ssl.
- SMTP_USERNAME, SMTP_PASSWORD: the provider's SMTP credentials or app password.
- SMTP_FROM: an authorised sender address.
- SECRET_KEY: the existing persistent application secret. Do not regenerate it for each CLI invocation.
- STAFF_MFA_ENCRYPTION_KEY: a separately generated Fernet key, held outside database backups and distinct from SECRET_KEY. Hosted/production startup fails closed without a valid key. Do not paste keys into commands, logs or Git. Use your approved secret manager to generate and provision it after release approval.
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

A plain-text welcome email contains a clickable HTTPS URL. Its secret is in the URL fragment, keeping it out of HTTP request URLs. The page removes the fragment from the current history entry, asks for password and confirmation, then consumes the invitation and enables the account transactionally. It creates only a five-minute, password-bound MFA challenge, not a staff session. Staff must confirm authenticator setup before accessing their workspace. GET requests and email scanners do not consume invitations.

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

## Mandatory staff MFA and recovery (Stage 8)

All staff roles use RFC 6238 TOTP through pinned PyOTP. Enrollment is available only
after password/invitation verification, with session-bound CSRF and exact HTTPS
Origin checks. Manually enter the displayed secret in an authenticator; there is
no third-party QR service or secret-bearing HTTP URL. Secrets never enter session
cookies or browser storage. The page is private/no-store. MFA challenges expire
after five minutes, are bound to account version, and are consumed once. Existing
password-only sessions are rejected; plan a controlled staff enrollment rollout.

Codes have six digits and 30-second steps with one step of clock skew allowed.
The highest accepted counter is persisted, preventing replay including concurrent
requests. Servers need a reliable clock. Enrollment produces ten 128-bit recovery
codes, displayed once and stored only as SHA-256 digests. Each is consumed atomically
and still requires a password challenge. A lost enrollment response may lose those
codes; do not replay a consumed challenge. Use the authenticator, or an authorized
operator reset if neither factor remains. There is no public/email-only MFA reset.

Store the authenticator and recovery codes separately from the staff browser.
TOTP is not phishing-resistant WebAuthn; compromised browser/server code, copied
secrets, unlocked devices and a malicious authorized operator remain threats.
Encryption protects a DB-only copy of TOTP secrets, not a running-server compromise.
The development-only key derivation is not operational key custody. Backup and key
custodians, rotation/re-encryption and independent security review remain pre-pilot
responsibilities; do not delete a key while retained encrypted secrets depend on it.

Password attempts are bounded per keyed identity (10/15 minutes) and address
(60/15 minutes); MFA attempts are bounded per account (8/15 minutes) and address.
Activation is limited to 20/address/15 minutes. Counters persist across requests,
expire and have a 10,000-row cap with saturation; the cap fails closed for new
buckets. Pairing counters are also capped and saturated. Public errors do not
identify whether an email exists; rejected email addresses are no longer logged.
These are application abuse controls, not upstream volumetric DoS protection;
shared addresses and targeted account lockout can still cause temporary denial.

### Operator-only MFA reset

Before any real pilot, name the recovery operators and independent identity
verification/approval process. Verify the staff member out of band through the
organisation's established channel; do not accept a case code, a forwarded email,
an invitation secret or an unauthenticated support message as identity proof.
Record approval in an access-controlled ticket without copying secrets or private
case data. The CLI flag below records an operator assertion of that external
process; it does **not** technically prove independent verification happened.

```fish
python -m flask --app app staff-mfa-reset --email colleague@example.org \
    --verification-reference APPROVED-TICKET-ID --confirm
```

This deletes MFA credentials/recovery codes, revokes pending MFA challenges,
increments account version to invalidate sessions and audits the non-sensitive
ticket reference. It preserves the password, case records and assignments.
The next sign-in requires password plus new enrollment. Do not use invitations to
overwrite an active account. Account suspension/global logout/device revocation
retain their existing separate controls. No MFA/PIN prompt was added to a paired,
explicitly enabled emergency gesture or its offline queue.

### Additive rollout and rollback boundary

No live DDL/key change is authorized by this document. After separate approval,
apply `sql/004_staff_mfa.sql` to the intended isolated/hosted target, provision the
separate key, then release the matching application. Hosted startup now requires
schema version 7; it never applies DDL automatically. SQLite migration adds the
new tables/version without altering existing evidence or inventing timestamps.
Do not deploy code expecting version 7 against a version-6 database. Preserve
the key separately when backing up; restoring encrypted rows without it is not
a successful identity restore. Rollback must retain the additive tables and key;
returning to a password-only older build would remove the MFA boundary and needs
explicit security approval, not an automatic operational workaround.

Verification adds `test_stage8_mfa.py`; the invitation/browser fixtures complete
actual TOTP or recovery-code verification rather than forging staff sessions.
Invitation expiry/resend/concurrency, assignment/role boundaries, suspension,
global logout, paired-device revocation and emergency/offline browser regressions
remain required. No real invitation or provider notification is sent by these tests.
This onboarding flow alone is not approval for real survivor data. Delegated
organisation administration and self-service password recovery remain outside
this release; absence of a recovery shortcut is intentional.
