# Avenra object-authorization matrix (2026-10-27)

Scope: HTTP routes that read or change a survivor-owned object. The rule under
test is explicit: a grant for one case never authorizes another case. An
administrator may read every case by policy, but irreversible evidence and
retention work still requires an explicit assignment (`assigned()`), not the
administrator-wide read policy (`allows()`).

Evidence module: `tests/test_stage12_object_authorization.py`. Existing
regressions are listed where they already covered the same boundary.

## Staff routes

| Route | Actor | Object check | Action check | Evidence |
| --- | --- | --- | --- | --- |
| `GET /api/alerts` | responder, admin | `PortalRepository.alert_page`: admin sees all; staff need `case_access` | Read only | stage12, `test_stage7_boundaries`, `test_dashboard_access` |
| `POST /api/alerts/<id>/acknowledge` | responder, admin | `CaseAccessRepository.allows(staff, alert.user_id)` before any write | Status transition through the repository | stage12, `test_dashboard_access` |
| `POST /api/alerts/<id>/workflow` | responder, admin | `allows()` before workflow load; assignee must be a case candidate | Valid action, revision match, reason rules, referral/resolution rules | stage12, `test_alert_accidental_followup` |
| `GET /api/alerts/<id>/nearby-services` | responder, admin | `allows()`; same 404 for missing and inaccessible alerts | Active `location_sharing` consent and a usable fix | stage12, `test_nearby_services_api` |
| `GET /cases/<case_code>` | responder, shelter, admin | `CaseService.view` -> `allows()`; inaccessible and missing both 404 | Read-only rendering; consent gates diary and referral sections | stage12, `test_case_workspace` |
| `GET /api/diary?case_code=` | responder, shelter, admin | `allows()` on the case owner before consent or entry queries | Active `diary_sharing` consent; only `shared` entries; view audit | stage12, `test_stage4_diary_access` |
| `GET /cases/diary-photo/<id>` | responder, shelter, admin | Entry owner must satisfy `allows()` before file lookup | Active consent, shared entry, verified object, view audit | stage12, `test_stage4_diary_access` |
| `GET /api/consents?case_code=` | responder, shelter, admin | Case selected from the query, then `allows()`; admin sees all; default remains the demo case when omitted | Read only | stage12 |
| `GET /api/audit-log?case_code=` | responder, shelter, admin | Admin sees all; staff see events for assigned cases plus their own null-case events | Read only; `case_code` filter is applied inside that scope | stage12 |
| `GET /api/referrals`, `GET /referrals` | responder, shelter, admin | Responder: explicit grants only; shelter: own `shelter_id`; admin: every consent-active referral by role policy | Active `shelter_referral_sharing`; no alert location fields | `test_referral_access` |
| `POST /api/referrals` | responder, shelter, admin | `allows()` on the alert owner before consent or duplicate checks | Active `shelter_referral_sharing`; unresolved alert; one active referral | stage12, `test_referral_access` |
| `POST /api/referrals/<id>/status` | shelter, responder, admin | Shelter role bound to its own shelter; staff need `allows()` on the alert owner | Active referral consent and allowed state transition | stage12, `test_referral_access` |
| `POST /api/shelters/<id>/capacity` | shelter, responder, admin | Shelter role bound to its own `shelter_id`; responder/admin may update any shelter by role design | Bounded integer update and audit entry | `test_avenra` shelter-capacity tests |
| `POST /api/cases/<case>/access` | admin | Case must exist | Admin only; target must be an active responder/admin; grant/revoke audited | `test_stage7_boundaries`, `test_case_workspace` |
| `POST /api/worker/tick` | worker bearer | N/A: no browser, staff, or public authority | Constant-time bearer token; evaluation mode refuses dispatch | `test_stage6_worker` |
| Evidence retention/deletion CLI | operator | `assigned()` only; an admin-wide read policy is not enough | Explicit hosted-apply approval for hosted/production targets | `test_stage9_retention` |

## Survivor routes

All of these resolve the owner from the paired device token, never from a
client-supplied user or case selector.

| Route | Object check | Action check | Evidence |
| --- | --- | --- | --- |
| `GET/POST /api/contacts`, `DELETE /api/contacts/<id>`, `POST /api/contacts/<id>/sms` | Every query and update includes `user_id = device owner` | Validated South African number; SMS changes cancel only that contact's pending jobs | stage12, `test_contacts_api`, `test_contacts_validation` |
| `GET/POST /api/diary`, `GET /api/diary/<id>`, `GET /api/diary/<id>/photo`, `POST /api/diary/<id>/share` | Entry lookup bound to the device owner | Vault unlock, consent/share state, verified object bytes, audit | `test_stage4_diary_access`, `test_stage5_*` |
| `GET /api/alerts/<id>/status` | `alert.user_id == device owner` | Read only; no workflow mutation | `test_stage9_alert_queue` |
| `POST /api/alerts/by-client/<client_id>/location` | `X-Queue-Owner` must equal the device owner; alert lookup also bound | Consent token, short fix age, bounded coordinates | `test_alert_location_update` |
| `/api/vault/*`, `/api/onboarding` | Credential and details bound to the device owner | Vault passphrase/authority; onboarding field validation | `test_stage9_vault_access`, `test_onboarding` |
| `/api/contact-push/*` | Subscription/invite ownership includes contact and survivor scope | One-use invites, origin/CSRF checks, opt-in only | `test_webpush` |
| `GET /api/my-access` | Cursor signed for the device owner's case | Read only; no raw note or photo path | `test_stage4_diary_access` |

## Defects confirmed while building the matrix

1. `GET /api/consents` always read `Config.DEMO_CASE_CODE` for staff and ignored
   a requested case. Multi-case staff could not read consents for their other
   assigned cases. It now accepts `case_code`, defaults to the demo case when
   omitted, and applies the same `allows()` check as diary and case pages.
2. `GET /api/audit-log?case_code=...` produced `...1=1AND e.case_code = ?` (and
   the analogous malformed fragment on the staff path), so a case filter failed
   with a database error instead of scoping results. The filter now has its
   separating space and is exercised on both the admin and assigned-staff paths.

## Follow-up defect fixed 2026-10-30

3. `GET /api/referrals` and `/referrals` narrowed administrators to explicit
   `case_access` grants, while referral creation and status updates already used
   `allows()`. An administrator could create a referral on an unassigned case
   and then not see it. The list now follows the same policy: responders remain
   grant-scoped, shelters remain bound to their own shelter, and administrators
   see every consent-active referral. Consent remains a hard gate.

## Deliberately unchanged

- Administrators keep read/workflow visibility across all cases via `allows()`.
- Destructive retention/evidence deletion keeps using `assigned()`, so an
  administrator without an explicit grant cannot irreversibly delete evidence.
- Responder/admin capacity updates remain role-wide; shelter users remain bound
  to their own shelter. Changing this would be a product-policy decision, not a
  cross-object authorization fix.
- PostgreSQL advisory locking and the existing transaction strategy are left
  intact until concurrency behavior is measured.
