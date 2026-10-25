# Dashboard onboarding and demo-data transition

This package includes normal staff sign-in, email invitation/password activation, developer CLI provisioning for admins/responders/shelter staff, explicit case/shelter assignments, and account disabling. It does not require a developer frontend.

## Demo cleanup plan

1. Do not truncate tables, delete avenra.db, or reset accounts on startup.
2. `python tools/prepare_dashboard.py` creates a separate private runtime at ~/.local/share/avenra-dashboard. If the repository's avenra.db exists, it first takes a SQLite backup including committed WAL data. If you used another database, pass its path with --source-db. Original databases and original upload files remain untouched.
3. The new dashboard.sqlite3 gets schema/migrations only. Core business tables must be empty before configuration is written. Evaluation seeding is never called. Re-running preserves an existing runtime and its new accounts.
4. Source runtime.fish in each terminal that runs the server or provisioning commands. It has a persistent private secret and the exact database/upload paths, outside Git. Never print, copy, commit, or attach this file.
5. Invite actual staff into this runtime after SMTP and the public HTTPS origin are configured. No demo accounts, case records or shelters are copied. Explicitly add real service/case records through the reviewed workflows when ready.
6. Keep synthetic fixtures in automated tests. `/evaluation` is disabled in this normal runtime. Normal startup remains empty unless an operator adds data.
7. Retain the old database and uploads until the transition is verified. Any later deletion is a separate deliberate operation; this package performs no deletion.

## Local commands (Fish)

After pulling and applying the combined patch:

```fish
source .venv/bin/activate.fish
python -m unittest discover -s tests -p test_staff_invitations.py -v
python tests/staff_invitation_browser.py
python tools/prepare_dashboard.py
source ~/.local/share/avenra-dashboard/runtime.fish
python -m flask --app app run --host 127.0.0.1 --port 5050
```

Open http://localhost:5050/login. There are deliberately no pre-created staff credentials. An empty login page is expected until the first invited account activates.

## Email and first administrator

The dashboard is not hosted yet. First establish a stable HTTPS origin and the persistent hosted database/storage. Localhost invitation links cannot onboard another person independently of your laptop. Transfer provisioning configuration deliberately to the host; do not accidentally invite into the local database while running the website against a different database.

Once the public URL and SMTP account exist, run `python tools/configure_staff_mail.py` to enter configuration privately for the local runtime. SMTP acceptance is not proof of inbox delivery. See staff-email-invitations.md for host environment settings.

```fish
source ~/.local/share/avenra-dashboard/runtime.fish
python -m flask --app app staff-invite --email person@example.org --name 'Person name' --role admin --org 'Organisation name'
```

Use the recipient's actual details. The email link opens password creation, then signs the person into the dashboard. Later sign-ins use /login. Add responders with --role responder and explicit --case-code grants; shelter users require --role shelter and --shelter-id. Administrators do not automatically receive access to every case. Provisioning remains operator CLI only; delegated administrator invitation management, MFA and password recovery are not implemented by this package.

## Survivor integration dependency

No fake survivor is retained in the clean dashboard database. The current PWA device token resolves the seeded evaluation survivor, so individual survivor enrollment remains a required Stage 6 integration step. Keep the isolated evaluation runtime for fictional PWA testing until enrollment is implemented. Do not restore a hidden demo account to bypass enrollment.

Production activation email delivery, public HTTPS routing, durable hosted storage, real-data identity/encryption/MFA gates and multi-device acceptance remain separate verification steps. This package does not claim the public deployment already exists.
