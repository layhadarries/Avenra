# Stage 5 completion fixes

Base: db1b5ff (main). Fictional evaluation data only.

- Serialize orphan reconciliation with upload commits using BEGIN IMMEDIATE. Refuse caller-owned transactions; preserve their state.
- Replay compares the original persisted upload fingerprint, while the receipt reports current sharing. A delayed original upload cannot restore withdrawn sharing. Historical receipts keep legacy matching rules.
- Sharing no-ops do not create audit events.
- Bump public shell cache to v9. Keep waiting-worker activation behaviour; pending IndexedDB records are preserved.
- Register the diary shell on direct entry by supplying the status elements required by shell.js.
- Add actual service-worker-enabled airplane-mode save, close/reopen and reconnect acceptance to the Stage 5 browser suite.
- Add a 20-second upload timeout and bounded transient retry backoff. Ignore late entry-detail responses after closing the viewer.
- Display unknown receipt/capture timestamps truthfully.
- Background alert results update state without displacing More; Home explicitly restores the latest state.
- Correct the Stage 4 migration test to inspect the emptied legacy database, not the canonical database that intentionally retains the migrated records.

Regression tests: test_stage5_completion_regressions.py covers no-op auditing, original replay after withdrawal, caller transaction preservation, and cleanup waiting for an in-flight upload.

Physical Note 9 acceptance remains a manual gate: camera orientation/readability, offline close/reopen, reconnect receipt, share/unshare and global withdrawal, Quick Exit/Back/app-switch behaviour. Test with fictional records only.

Stage 6 retains individual device enrollment, reviewed encryption/unlock/recovery, staff MFA, hosted durable database/private storage, backup/restore, and laptop-off hosted acceptance. These fixes do not authorize real survivor data.
