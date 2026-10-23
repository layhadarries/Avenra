"""Fictional evaluation/test fixtures, never real partner or survivor records.

Only prepare_evaluation_database is called at evaluation startup. Ordinary
startup never seeds accounts. Synthetic contacts cannot be overridden by env.
"""
import os
import secrets

from werkzeug.security import generate_password_hash

import db

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")
FIXTURE_EMAILS = frozenset({'survivor@safepath.demo', 'nomsa@safepath.demo',
                          'pieter@safepath.demo', 'admin@safepath.demo'})

# name, lat, lng, beds_total, beds_available, accepting, languages, hours, walk_ins, verified
SHELTERS = [
    ("Sunrise Shelter",           -33.9275, 18.4467, 20, 6, 1, "English, isiXhosa, Afrikaans", "08:00 – 20:00", 1, 1),
    ("Hope Centre",               -34.0489, 18.6226, 14, 3, 1, "English, isiXhosa",            "08:00 – 17:00", 1, 1),
    ("Community Health Clinic",   -34.0422, 18.6761,  0, 0, 1, "English, Afrikaans",           "07:30 – 16:30", 1, 1),
]

CONTACTS = [
    ("Lerato K", "+27 00 000 0001"),
    ("Thabo M", "+27 00 000 0002"),
]


def seed(password=None):
    """Insert demo data. Returns a small summary dictionary."""
    conn = db.connect()
    try:
        with conn:  # one transaction
            for s in SHELTERS:
                conn.execute(
                    """INSERT OR IGNORE INTO shelters
                       (name, lat, lng, beds_total, beds_available, accepting,
                        languages, hours, walk_ins, verified)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    s,
                )

            sunrise_id = conn.execute(
                "SELECT id FROM shelters WHERE name = ?", ("Sunrise Shelter",)
            ).fetchone()["id"]

            # name, role, email, org, case_code, shelter_id, can_sign_in
            users = [
                ("Thandi M (fictional)", "survivor", "survivor@safepath.demo", None,                 "SP-1042", None,       False),
                ("Nomsa D",         "responder", "nomsa@safepath.demo",    "Cape Town Responder Hub", None,      None,       True),
                ("Pieter V",        "shelter",   "pieter@safepath.demo",   "Sunrise Shelter",         None,      sunrise_id, True),
                ("Admin (demo)",    "admin",     "admin@safepath.demo",    "SafePath compliance",     None,      None,       True),
            ]
            for name, role, email, org, case_code, shelter_id, can_sign_in in users:
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE email = ?", (email,)
                ).fetchone()
                if exists:
                    continue  # skip hashing too, so restarts stay fast
                pw_hash = generate_password_hash(password or DEMO_PASSWORD, method='scrypt:32768:8:3') if can_sign_in else None
                conn.execute(
                    """INSERT INTO users
                       (name, role, email, password_hash, org, case_code, shelter_id)
                       VALUES (?,?,?,?,?,?,?)""",
                    (name, role, email, pw_hash, org, case_code, shelter_id),
                )

            survivor_id = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("survivor@safepath.demo",)
            ).fetchone()["id"]

            # Fictional demo access only. Real case grants are provisioned explicitly.
            conn.execute("""INSERT OR IGNORE INTO case_access(staff_id, survivor_id)
                            SELECT id, ? FROM users WHERE email IN
                            ('nomsa@safepath.demo','admin@safepath.demo')""", (survivor_id,))

            for name, phone in CONTACTS:
                conn.execute(
                    "INSERT OR IGNORE INTO contacts (user_id, name, phone) VALUES (?,?,?)",
                    (survivor_id, name, phone),
                )
                # Keep repeated test fixtures deterministic.
                conn.execute(
                    "UPDATE contacts SET phone = ? WHERE user_id = ? AND name = ?",
                    (phone, survivor_id, name),
                )

            default_consents = [
                ("location_sharing", "Cape Town Responder Hub"),
                ("diary_sharing", "Assigned Social Worker (Nomsa D)"),
                ("shelter_referral_sharing", "Verified Partner Shelters"),
            ]
            for item_key, granted_to in default_consents:
                has_item = conn.execute(
                    "SELECT 1 FROM consents WHERE user_id = ? AND item = ?",
                    (survivor_id, item_key),
                ).fetchone()
                if not has_item:
                    conn.execute(
                        "INSERT INTO consents (user_id, item, granted_to) VALUES (?, ?, ?)",
                        (survivor_id, item_key, granted_to),
                    )

        return {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "contacts": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            "shelters": conn.execute("SELECT COUNT(*) FROM shelters").fetchone()[0],
            "consents": conn.execute("SELECT COUNT(*) FROM consents").fetchone()[0],
        }
    finally:
        conn.close()


def is_evaluation_database(conn=None):
    """Explicit marker plus expected identities; never infer this from a filename."""
    owned = conn is None
    conn = conn or db.connect()
    try:
        marker = conn.execute("SELECT value FROM app_metadata WHERE key='evaluation_fixture'").fetchone()
        emails = {row['email'] for row in conn.execute('SELECT email FROM users')}
        return bool(marker and marker['value'] == 'avenra-stage0-v1' and emails == FIXTURE_EMAILS)
    finally:
        if owned:
            conn.close()


def prepare_evaluation_database():
    """Seed only an empty dedicated evaluation DB; preserve state on restarts."""
    conn = db.connect()
    try:
        if is_evaluation_database(conn):
            return
        counts = [conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('users', 'contacts', 'shelters', 'alerts', 'referrals',
                                'diary_entries', 'consents', 'audit_log')]
        if any(counts):
            raise RuntimeError('Evaluation refuses an existing unmarked database. Use a separate empty DATABASE_PATH.')
    finally:
        conn.close()
    # No fixed public password; evaluation role forms are limited to two staff roles.
    seed(password=secrets.token_urlsafe(48))
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE users SET is_active=1 WHERE role IN ('responder','shelter')")
            conn.execute("INSERT INTO app_metadata(key,value) VALUES ('evaluation_fixture','avenra-stage0-v1')")
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Create fictional data in a dedicated evaluation database only.')
    parser.add_argument('--evaluation', action='store_true')
    args = parser.parse_args()
    if not args.evaluation:
        parser.error('Explicit --evaluation is required. Never seed a real-data database.')
    db.init_db()
    prepare_evaluation_database()
    print('Synthetic evaluation database ready. Re-running preserves existing evaluation state.')
