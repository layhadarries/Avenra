"""Verify configured PostgreSQL connection, schema and login-facing queries."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if not os.environ.get('DATABASE_URL'):
    raise SystemExit('Source the private hosted runtime first.')
import db
from avenra.repositories.user_repository import UserRepository
from avenra.repositories.portal_repository import PortalRepository
from types import SimpleNamespace
with db.connect() as conn:
    if conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]!=9:
        raise SystemExit('Hosted schema upgrade required; no changes were made.')
    conn.execute('SELECT sms_opt_in FROM contacts LIMIT 0')
    user=UserRepository(conn).get_by_email('nonexistent-check@example.invalid')
    if user is not None:
        raise SystemExit('Reserved fictional probe identifier is not available; no changes were made.')
    portal=PortalRepository(conn)
    portal.cases(-1)
    portal.audit_page(SimpleNamespace(id=-1),{})
    portal.access_signature(SimpleNamespace(id=-1,role='admin',shelter_id=None))
print('PASS: hosted connection, schema, account lookup, case/audit queries and permission signature.')
