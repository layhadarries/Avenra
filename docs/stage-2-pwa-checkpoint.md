# Stage 2 PWA integration checkpoint

The five-contact limit supersedes the original three-contact handout. The server returns masked numbers with four trailing digits. The public shell cache is `clear-sky-shell-v5`.

## Behaviour

- One submission path: commit a pending IndexedDB transaction, then let the queue send it. A failed/aborted save has a separate unconfirmed state.
- Keep the original client ID across retries. Remove an item only after a matching server receipt and a completed deletion transaction.
- Short holds and Undo do not submit. Quick exit cancels preparation before saving starts; an already committed item stays queued. Exit is not cancellation of an alert already submitted.
- Automatic retry operates while a page is running or on reopening/foregrounding. Delivery while the app is closed or the OS suspends it is not guaranteed. No Background Sync implementation is claimed.
- “Service received” is not a responder acknowledgement, SMS delivery, or confirmation that help is coming.
- No startup GPS warm-up. Location requires an explicit per-alert choice and active server consent. If consent cannot be established, send without GPS. This intentionally means offline-created alerts may have no GPS.
- Capture actual device accuracy and position timestamp. Recheck consent before flushing older payloads. The backend remains the authority for disclosure and dispatch.
- Contact load/removal errors are visible, with no fake empty list or successful removal.
- Preserve the neutral Clear Sky identity, styles, and public-shell-only caching. Current manifest references only the existing regular icons; no maskable icon or root favicon is fabricated. Old cached references should disappear after the updated worker takes control and the page reloads.

## Checks

`python tests/stage2_pwa_browser.py` uses the existing isolated evaluation fixture and temporary browser contexts. It does not send SMS or access a real user database. It accelerates hold/countdown timers for automation; real timing still needs a phone check.

It covers cancelled holds/countdowns, transaction abort and unavailable storage, offline persistence after page close, lost-response idempotency, acknowledgement reaching the phone, measured GPS metadata, denied/revoked consent, consent changed while queued, quick exit before and after saving, invalid receipts, authentication rejection, contact form limits/masking/persistence, and contact read/removal failures.

Also run the existing Python suite, dashboard browser test, service-worker contract, and startup checks.

## Remaining release gates

This is evaluation software. The `demo-device` shared credential is not individual survivor authentication. Queued payloads can contain sensitive unencrypted data in browser storage. A local commit is not a guarantee against browser eviction, user clearing storage, device loss, or OS failure. Individual credentials, PIN/WebAuthn integration, an agreed local-data protection and retention design, HTTPS deployment checks, and real notification delivery verification remain separate work.

Manually check the Galaxy Note 9 / Android 10 using the installed app: actual hold timing, Undo, offline reopening, close/reopen queue recovery, quick exit/Back/app-switcher behaviour, and dashboard acknowledgement. Quick exit does not erase browser history or OS previews.
