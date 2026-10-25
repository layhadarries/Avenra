# Vercel dashboard-only launch

Scope: staff login, empty assigned dashboard/case/referral/audit pages, invitations, activation and access controls. Survivor enrollment, diary file storage and notification dispatch are not part of this deployment checkpoint. No demo records are seeded.

Supabase project: bkurrdbqnmrpzmeqpdla, region eu-west-1. Tables live in the private `avenra` schema, not an exposed Data API schema. All tables have RLS enabled; public/anon/authenticated schema access is revoked. The Flask backend uses its private database credential and applies existing assignment/consent checks.

The schema file is `sql/001_dashboard_postgres.sql`. It has already been applied to the new empty project during preparation. `db.init_db()` verifies version 6 for Postgres; it does not reset records or run DDL on every function startup. SQLite remains the local-test backend. Vercel without DATABASE_URL refuses to use SQLite.

## Install and verify

Apply the Vercel upgrade patch after the combined dashboard-onboarding patch. Keep Vercel's local `.vercel` link and `.env.local` private.

```fish
source .venv/bin/activate.fish
pip install -r requirements.txt
python -m unittest discover -s tests -p test_postgres_adapter.py -v
python -m unittest discover -s tests -p test_staff_invitations.py -v
python tools/configure_vercel_dashboard.py
source ~/.local/share/avenra-hosted/runtime.fish
python tools/check_hosted_dashboard.py
```

The configure script asks for the database URI at a hidden prompt, saves a private matching CLI configuration outside Git, and adds SECRET_KEY/production settings to Vercel. DATABASE_URL must already exist in Vercel production. Never paste either database credentials or runtime.fish into chat. The script preserves existing configuration by refusing to overwrite it. Do not regenerate the secret on every deploy.

`check_hosted_dashboard.py` is the required application-to-Postgres verification. It must pass before deployment. Local SQLite tests and SQL execution through the Supabase management tool do not substitute for that check.

## Deploy local checkout

```fish
npx vercel@latest deploy --prod
```

This uploads the local checkout, including the uncommitted upgrade, without requiring automatic GitHub integration. The build copies public static assets into public/static; templates and application stay in the Python service. The private database and uploads in the local checkout are excluded via .vercelignore.

Open the returned production URL at `/login`. Verify HTTPS, a rendered login page/assets, `/evaluation` -> 404, signed-out `/api/alerts` -> 401, and secure HttpOnly session cookies. There is no default login account. A successful build alone does not establish working runtime/database access.

## Email and first account

After obtaining the stable production URL:

```fish
python tools/configure_staff_mail.py
source ~/.local/share/avenra-hosted/runtime.fish
python -m flask --app app staff-invite --email REAL_ADDRESS --name 'Actual person' --role admin --org 'Actual organisation'
```

The mail helper detects the hosted CLI runtime and adds PUBLIC_BASE_URL and SMTP settings there. SMTP delivery runs synchronously from the operator CLI, using the hosted database. It does not require a background worker on the developer laptop after the invitation is sent. Credentials for the CLI must point to the same database as Vercel. Add these email settings to Vercel only if future server-side invitation sending is added; the current runtime activation page does not send mail.

Click the actual received invitation, create a password, enter the dashboard, sign out, and sign in normally. Verify intended case/shelter scope and the disabled account/session path. Invite responders with --case-code only when actual cases exist, and shelter users with a real --shelter-id. No fictional grants are added automatically.

## Implementation and security boundaries

The Postgres adapter keeps values parameterized, uses schema-qualified application tables for transaction-pooler compatibility, disables prepared statements, requires TLS for hosted connections and preserves explicit transaction ownership. SQLite BEGIN IMMEDIATE maps to a transaction-scoped advisory writer lock to preserve existing service concurrency semantics. Context-managed writes commit/roll back; teardown closes connections.

Runtime database credentials remain server-side. A dedicated least-privilege database role should replace the initial setup credential before a real-data pilot. Client encryption/recovery, individual survivor identity, staff MFA, password recovery and independent security verification remain pilot gates. Do not upload real incident data into this demo dashboard.

Postgres schema execution and SQL syntax were checked using the Supabase management connection. Full connection and deployed acceptance remain pending until the operator runs the checks above with the privately configured DATABASE_URL. No production deployment is claimed by this document.
