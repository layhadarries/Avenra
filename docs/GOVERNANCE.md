# Avenra prototype privacy and accountability

This document describes the development prototype. It is not a claim of legal compliance, independent security certification or production readiness.

## Access and consent

Staff access requires an authorised role and, for private case data, a case assignment. Diary disclosure also requires active diary consent and entry-level sharing.

Location withdrawal redacts coordinates, accuracy and capture time from subsequent covered staff responses. Referral consent controls access to referral information and referral operations.

Withdrawal controls future disclosure through the application. It cannot recall information already delivered, downloaded, photographed or copied by a recipient. Existing browser content may remain until the next refresh or access revalidation.

Regranting consent can make retained information visible again. Withdrawal is not a deletion request.

## Notifications

Web Push uses neutral notifications without incident coordinates or diary content.

SMS can include alert location when location_sharing is active. The prototype currently uses this same consent for staff location disclosure and SMS location disclosure; independent recipient-specific location consent is not implemented.

Provider acceptance is distinct from delivery and human acknowledgement. Notifications do not guarantee emergency response or shelter placement.

## Audit history

Survivors receive only safe viewing events for their own case, including case, diary and photo views. Raw audit details are excluded.

Staff audit results are scoped to permitted case events and permitted own-account events. Forbidden authenticated audit-route access is recorded minimally and repeated matching attempts are coalesced.

Denied-access recording currently covers the audit page and audit API. It is not comprehensive intrusion detection.

Audit records are held in the application database. They are not externally anchored or tamper-proof against a database administrator.

## Development and release limits

The evaluation device credential is not individual survivor enrolment. Individual credentials, recovery and approved staff invitation and MFA flows remain release gates.

Public shell caching must exclude private APIs and staff pages. Local PWA storage protection requires separate review.

Before real-data deployment, establish retention and deletion rules, approved service recipients, HTTPS configuration, backup and recovery verification, provider assessment and an incident-response process.

Consent catalogue wording describes current intended recipient categories. It does not verify a real responder organisation or shelter partnership. Historical records may retain earlier evaluation labels; do not silently rewrite historical audit events.

Backend regression results and PWA integration sign-off must both be recorded before a shared release is marked complete.
