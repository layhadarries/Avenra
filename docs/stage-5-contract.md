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
* **Authentication:** Device Token header `X-Device-Token: <token>` (authority is derived strictly from the authenticated survivor identity; client-supplied `user_id`, `case_code`, `owner_id`, or `survivor_id` fields are rejected with `400 invalid_authority_selector`)
* **Content-Type:** `multipart/form-data` (v2 preferred binary upload) or `application/json` (v2 and legacy v1 queue compatibility)

#### Request Payload Schema (`application/json` or `multipart/form-data`)
```json
{
  "client_id": "string (UUIDv4 or stable ASCII ID, 1-64 chars, required)",
  "contract_version": 2,
  "note": "string (plain text, max 4,000 characters after CRLF->LF normalisation, optional if photo provided)",
  "photo_data": "string (JSON path: data URL starting with 'data:image/jpeg;base64,', optional if note provided)",
  "file_hash": "string (64-char lowercase hex SHA-256 of raw JPEG bytes if photo present, else canonical UTF-8 note bytes)",
  "note_sha256": "string (optional in request, always returned in receipt: 64-char hex SHA-256 of canonical UTF-8 note bytes)",
  "photo_sha256": "string or null (optional in request, always returned in receipt: 64-char hex SHA-256 of raw JPEG bytes, or null if note-only)",
  "entry_fingerprint": "string (optional in request, always returned in receipt: SHA-256 of canonical JSON payload state)",
  "shared": false,
  "captured_at": "string (optional ISO-8601 UTC timestamp with explicit offset; legacy alias: created_at)"
}
```
For `multipart/form-data`, pass the binary JPEG file in the `photo` file part (`Content-Type: image/jpeg`) and metadata fields (`client_id`, `note`, `shared` as `"true"`/`"false"`, `captured_at`, `file_hash`, `note_sha256`, `photo_sha256`, `entry_fingerprint`, `contract_version`) as single-valued form fields.

#### Validation & Constraints
* At least one of `note` or photo must be present (`400 note_or_photo_required`).
* `client_id` must be non-empty, stripped, printable ASCII, and $\le$ 64 characters (`400 client_id_required` or `400 invalid_client_id`).
* `note` is canonicalised by normalising `\r\n` and `\r` to `\n` and stripping outer whitespace; length must be $\le$ 4,000 characters (`400 note_too_long`).
* **Image Bounds & Metadata Inspection:**
  - `contract_version: 2` (default): raw JPEG size $\le$ **2 MiB** (`413 photo_too_large`), full Pillow JPEG decode + `load()`, longest edge $\le$ **1,280 px**, total pixels $\le$ $1,280 \times 1,280$, and zero EXIF (`APP1`), XMP, GPS, ICC (`APP2`), or JPEG `COM` metadata (`400 prohibited_photo_metadata`).
  - `contract_version: 1` (legacy queue compatibility): raw JPEG size $\le$ **4 MiB**, full JPEG decode up to 8,192 px / 16 MP (`400 invalid_photo`).
* **Canonical Digests:**
  - `note_sha256 = sha256(canonical_note.encode("utf-8")).hexdigest()`
  - `photo_sha256 = sha256(raw_jpeg_bytes).hexdigest()` (or `null` when no photo is present)
  - `file_hash = photo_sha256 if photo_sha256 is not None else note_sha256`
  - `entry_fingerprint = sha256(json.dumps({"captured_at": captured_at, "note_sha256": note_sha256, "photo_sha256": photo_sha256, "shared": bool(shared), "v": contract_version}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()`
  - Any mismatch between client-supplied digests and server-computed digests returns `422 hash_mismatch`.
* `shared` must be a strict boolean (`400 shared_must_be_boolean`).
* Client-supplied `received_at` is ignored; `received_at` is always assigned by the server at durable commit time.

#### Response: First Commit (`HTTP 201 Created`) & Idempotent Replay (`HTTP 200 OK`)
Initial durable commit returns `201 Created`. Replaying the identical `client_id` and identical canonical content for the same survivor verifies the stored object on disk/object storage and returns `200 OK` with the same receipt without creating duplicate rows, files, or audit events:
```json
{
  "id": 14,
  "client_id": "c1f7a28e-8a90-4821-b384-5f16e9198651",
  "stored": true,
  "contract_version": 2,
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "note_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "photo_sha256": null,
  "entry_fingerprint": "f053c9798718d3679e889bd50888f062d28257023c6c2ca1701ab82a596a7180",
  "shared": false,
  "has_photo": false,
  "created_at": "2026-10-24T22:00:00Z",
  "captured_at": "2026-10-24T22:00:00Z",
  "received_at": "2026-10-24T22:00:01Z"
}
```

#### Error Responses
| HTTP Status | Error Code | Condition |
|---|---|---|
| `400 Bad Request` | `client_id_required` / `invalid_client_id` | Missing, blank, non-ASCII, or > 64 char client ID |
| `400 Bad Request` | `invalid_authority_selector` | Request body attempts to supply `user_id`, `case_code`, `owner_id`, or `survivor_id` |
| `400 Bad Request` | `note_or_photo_required` | Neither note nor photo submitted |
| `400 Bad Request` | `note_too_long` | Canonicalised note text exceeds 4,000 characters |
| `400 Bad Request` | `jpeg_data_url_required` / `jpeg_media_type_required` | Missing JPEG header/MIME type |
| `400 Bad Request` | `prohibited_photo_metadata` | v2 JPEG contains EXIF, XMP, ICC, or comment segments |
| `400 Bad Request` | `invalid_photo` | Corrupt JPEG, exceeds dimension bounds, or legacy > 4 MiB |
| `400 Bad Request` | `shared_must_be_boolean` | Non-boolean value passed for `shared` |
| `400 Bad Request` | `invalid_capture_time` / `conflicting_capture_times` | Malformed, timezone-naive, or future (> 5 min skew) timestamp |
| `401 Unauthorized` | `bad_device_token` | Missing or invalid `X-Device-Token` header |
| `409 Conflict` | `client_id_conflict` | `client_id` already committed with different content or by another survivor |
| `413 Payload Too Large` | `photo_too_large` | Decoded v2 photo exceeds 2 MiB (`2,097,152` bytes) |
| `422 Unprocessable` | `hash_mismatch` | Supplied `file_hash`, `note_sha256`, `photo_sha256`, or `entry_fingerprint` mismatches |
| `503 Service Unavailable` | `diary_storage_unavailable` | Storage write/verification failure or database transaction failure |

---

### 2.2 List Survivor Vault Receipts (Paginated)
* **Route:** `GET /api/diary?limit=<1..50>&cursor=<signed_token>`
* **Authentication:** Device Token header `X-Device-Token: <token>`
* **Caching:** `Cache-Control: private, no-store`
* **Privacy Contract:** Returns storage receipts for the authenticated survivor device (`entries` + `next_cursor`). Raw note text is excluded from list views to protect against shoulder surfing on shared devices. Cursors are HMAC-signed and bound to `survivor_id`.

---

### 2.3 Survivor Own-Entry Detail, Photo & Per-Entry Sharing
* **Detail Route:** `GET /api/diary/<int:entry_id>` (`X-Device-Token`)
  - Returns `{"entry": {..., "note": "...", "photo_url": "/api/diary/<id>/photo"}}` for the authenticated owner, or `404 not_found` for any other survivor.
* **Photo Route:** `GET /api/diary/<int:entry_id>/photo` (`X-Device-Token`)
  - Verifies stored object SHA-256 integrity and streams `image/jpeg` with `Cache-Control: private, no-store`, or `404` if not owned / missing / corrupt.
* **Per-Entry Share Toggle:** `POST /api/diary/<int:entry_id>/share` (`X-Device-Token`)
  - Body: `{"shared": true | false}`. Updates per-entry `shared` flag transactionally and returns `{"entry": <receipt>, "global_diary_consent_active": <bool>}`.
  - Global `diary_sharing` consent withdrawal blocks staff disclosure for all entries immediately; re-granting global consent exposes only entries whose individual `shared` flag is `true`.

---

### 2.4 Staff Diary Access (Dual-Gated)
* **Route:** `GET /api/diary?case_code=<CASE_CODE>` (Session-authenticated responder/admin with active `case_access` assignment)
* **Authorization:** Requires `responder` or `admin` role AND an active row in `case_access` for the survivor (`403` for shelter users, `404` for unassigned staff/admins).
* **Consent Verification:**
  - If global `diary_sharing` consent is **active**, returns entries marked `shared = 1` along with `consent_active: true`.
  - If global `diary_sharing` consent is **revoked**, returns `consent_active: false` and `entries: []`.
* **Audit Logging:** Logged to `audit_log` under `diary_viewed` when shared entries are returned.

---

### 2.5 Staff Photo Retrieval
* **Route:** `GET /cases/diary-photo/<int:entry_id>`
* **Authorization:** Session-authenticated responder/admin with assigned access to the entry's case.
* **Gating:** Requires `entry.shared == True`, active `diary_sharing` consent (`403` if revoked), and verified on-disk SHA-256 digest (`404` if unshared, unassigned, missing, or corrupt).
* **Audit Logging:** Logged to `audit_log` under `diary_photo_viewed` only after a verified `200 OK` response.

---

## 3. Client Specifications (Survivor PWA)

### 3.1 Image Compression & Pre-Processing
1. **Target Dimensions:** Downscale images so the longest edge does not exceed **1,280 px**.
2. **Compression Target:** Quality parameter ~0.75 to 0.8 targeting roughly **300 KiB** for readable documentary evidence. Hard decoded limit: $\le$ 2 MiB (`2,097,152` bytes) for v2 uploads (4 MiB for legacy v1 queued items).
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
* **Canonical Note Digest (`note_sha256`):** Computed over UTF-8 bytes of `note.replace(/\r\n?/g, '\n').trim()`.
* **Photo Digest (`photo_sha256`):** Computed strictly over the binary JPEG bytes (`null` when no photo is attached).
* **Primary `file_hash`:** Equals `photo_sha256` when a photo is present, otherwise `note_sha256`.

### 3.3 Offline Queue & IndexedDB Schema
* **Object Store:** `diary_queue`, key path `client_id`.
* **Transaction Invariant:** A draft is only marked *"Saved on this phone"* after `transaction.oncomplete` fires. A request-level `onsuccess` is insufficient.
* **Receipt Verification & Deletion:**
  - Verify `res.status === 201 || res.status === 200`.
  - Verify `json.stored === true && Number.isInteger(json.id) && json.id > 0 && json.client_id === item.client_id && json.file_hash === item.file_hash`.
  - Only upon successful verification, remove the record from `diary_queue`.

### 3.4 Quick Exit Safeguard
* Clicking the **Quick Exit** button immediately:
  1. Hides all diary views and renders the public cover (`/survivor/cover.html` or weather view).
  2. Clears textareas, file input elements, and thumbnail previews.
  3. Releases all pending Blob object URLs.
  4. Preserves any already committed IndexedDB queue items (never deletes offline drafts).

---

## 4. Verified Test Fixtures

### Fixture A: Note-Only Upload (Unicode & CRLF Normalisation)
Input `note`: `"Suspect observed outside residence.\r\nRegistration: CA 123-456 — 21:00"`  
Canonical note: `"Suspect observed outside residence.\nRegistration: CA 123-456 — 21:00"`  
`note_sha256` / `file_hash`: `"27079ca436e5502fd4b8f19f1f597101f4421dc41e1920c5c2618307120a2f43"`
```json
{
  "client_id": "00000000-0000-4000-8000-000000000002",
  "contract_version": 2,
  "note": "Suspect observed outside residence.\r\nRegistration: CA 123-456 — 21:00",
  "file_hash": "27079ca436e5502fd4b8f19f1f597101f4421dc41e1920c5c2618307120a2f43",
  "note_sha256": "27079ca436e5502fd4b8f19f1f597101f4421dc41e1920c5c2618307120a2f43",
  "shared": true,
  "captured_at": "2026-10-24T20:15:00Z"
}
```

### Fixture B: Valid Receipt Response (`201 Created` / Idempotent Replay `200 OK`)
```json
{
  "id": 1,
  "client_id": "00000000-0000-4000-8000-000000000002",
  "stored": true,
  "contract_version": 2,
  "file_hash": "27079ca436e5502fd4b8f19f1f597101f4421dc41e1920c5c2618307120a2f43",
  "note_sha256": "27079ca436e5502fd4b8f19f1f597101f4421dc41e1920c5c2618307120a2f43",
  "photo_sha256": null,
  "entry_fingerprint": "f05bc5d701be0ba4536f38a85c0b5df2b1df86f49e81c36f3d0e67488d8b7b41",
  "shared": true,
  "has_photo": false,
  "created_at": "2026-10-24T20:15:00Z",
  "captured_at": "2026-10-24T20:15:00Z",
  "received_at": "2026-10-24T20:15:02Z"
}
```

### Fixture C: Deterministic Error Fixtures (`409`, `413`, `422`, `503`)
* **`409 Conflict`** (same `client_id` replayed with modified note, photo, timestamp, or `shared` flag, or owned by another survivor):
  ```json
  {"error": "client_id_conflict"}
  ```
* **`413 Payload Too Large`** (v2 photo > 2,097,152 bytes):
  ```json
  {"error": "photo_too_large"}
  ```
* **`422 Unprocessable Entity`** (corrupted bytes or mismatched `file_hash` / `note_sha256` / `photo_sha256` / `entry_fingerprint`):
  ```json
  {"error": "hash_mismatch"}
  ```
* **`503 Service Unavailable`** (storage write failure, missing/corrupt object on replay, or database transaction failure):
  ```json
  {"error": "diary_storage_unavailable"}
  ```

