# Stage 4 combined integration checkpoint

This change reconciles main at deed00e with the already-tested backend and the
Stage 3/4 PWA screens. It does not add individual survivor enrolment or staff MFA.

## Behaviour

- Panic alerts wait for a committed IndexedDB write before claiming local storage.
- Only a matching server receipt moves an alert to the received state.
- Storage failures, rejected credentials and mismatched receipts preserve truthful states.
- The canonical cape-weather-queue is retained. Records from clear-sky-queue are
  copied before legacy removal. Interrupted migration can replay an idempotent ID;
  conflicting payloads under the same ID stop migration rather than silently overwrite.
- Quick exit preserves committed alerts and cancels unsaved preparation.
- Referral acceptance is separate from confirmed placement. Status polling continues
  after acceptance, and service names are rendered as text.
- Referral requests check current consent before returning an existing referral receipt.
- Privacy controls enable only after a valid current response. Lost save responses
  produce an unknown state requiring refresh, not a guessed rollback.
- Access history uses signed cursor pagination and safe actor/action fields.
- Private history and consent states clear on page hiding and are reloaded on return.
- Nearby help uses an explicit local location fix, defaults to 25 km, allows 50 km,
  sorts nearest first and never substitutes an unfiltered directory for a missing fix.
- Service availability always requires confirmation; bed counts and Full claims are absent.
- The public shell uses one weather identity. APIs and authorised requests bypass caching.
- Activation removes obsolete owned directory caches while preserving unrelated caches.
- Updates do not forcibly replace a service worker while an older app page is open.

## Automated checks

Run from the repository root:

```text
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/pwa-shell.cjs tests/service-worker-contract.cjs
python tests/stage2_pwa_browser.py
python tests/stage4_pwa_browser.py
python tests/stage4_audit_browser.py
python tests/stage3_case_browser.py
python tests/stage1_dashboard_browser.py
python tools/check_stage0.py
git diff --check
```

The new browser check uses a temporary Gunicorn database and fictional records.
It covers PWA-to-dashboard location withdrawal/restoration, diary/photo history,
referral consent, pagination, text-safe rendering, lost-save responses, stale view
clearing, both queue database names, radius filtering and public-only offline caches.

The three referral-retry unit tests reproduced the consent bypass before the fix.
The repaired source passed 237 unit tests, including 44 Stage 4 unit tests.
Both Node cache-contract files, the Stage 2 PWA and combined Stage 4 PWA browser
checks, the Stage 1 dashboard, Stage 3 case and Stage 4 audit browser checks,
and the Stage 0 startup check passed. Local verification used Python 3.12 and
Playwright 1.51; the team must repeat the checks on its Python 3.14 environment.

## Remaining deployment and device checks

Repeat the test suite on the team development environment. On the target phone,
close older app tabs before reopening so the new service worker can activate.
Verify privacy controls, navigation, quick exit and offline opening on Android 10.

The hardcoded device token remains a shared prototype credential. Tests are not a
production security certification. Keep public testing isolated to fictional data
and disabled outbound notification providers. See GOVERNANCE.md for release limits.
