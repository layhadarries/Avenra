# Stage 6B Data Lifecycle, Retention Proposal & Pre-Pilot Mandatory Gate

> **Important Release Boundary:** Avenra's current hosted and local builds are scoped strictly for **fictional demonstration and technical evaluation**. Real adult survivor onboarding is blocked until every Stage 6B gate below has an accountable partner and engineering sign-off. Minors must never be enrolled under an adult pilot plan.

## 1. Data Inventory, Minimisation & Retention Proposal

| Record Type | Storage Location | Personal / Sensitive Fields | Minimisation Control | Proposed Pilot Retention & Deletion Policy |
|---|---|---|---|---|
| **Survivor Account (`users`)** | `users` table | Pseudonymous `case_code`, role, active flag | No legal name, national ID, or home address required for case code creation | Retained while case is active; deleted or anonymised upon survivor deletion request unless subject to an explicit, documented legal hold. |
| **Emergency Alerts (`alerts`, `alert_workflow`, `alert_history`)** | SQLite / Postgres DB | `case_code`, optional `lat`/`lng`, `location_accuracy`, status timestamps | Coordinates are omitted or redacted immediately in staff views when `location_sharing` consent is inactive | Active operational window: 90 days after alert resolution, followed by coordinate purge unless retained by survivor request. |
| **Evidence Diary (`diary_entries` + `UPLOADS_DIR`)** | `diary_entries` table + private object/file storage | `note`, JPEG photo (`diary_<uuid>.jpg`), SHA-256 digests, `captured_at`, `received_at`, `shared` | Client strips EXIF/GPS via canvas redraw; server rejects any v2 JPEG containing EXIF/XMP/ICC/COM segments; staff access requires `shared=1` + active `diary_sharing` consent + `case_access` assignment | Controlled by survivor: unsharing (`POST /api/diary/<id>/share`) or global consent withdrawal immediately blocks staff access; full deletion must purge both the DB row and the underlying photo object + expired backups. |
| **Trusted Contacts & Push Subscriptions (`contacts`, `push_subscriptions`, `push_invites`)** | DB (`encrypted_subscription` via Fernet) | Contact label, phone (SMS mode), Fernet-encrypted push endpoint/keys, SHA-256 token hashes | Push payloads are strictly neutral (`"You have a new notification"`); invite/ack tokens stored only as SHA-256 hashes (`expires_at` = 24 h) | Deleting a contact cascades (`ON DELETE CASCADE`) to `push_invites` and `push_subscriptions`; expired invites and revoked subscriptions are purged on schedule. |
| **Consent & Audit Records (`consents`, `audit_log`)** | DB | Actor identifier, action code, `case_code`, timestamp | Audit logs never store raw diary notes, photo bytes, device tokens, passwords, or signed URLs | Retained for accountability during pilot + 1 year; survivor `/api/my-access` exposes only safe staff-viewing events (`case_viewed`, `diary_viewed`, `diary_photo_viewed`). |

## 2. Consent Withdrawal vs Deletion

Stage 9 adds bounded, previewable record-level retention commands and encrypted
offline queues; see [private storage and recovery](stage-9-private-storage-and-recovery.md).
This does not approve the proposed retention durations or implement account-wide,
browser-copy or backup deletion. The primary DB/provider encryption, independent
custody and hosted restore gates still require operational evidence.

- **Consent Withdrawal (`POST /api/consents` or `POST /api/diary/<id>/share`):** Immediately stops future disclosure to staff and trusted contacts and invalidates open staff screens via `access_signature`, while preserving the survivor's own vault records.
- **Account / Record Deletion:** Removes the record from the primary database and deletes/quarantines associated photo objects across primary storage and expiring backup snapshots.

## 3. Stage 6B Mandatory Gates Before Real Adult Survivor Data

| Gate | Required Implementation Before Pilot | Status |
|---|---|---|
| **1. Individual Survivor Authority** | Replace shared prototype `X-Device-Token` (`demo-device`) with one-time pairing, revocable per-device credentials, session rotation, and device removal. | **Blocked for Pilot** (Prototype token active for demo only) |
| **2. Staff Trust & MFA** | Invitation-only staff provisioning, mandatory multi-factor authentication (MFA), scoped case assignments, and immediate session revocation on offboarding. | **Partial** (Scoped `case_access` & `auth_version` revocation implemented; MFA required before pilot) |
| **3. Encryption & Key Management** | Threat model review, encrypted database/object storage and backups, KMS/separate key custody, and key rotation drill. | **Partial** (Fernet subscription encryption + SHA-256 token hashing implemented; full DB/object KMS rotation required before pilot) |
| **4. Granular Location Consent** | Split `location_sharing` into separate `location_to_staff` and `location_to_contacts` consents without silently expanding existing permissions. | **Planned for Stage 6B** |
| **5. POPIA & Organisational Governance** | Partner-led POPIA review (special personal information, operator agreements, cross-border transfer assessment, named Information Officer, and regulator breach notification process). | **Requires Partner Sign-Off** |
| **6. Service Safety & Escalation** | Verified shelter operating hours, named responder shift coverage, handover protocol, and unacknowledged-alert escalation SLA. | **Requires Partner Sign-Off** |
| **7. Independent Security & Practitioner Review** | Third-party penetration test and GBV practitioner usability/safety review with all blocking findings closed. | **Required Before Pilot** |

## 4. Pitch & Claims Discipline (`T6.4`)

When demonstrating Avenra in the 3–4 minute walkthrough or 20-second pitch:
- Use **only fictional records** (`SP-1042`, demo contacts, synthetic test photos).
- State clearly that offline capture queues items in IndexedDB on the phone until connectivity returns, and that **Server received** (`stored: true`) is shown only after a verified durable server receipt (`201` or `200`).
- Distinguish **provider acceptance** (`accepted`) from confirmed human reading (`acknowledged`), and **referral acceptance** (`accepted`) from confirmed physical shelter placement (`placed`).
- **Never claim:** "zero airtime/data," "invisible to an abuser inspecting the unlocked phone," "tamper-proof / court-certified forensic evidence," or "guaranteed emergency rescue."
