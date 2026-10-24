# Stage 5 Shared Contract: Survivor Evidence Diary & Vault

**Status:** Proposed & Frozen for Implementation  
**Owners:** Zulayha (Survivor PWA, Client Compression & Offline Queue) · Tazio (Vault Backend, Storage Receipts & Access Gates)  
**Target:** Avenra Stage 5 Integration Checkpoint  
**Companion:** `Avenra-Zulayha-Stages-5-and-6.md`

---

## 1. Scope & Core Invariants

Stage 5 equips the survivor with an offline-first evidence diary: capturing text notes, capturing or uploading photos without signal, distinguishing between local device storage and confirmed server receipts, choosing private vs caseworker-shared scope, and maintaining zero-data-loss Quick Exit protections.

### Invariant Rules
1. **Dual-Gate Privacy:** Storing an entry in the account does **not** grant staff access. For caseworkers or responders to view an entry, two conditions must be true:
   - The individual entry's `shared` flag must be `true` (`1`).
   - The survivor's global `diary_sharing` consent must be active (`1`).
2. **Alert Independence & Priority:** The emergency alert queue (`/api/alerts`) retains absolute operational priority over diary synchronisation. A pending diary item or photo upload must never block, delay, or discard an alert.
3. **Honest Receipt Verification:** A queued local item is removed from IndexedDB **only** after validating an authentic, durable server receipt (`stored: true`, positive integer `id`, matching `client_id`, matching `file_hash`). 
4. **Idempotent Replay (201 vs 200):** 
   - Initial successful commit returns `HTTP 201 Created`.
   - Replay of an identical `client_id` by the same survivor returns `HTTP 200 OK` with the existing receipt.
   - Replay of an existing `client_id` belonging to a different user returns `HTTP 409 Conflict`.
5. **No Blind Data URL Hashing:** SHA-256 integrity digests must be computed against the raw binary decoded image bytes (`ArrayBuffer` / `Blob`), **never** against the ASCII base64 string or data URL wrapper.
6. **Zero EXIF / Location Leakage:** All client photo uploads must be transcoded via HTML5 Canvas prior to transmission to strip GPS, camera metadata, and device identifiers.
7. **Identity Disguise Stability:** The survivor PWA shell identity is strictly standardized to `"Clear Sky"` across all HTML titles, manifests, headers, and UI chrome.

---

## 2. API Endpoints Specification

### 2.1 Upload Diary Entry
* **Route:** `POST /api/diary`
* **Authentication:** Device Token header `X-Device-Token: <token>` (prototype default: `demo-device`)
* **Content-Type:** `application/json` (v1 migration protocol; v2 multipart reserved for binary streaming)

#### Request Payload Schema
```json
{
  "client_id": "string (UUIDv4 or stable client ID, 1-64 chars, required)",
  "note": "string (plain text, max 4,000 characters, optional if photo provided)",
  "photo_data": "string (data URL starting with 'data:image/jpeg;base64,', max 4 MiB decoded, optional if note provided)",
  "file_hash": "string (64-char lowercase hexadecimal SHA-256 digest, required if photo provided, optional for note-only)",
  "shared": "boolean (default: false)",
  "created_at": "string (ISO-8601 UTC timestamp, optional; defaults to server time)"
}
```

#### Validation & Constraints
* At least one of `note` or `photo_data` must be present (`400 note_or_photo_required`).
* `client_id` must be non-empty, stripped, and $\le$ 64 characters (`400 client_id_required`).
* `note` length must be $\le$ 4,000 characters (`400 note_too_long`).
* `photo_data` must start with `data:image/jpeg;base64,` and decode to valid JPEG magic bytes (`\xff\xd8`) with length $\le$ 4 MiB (`400 invalid_photo` or `400 jpeg_data_url_required`).
* If `file_hash` is provided, the backend calculates the SHA-256 digest of the raw decoded photo bytes (or UTF-8 bytes of `note` if photo is absent). If the client hash does not match, the upload is rejected (`422 hash_mismatch`).
* `shared` must be a strict boolean (`400 shared_must_be_boolean`).

#### Response: First Commit (`HTTP 201 Created`)
```json
{
  "id": 14,
  "client_id": "c1f7a28e-8a90-4821-b384-5f16e9198651",
  "stored": true,
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "shared": false,
  "has_photo": true,
  "created_at": "2026-10-24T22:00:00Z"
}
```

#### Response: Idempotent Replay (`HTTP 200 OK`)
If an entry with the exact same `client_id` already exists for this survivor:
```json
{
  "id": 14,
  "client_id": "c1f7a28e-8a90-4821-b384-5f16e9198651",
  "stored": true,
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "shared": false,
  "has_photo": true,
  "created_at": "2026-10-24T22:00:00Z"
}
```

#### Error Responses
| HTTP Status | Error Code | Condition |
|---|---|---|
| `400 Bad Request` | `client_id_required` | Missing or blank client ID |
| `400 Bad Request` | `note_or_photo_required` | Neither note nor photo submitted |
| `400 Bad Request` | `note_too_long` | Note text exceeds 4,000 characters |
| `400 Bad Request` | `jpeg_data_url_required` | Photo does not have `data:image/jpeg;base64,` header |
| `400 Bad Request` | `invalid_photo` | Invalid base64, missing `\xff\xd8` header, or > 4 MiB |
| `400 Bad Request` | `shared_must_be_boolean` | Non-boolean value passed for `shared` |
| `401 Unauthorized` | `bad_device_token` | Missing or invalid `X-Device-Token` header |
| `409 Conflict` | `client_id_conflict` | `client_id` claimed by another survivor account |
| `422 Unprocessable` | `hash_mismatch` | Supplied `file_hash` does not match server-computed digest |

---

### 2.2 List Survivor Vault Receipts
* **Route:** `GET /api/diary`
* **Authentication:** Device Token header `X-Device-Token: <token>`
* **Privacy Contract:** Returns storage receipts for the authenticated survivor device. Raw note text is excluded from list views to protect against shoulder surfing on shared devices.

#### Response (`HTTP 200 OK`)
```json
{
  "entries": [
    {
      "id": 14,
      "client_id": "c1f7a28e-8a90-4821-b384-5f16e9198651",
      "stored": true,
      "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "shared": false,
      "has_photo": true,
      "created_at": "2026-10-24T22:00:00Z"
    }
  ]
}
```

---

### 2.3 Staff Diary Access (Dual-Gated)
* **Route:** `GET /api/diary` (Session-authenticated caseworker / responder)
* **Parameters:** `case_code` query param (e.g. `?case_code=SP-1042`)
* **Authorization:** Requires responder/admin role and active case access.
* **Consent Verification:**
  - If global `diary_sharing` consent is **active**, returns entries marked `shared = 1` along with `consent_active: true`.
  - If global `diary_sharing` consent is **revoked**, returns `consent_active: false` and an empty `entries: []` array.
* **Audit Logging:** Every view is logged to `audit_log` under `diary_viewed`.

---

### 2.4 Staff Photo Retrieval
* **Route:** `GET /cases/diary-photo/<int:entry_id>`
* **Authorization:** Session-authenticated caseworker with assigned access to the entry's case.
* **Gating:** Requires both entry `shared = 1` and survivor's active `diary_sharing` consent.
* **Response:** Binary JPEG image (`image/jpeg`) or `403 Forbidden` if consent is revoked.
* **Audit Logging:** Every fetch is logged to `audit_log` under `diary_photo_viewed`.

---

## 3. Client Specifications (Survivor PWA)

### 3.1 Image Compression & Pre-Processing
1. **Target Dimensions:** Downscale images so the longest edge does not exceed **1,280 px**.
2. **Compression Target:** Quality parameter ~0.75 to 0.8 targeting roughly **300 KiB** for readable documentary evidence. Hard decoded limit: $\le$ 2 MiB.
3. **Canvas Redraw:** Draw input file to `<canvas>` to strip all EXIF, GPS, camera serials, and thumbnail metadata before reading `canvas.toBlob('image/jpeg', 0.8)`.
4. **Memory Hygiene:** Every `URL.createObjectURL()` used for thumbnail previews must be explicitly released via `URL.revokeObjectURL()` upon submission, entry removal, or page unload.

### 3.2 Integrity Hashing (SHA-256)
```javascript
async function computeSha256(arrayBuffer) {
  const digestBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
  const hashArray = Array.from(new Uint8Array(digestBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
```
* **Photo present:** Hash is computed strictly over the binary JPEG bytes.
* **Note-only:** Hash is computed over UTF-8 encoded text bytes `new TextEncoder().encode(noteText.trim())`.

### 3.3 Offline Queue & IndexedDB Schema
* **Database Name:** Retain canonical `cape-weather-queue` (or dedicated object store `diary_queue` within the database).
* **Object Store:** `diary_queue`, key path `client_id`.
* **Transaction Invariant:** A draft is only marked *"Saved on this phone"* after `transaction.oncomplete` fires. A request-level `onsuccess` is insufficient.
* **Queue Record Schema:**
```javascript
{
  client_id: "c1f7a28e-8a90-4821-b384-5f16e9198651",
  note: "Incident note text...",
  photo_data: "data:image/jpeg;base64,...",
  file_hash: "a4f1...",
  shared: false,
  created_at: "2026-10-24T22:00:00Z",
  status: "queued" // "queued" | "uploading" | "failed"
}
```
* **Receipt Verification & Deletion:**
  - Verify `res.status === 201 || res.status === 200`.
  - Verify `json.stored === true && json.client_id === item.client_id && json.file_hash === item.file_hash`.
  - Only upon successful verification, remove the record from `diary_queue`.

### 3.4 Quick Exit Safeguard
* Clicking the **Quick Exit** button immediately:
  1. Hides all diary views and renders the public cover (`/survivor/cover.html` or weather view).
  2. Clears textareas, file input elements, and thumbnail previews.
  3. Releases all pending Blob object URLs.
  4. Preserves any already committed IndexedDB queue items (never deletes offline drafts).

---

## 4. Test Fixtures

### Fixture A: Combined Note and Photo Upload
```json
{
  "client_id": "00000000-0000-4000-8000-000000000001",
  "note": "Threatening message taped to window at 21:00.",
  "photo_data": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=",
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "shared": false,
  "created_at": "2026-10-24T20:00:00Z"
}
```

### Fixture B: Note-Only Upload
```json
{
  "client_id": "00000000-0000-4000-8000-000000000002",
  "note": "Suspect observed in vehicle outside residence. Vehicle registration: CA 123-456.",
  "file_hash": "ca978112ca1bbdcafac231b39a23dc4da7860814965f7471e869cce0a84854f3",
  "shared": true,
  "created_at": "2026-10-24T20:15:00Z"
}
```

### Fixture C: Valid Receipt Response (`201 Created` / `200 OK`)
```json
{
  "id": 1,
  "client_id": "00000000-0000-4000-8000-000000000001",
  "stored": true,
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "shared": false,
  "has_photo": true,
  "created_at": "2026-10-24T20:00:00Z"
}
```
