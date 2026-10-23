# Avenra

A survivor-facing PWA and role-based staff portal under development. Python/Flask
controllers, services and repositories live in `avenra/`; `app.py` remains the
Gunicorn compatibility entrypoint. Backend APIs for alerts, consents, diary and
referrals are present; the Stage 0 staff interface is an initial shell. Live alert
triage, evidence views and the audit browser are not completed interfaces.

This Stage 0 backend delivery is suitable for synthetic evaluation. It is not a
production security certification or a live emergency response service. See
`docs/STAGE0_STATUS.md` for remaining release gates.

## Start locally in Fish (CachyOS)

From the project directory, install the pinned dependencies:

```fish
cd ~/Desktop/Avenra
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install -r requirements-lock.txt
set -gx SECRET_KEY (python -c 'import secrets; print(secrets.token_urlsafe(48))')
```

Keep that terminal open: environment variables apply to it and its child processes.
The application does not load `.env` automatically.

For a **fictional evaluation**, choose a NEW database filename that has never held
real data. Existing unmarked databases are refused; do not delete an existing
database to get around that check.

```fish
set -gx APP_ENV evaluation
set -gx COOKIE_SECURE 0
set -gx DATABASE_PATH "$PWD/avenra-evaluation.sqlite3"
set -gx UPLOADS_DIR "$PWD/evaluation-uploads"
python -m flask --app app run --port 5050
```

Visit http://127.0.0.1:5050/evaluation for the Social worker and Shelter staff
role buttons. These are deliberately public demo access, restricted to a marked,
separate fictional database. There is no public admin shortcut or known staff
password. Both role logins are CSRF protected and audited.

Visit `/health` for the eight core table counts, or `/survivor/` for the existing
PWA. The first initialization creates 4 fictional profiles, 3 shelters, 2 contacts
and 3 consent records. Cape Town coordinates and capacity values are illustrative,
not verified support locations or partners. Notifications are disabled in the
evaluation app. Do not enter real information.

Restarting preserves records and deactivated accounts while the database exists.
A fresh empty evaluation database gets the initial fixtures. There is no startup
reset. These are different behaviours.

## Normal staff authentication

Use a different database path, set `APP_ENV=development` locally and
`COOKIE_SECURE=0` only for local HTTP. Normal startup initializes the schema but
does not seed accounts. Set the same secret and paths every time you restart.
Changing the secret signs out existing browsers.

For an existing database, stop the server and back it up/migrate before the first
startup with this version:

```fish
python migrate_staff_security.py
```

The migration saves a private SQLite backup. It preserves existing activation and
session versions; old accounts without activation columns become disabled.
Normal startup leaves an empty account table. The controlled, one-time web owner
setup and approved staff invitation workflow are **not implemented yet**. There
is no `bootstrap_admin.py` in this repository and no public administrator signup.
Use only the isolated fictional evaluation to review this checkpoint. Do not
manually insert a real-data administrator as a workaround for missing onboarding.

Use `/login` for email/password authentication. Sessions expire 15 minutes after
sign-in; polling does not extend them. Logout is a CSRF-protected POST and
invalidates all sessions for that account. Account disabling also takes effect
on subsequent requests.

## Test first

Add a failing test for the next behaviour, run it to verify the expected failure,
implement the smallest change, then run the targeted tests and full suite.

```fish
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/check_stage0.py
python -m pip check
```

The smoke check runs local Gunicorn with temporary data, checks startup guards,
role login and audit, then restarts to verify account state is preserved.
It sends no messages. No GitHub Actions workflow is currently configured.
This checkpoint was verified on Python 3.12. The JavaScript cache boundary tests
run with Node; the optional browser checks require a separate development install
of Playwright and its Chromium (not a production dependency):

```fish
node --test tests/pwa-shell.cjs
python tests/stage0_browser.py
```

Browser checks use temporary fictional data and start local Gunicorn. Mobile
viewport checks do not replace installation testing on a physical Android phone.

## Render deployment

No public URL has been deployed or verified for this delivery.

For a no-cost fictional hackathon preview, create a Render Blueprint from your
Git repository and set its Blueprint Path to `render.evaluation.yaml`.
Review its generated service settings, deploy, then record the actual Render URL
in `docs/STAGE0_STATUS.md`. Share `https://YOUR-ACTUAL-HOST/evaluation` with judges.
This free service sleeps when idle and uses ephemeral storage: data may disappear
on redeployment or replacement. It is unsuitable for emergencies or real records.

`render.yaml` is an alternative **paid persistent** profile, with the SQLite
database and uploads under `/var/data`. Review Render's current compute and disk
charges before deploying it. It enables HTTPS-only cookies, generates the secret,
and runs `gunicorn app:app --workers 1 --threads 4`. It does not seed real-data
accounts. Persistence does not replace tested backups, restore drills, encryption
requirements, access reviews or the outstanding security work.

Both profiles install `requirements-lock.txt`. `.python-version` selects the
latest Render-supported Python 3.12 patch. Keep `requirements.txt` and the lock file
identical when updating dependencies. Neither file contains package hashes.

References: [Blueprint specification](https://render.com/docs/blueprint-spec),
[Python versions](https://render.com/docs/python-version),
[free service limits](https://render.com/docs/free),
[persistent disks](https://render.com/docs/disks).

## Verify one SMS separately

Twilio is a provisional verification channel, not a confirmed production supplier.
The application webhook dispatcher is separate from this CLI; this test does not
enable Twilio delivery from dashboard alerts.

Default invocation is safe and offline:

```fish
python tools/sms_test.py
```

For an intentional, potentially billable test, configure your Twilio account,
a sender authorized for the destination and your own consenting South African
recipient. Enter values at prompts rather than pasting secrets into chat or
committing them:

```fish
read --prompt-str 'Twilio Account SID: ' --export TWILIO_ACCOUNT_SID
read --silent --prompt-str 'Twilio Auth Token: ' --export TWILIO_AUTH_TOKEN
read --prompt-str 'Sender (+countrycode): ' --export TWILIO_FROM_NUMBER
read --prompt-str 'Consenting recipient (+27...): ' --export TEST_RECIPIENT_PHONE
python tools/sms_test.py --send
```

This sends one fixed, neutral test message. It does not include names, locations,
case details or the product name. Do not repeat `--send` to check status: use
`python tools/sms_test.py --status SM...` with the returned Message SID.
An accepted, queued or sent status is not delivery. A provider `delivered` status
is not proof of reading; confirm actual receipt with your recipient.
Record the result without phone numbers, tokens or sensitive content in
`docs/STAGE0_STATUS.md`. Clear credentials afterward:

```fish
set -e TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_FROM_NUMBER TEST_RECIPIENT_PHONE
```

The tool restricts the provider URL to Twilio HTTPS, refuses redirects,
validates identifiers, limits response size, sanitizes errors and does not retry
a message creation request automatically. See
[Twilio message status documentation](https://www.twilio.com/docs/messaging/api/message-resource).

## Data handling limits

Do not commit databases, their WAL/journal files, evidence uploads, environment
files, credentials or private backups. SQLite file permissions are restricted on
POSIX systems; filesystem permissions alone are not encryption.
The public PWA shell contains no device credential and does not submit alerts.
Legacy backend device authentication still has a shared demonstration identity.
Individual enrolment, revocation, per-case API authorization and safe evidence
handling remain release blockers. See [Stage 0 status](docs/STAGE0_STATUS.md) and
[security requirements](docs/SECURITY_REQUIREMENTS.md) before working with real
survivor information.
