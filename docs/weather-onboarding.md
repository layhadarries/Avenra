# Weather entry and local screen unlock

Open `/survivor/cover.html`. Tap Thursday's forecast or hold the temperature to
open setup. New installations use the weather page as their manifest start URL.
The weather layout remains unchanged; only its hidden setup sheet is extended.

First-time setup supports either a confirmed four-digit PIN or WebAuthn platform
device verification, followed by optional name/nickname, two contact additions,
and optional location permission. More contacts can be managed inside the app.
No sample names or telephone numbers are prefilled for new accounts.

**This is a local screen disguise, not server authentication or encrypted storage.**
Direct support-page URLs remain accessible. Server APIs still require a paired
device cookie, case permissions and consent. A PIN, device key, installation,
public QR or preferred name cannot create or authenticate a survivor account.

PINs use salted PBKDF2-SHA256 (100,000 iterations) with a local attempt cooldown.
Legacy screen PINs migrate after successful entry. Four-digit PINs are low entropy;
browser-side cooldowns are bypassable and are not an account security boundary.

Device unlock uses WebAuthn ES256 platform credentials with required user presence
and verification. Fresh random challenges, origin, relying-party hash, verification
flags and assertion signatures are checked locally using Web Crypto. Only the
credential ID and public key are stored in this browser. No biometric templates
are requested, received or stored by Avenra. The browser/OS decides whether to use
fingerprint, face, device PIN or another supported verification method. Device
providers may manage or sync credentials under their own policies. HTTPS and a
compatible authenticator are needed; the PIN path works without WebAuthn.

Names and contact numbers remain in form memory until the user submits them to
the authenticated `/api/onboarding` endpoint. They are not saved in localStorage.
The server transaction preserves existing contact IDs and notification state,
normalises new numbers and makes repeated submissions idempotent. Partial failure
rolls back profile/contact changes. Audit details exclude names and numbers.
Unpaired/offline users can explicitly continue without saving account details;
this does not grant account access or imply contacts have been notified.

Checks: `node --test tests/local-unlock.cjs`,
`python -m unittest discover -s tests -p test_onboarding.py`, and
`python tests/weather_onboarding_browser.py`. The browser test uses a virtual
authenticator, **not** a physical fingerprint/Face ID acceptance test. Before
claiming phone support, verify registration, repeat unlock, cancellation, offline
PIN unlock and Quick Exit on the actual target devices.
