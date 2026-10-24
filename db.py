"""Database helpers. One place that opens SQLite and builds the tables."""
import os
import sqlite3
from pathlib import Path

from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Change the location with the DATABASE_PATH environment variable.
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "avenra.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def connect():
    """Open a new connection. Rows come back as dictionary-like objects."""
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if os.name == 'posix':
        path.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # nicer with several readers
    except sqlite3.DatabaseError:
        pass  # some file systems refuse WAL; the default mode still works
    return conn


def get_db():
    """One connection per request, closed automatically afterwards."""
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """Create every table from schema.sql. Safe to run on every startup."""
    conn = connect()
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())
        migrate(conn)
        conn.commit()
    finally:
        conn.close()


def migrate(conn):
    """Additive upgrades only. Never reset accounts or delete case records."""
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )''')
    have = {row['name'] for row in conn.execute('PRAGMA table_info(users)')}
    if 'is_active' not in have:
        conn.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1))')
    if 'auth_version' not in have:
        conn.execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1 CHECK(auth_version>=1)')
    conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)')
    # Fixed identifiers/definitions: no request or environment input enters SQL.
    additions = {'contacts': [('channel', "TEXT NOT NULL DEFAULT 'sms'"), ('chat_id', 'TEXT')],
                 'shelters': [('updated_at', 'TEXT')], 'alerts': [
            ('notify_status', "TEXT NOT NULL DEFAULT 'pending'"),
            ('notify_detail', 'TEXT'),
            ('location_accuracy', 'REAL'),
            ('location_recorded_at', 'TEXT'),
        ], 'diary_entries': [
            ('captured_at', 'TEXT'),
            ('received_at', 'TEXT'),
            ('note_sha256', 'TEXT'),
            ('photo_sha256', 'TEXT'),
            ('entry_fingerprint', 'TEXT'),
            ('contract_version', 'INTEGER NOT NULL DEFAULT 1'),
        ], "notification_outbox": [
            ("claim_token", "TEXT"), ("claimed_at", "TEXT"),
            ("provider_message_id", "TEXT"), ("reason_code", "TEXT"),
            ("completed_at", "TEXT"),
        ]}
    # Stage 2 completion migration: existing databases retain all records.
    for table, columns in additions.items():
        present = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
        for column, definition in columns:
            if column not in present:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_diary_user_client ON diary_entries(user_id, client_id)')
    from avenra.repositories.push_repository import SCHEMA
    # Fixed additive statements, without executescript committing the caller transaction.
    for statement in SCHEMA.split(';'):
        if statement.strip(): conn.execute(statement)
    conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)')
    conn.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)')
    conn.execute('''CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''')
