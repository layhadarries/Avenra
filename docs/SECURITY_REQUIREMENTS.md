# Agreed security requirements

Status: design requirements unless explicitly verified in STAGE0_STATUS.md.
Use test-driven development: reproduce the expected failure first, implement the
policy in services/repositories, then run targeted and full regression checks.
Use OWASP Top 10 and ASVS as review frameworks, not a certification claim.

## Staff and platform owners

- All onboarding and account management should take place on the website.
- Initial owner setup requires a controlled, expiring, single-use bootstrap
  capability provisioned by the deployment owner. Public first-signup-wins is
  forbidden. Disabling/deleting an owner must never reopen bootstrap.
- Administrative staff request a person with verified contact details,
  organisation, role, scope and reason. An independently authorised platform
  approver accepts/rejects; nobody approves their own request.
- Invitations bind recipient, organisation, role and scope server-side; expire,
  are single use, and are delivered directly to the recipient. Resending/revoking
  invalidates the old invitation. Requesters see status, never invitation secrets.
- Recipients set their own password. Privileges are preset server-side and cannot
  be chosen or elevated through a public form.
- Staff sign-in uses a password plus an email or SMS code; no external
  authenticator application is required. Email is the preferred initial channel;
  SMS delivery may cost money and is vulnerable to number takeover. Email
  two-step verification is not a claim of phishing-resistant MFA.
- Codes expire promptly (target five minutes), are single use, attempt-limited
  and resend-limited, and never appear in logs. Protect account recovery and
  destination changes; require fresh verification for privileged changes.
- Platform approval authority does not imply access to survivor records.

## Survivors

- Survivors register themselves. Public registration can create only survivor
  accounts and must never accept a client-supplied staff role or case grant.
- Offer an app PIN with strict attempt limits and safe recovery. A short PIN
  must not be the sole remote credential or the sole encryption key.
- Offer device-supported WebAuthn/passkeys when available, using the device's
  own biometric or PIN verification. Do not collect facial/fingerprint templates.
  Browser/device support must be checked, including the target Note 9.
- Keep information private by default. Sending an alert grants only defined,
  time-limited information to assigned responders. Location requires explicit
  consent; diary/evidence sharing requires separate, selective permission.
- Check authorization on every request. Closing/revoking access blocks future
  reads and removes stale client displays; it cannot erase information already
  seen, copied or photographed.
- No automatic developer/admin access. If even operators must be unable to read
  stored private material, use an explicitly designed end-to-end encryption and
  selective-disclosure/key-recovery model, not login controls alone.

## Application boundaries

Use secure transport/cookies, server-side scoped permissions, CSRF protection for
staff writes, safe output encoding, parameterised queries, strict input and upload
validation, minimal logs, private storage, backups and tested restoration. Keep
private API responses out of service-worker/browser persistence. Protect against
authentication abuse, permission escalation and cross-organisation access with
negative tests. Operational response coverage must be stated honestly.

These requirements are not all implemented. Never use passing legacy tests or a
Stage 0 tag as evidence that real-data release blockers have been resolved.
