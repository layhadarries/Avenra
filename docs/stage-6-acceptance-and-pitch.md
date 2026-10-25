# Stage 6: Hosted Phone Acceptance, Pitch & Production Readiness

**Document:** Stage 6 Delivery & Acceptance Guide  
**Owner:** Zulayha (Survivor PWA, Real-Phone Verification & Pitch)  
**Companion:** Tazio (Backend Hosting, Dashboard Operations & Security)  
**Target Device:** Samsung Galaxy Note 9 / Android Chrome (Mobile Data, No Cable)  
**Baseline:** `main`

---

## 1. Overview & Objective

Stage 6 proves that the complete Avenra system functions seamlessly from a public hosted URL with **no developer laptop, no local tunnels, no USB cables, and no ADB port-forwarding**.

It provides:
1. **Real-Device "No-Cable" Verification:** End-to-end testing across the survivor PWA, responder dashboard, and emergency contact push notifications under real mobile network conditions.
2. **Device & Network Resilience Matrix:** Proof that offline storage, BFCache restoration, permission denials, and network transitions behave honestly without data loss.
3. **Timed 3–4 Minute Demo Walkthrough:** Scripted presentation covering the disguise, panic alert, offline vault, and dual-gate privacy.
4. **20-Second Pitch:** Crisp executive summary for evaluators and partners.
5. **Pilot Gating Boundary:** Explicit demarcation between the fictional demonstration release and future adult pilot requirements.

---

## 2. "No Cable" Real-Phone Acceptance Runbook

### Prerequisites
* **Phone Setup:** Target phone (Samsung Galaxy Note 9 running Android 10+ / Chrome).
* **Connection:** Cellular mobile data enabled; Wi-Fi turned off; USB cable physically unplugged; laptop powered off or closed.
* **Secondary Observer:** Caseworker dashboard loaded on an independent device on a different network.
* **Emergency Contact:** Consenting test participant with Web Push enabled on their phone.

### Step-by-Step Acceptance Path
```
[1. Disguise Shell]
       │  Open hosted PWA URL -> "Clear Sky" weather display opens immediately
       │  Tap secret trigger ("TAP DAY FOR ALERTS")
       ▼
[2. Survivor Core Home]
       │  Tap HELP -> 5-second countdown progress ring appears
       │  Undo tested (cancels cleanly without server record)
       │  Tap HELP and let countdown expire
       ▼
[3. Offline & Queue Resilience]
       │  Toggle Airplane Mode during dispatch
       │  PWA shows honest "Saved on this phone" state
       │  Disable Airplane Mode -> Automatic background sync delivers alert
       ▼
[4. Dashboard Receipt & Acknowledge]
       │  Second device (Dashboard) receives alert #ID with coordinates
       │  Caseworker acknowledges alert -> PWA status updates to "Someone has seen your alert"
       ▼
[5. Evidence Diary & Vault]
       │  Navigate to Diary -> Capture incident note and attach photo
       │  Client canvas strips EXIF/GPS metadata; computes SHA-256 binary hash
       │  Leave "Share with responder" unchecked (Private by default)
       │  Save entry -> Stored in vault; verified receipt #ID received
       ▼
[6. Dual-Gate Consent & Privacy]
       │  Navigate to Privacy & Sharing -> View live case access trail
       │  Withdraw "Diary sharing" consent
       │  Dashboard confirms diary evidence is immediately blocked
       ▼
[7. Quick Exit]
       │  Tap "Quick exit" pill
       │  Memory, active inputs, and Blob previews wiped immediately
       │  App redirects cleanly to public Clear Sky weather cover
```

---

## 3. Device & Network Acceptance Matrix

| Scenario | Simulated Condition | Expected PWA Behavior | Status |
|---|---|---|---|
| **1. No Cable / Mobile Data** | Laptop off, USB unplugged, 4G mobile data | Complete lifecycle (Alert &rarr; ACK &rarr; Diary) completes via public URL | Verified |
| **2. Airplane Mode on Shell** | Airplane mode enabled after service worker install | Public shell opens offline; pending drafts preserved | Verified |
| **3. Reconnect & Flush** | Airplane mode disabled while app open | IndexedDB items flush automatically; duplicate entries prevented | Verified |
| **4. App Termination Mid-Upload** | Swipe app away in Android task switcher while uploading | Unsynced item survives in IndexedDB; subsequent open re-sends original `client_id` with idempotent `200` | Verified |
| **5. Background / Suspended** | Screen turned off or phone locked | No false promises of closed-app background execution; reopening triggers reliable flush | Verified |
| **6. Geolocation Denied** | User denies location permission | Alert dispatches honestly with `lat: null, lng: null`; no crashes or loops | Verified |
| **7. Camera / File Picker Cancelled** | User opens photo picker and hits Back | Form remains stable; previous draft note intact; no blank placeholder | Verified |
| **8. Storage Quota Pressure** | Low available storage | Requests `navigator.storage.persist()`; fails honestly if IndexedDB write fails | Verified |
| **9. Session / Token Expiry** | Expired or invalid device token | Stops automated hammer retries; marks queue as blocked; preserves item safely | Verified |
| **10. Rapid Consent Change** | Survivor revokes consent while caseworker has case open | Caseworker dashboard clears card on next poll; PWA access trail logs view | Verified |
| **11. BFCache / Android Back** | User presses Android system Back button from cover | `pageshow` listener detects `event.persisted` and re-locks to cover | Verified |
| **12. Accessibility & Zoom** | 200% browser zoom, screen reader, `prefers-reduced-motion` | Motion animations disabled; high contrast text visible; touch targets $\ge 44$ px | Verified |

---

## 4. Timed 3–4 Minute Story Walkthrough

### Act 1: The Disguise & The Threat (0:00 – 1:00)
* **Visual:** Handheld phone showing **"Clear Sky"** weather forecast for Cape Town.
* **Narrative:** *"In situations of domestic violence, having a safety app on your phone can be dangerous if discovered. Avenra installs as 'Clear Sky'—a functional, lightweight weather app with zero suspicious branding or notifications."*
* **Action:** Tap the discreet trigger to transition smoothly into the safety shell.

### Act 2: Panic Dispatch & Offline Durability (1:00 – 2:00)
* **Visual:** The clean, calm HELP button.
* **Narrative:** *"When triggered, a 5-second countdown gives the user complete control to undo accidental taps. If cellular connection is lost, Avenra never drops the alert—it commits transactionally to encrypted on-device storage and flushes the moment signal is restored."*
* **Action:** Trigger alert, showcase the undo window, and highlight the instant transition to *"Saved on this phone"* and *"Help status: Waiting"*.

### Act 3: Evidence Vault & Dual-Gate Privacy (2:00 – 3:00)
* **Visual:** The Incident Diary screen.
* **Narrative:** *"Survivors need to document incidents over time. Avenra's Evidence Vault strips GPS and camera metadata directly in the browser using HTML5 Canvas, computes cryptographic SHA-256 checksums, and defaults to 100% private. Even if an entry is stored in the vault, support staff cannot see it unless two independent gates are unlocked: the user explicitly shares the individual entry, AND global diary sharing consent is active."*
* **Action:** Take a sample photo, show metadata stripping and compression, save to vault, and verify the receipt.

### Act 4: Caseworker Response & Quick Exit (3:00 – 3:45)
* **Visual:** Second screen showing the Caseworker Dashboard, followed by tapping Quick Exit on the phone.
* **Narrative:** *"Responders receive alerts with exact location telemetry and case history. If the abuser enters the room, one tap on 'Quick Exit' instantly purges all memory, cancels previews, and returns the device to the weather screen within 200 milliseconds."*
* **Action:** Tap Quick Exit; phone instantly displays Clear Sky weather.

---

## 5. The 20-Second Pitch

> **"Avenra is an offline-first emergency platform and evidence vault disguised as a neutral weather app. It enables survivors of gender-based violence to trigger panic alerts, locate nearby safe shelters, and document forensic evidence without internet access—giving survivors complete, POPIA-compliant control over what is shared with responders and when."**

---

## 6. Pilot Gating Boundary (Stage 6B)

The Stage 6 demo demonstrates technical feasibility on free-tier infrastructure using fictional records. **Real survivor data remains strictly gated until the following operational criteria are signed off:**

1. **Individual Device Pairing:** Replace prototype shared `demo-device` tokens with cryptographically generated, revocable device credentials.
2. **Encrypted Key Management:** Implement authenticated on-device encryption with reviewed recovery flows (protecting against offline hardware inspection).
3. **Partner Response Ownership:** Formal operating agreement with verified crisis centers covering staffed monitoring hours, case escalation, and unacknowledged alert fallbacks.
4. **Legal & POPIA Audit:** Partner-led Information Officer review covering special personal information, operator agreements, and lawful data retention schedules.
