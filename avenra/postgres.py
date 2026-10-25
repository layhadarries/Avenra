"""Postgres persistence boundary for existing parameterized repositories.

Preserves SQLite's explicit transaction/row contract while local tests use SQLite.
Only application-owned SQL is translated; parameter values are never interpolated.
"""
import re
import sqlite3

TABLES = frozenset(('device_pairing_attempts','device_enrollments','survivor_devices','schema_migrations','app_metadata','staff_activation_attempts','case_access','alert_workflow','notification_batches','push_acknowledgements'))
IDENTITY_TABLES = frozenset(('users','shelters','contacts','alerts','referrals','diary_entries',
    'consents','audit_log','alert_history','notification_outbox','push_invites','push_subscriptions','staff_invitations'))
NOW = "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
DAY = "to_char((CURRENT_TIMESTAMP + interval '1 day') AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"


def translate(sql):
    sql = sql.replace("strftime('%Y-%m-%dT%H:%M:%SZ','now','+1 day')",DAY)
    sql = sql.replace("strftime('%Y-%m-%dT%H:%M:%SZ','now')",NOW)
    sql = sql.replace('MAX(0, beds_available - 1)','GREATEST(0, beds_available - 1)')
    ignore = re.match(r'\s*INSERT\s+OR\s+IGNORE\s+',sql,re.I)
    if ignore:
        sql = re.sub(r'INSERT\s+OR\s+IGNORE','INSERT',sql,count=1,flags=re.I).rstrip().rstrip(';')
        sql += ' ON CONFLICT DO NOTHING'
    # Preserve question marks inside quoted literals/identifiers. SQL is static,
    # and all request values remain separately bound by psycopg.
    tokens = re.split(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")",sql)
    def fragment(token):
        token=token.replace('?', '%s')
        token=re.sub(r'\binstr\s*\(', 'avenra.instr(', token, flags=re.I)
        return re.sub(r'(?<![.\w])([a-z_]+)\b', lambda m: 'avenra.'+m[1] if m[1].lower() in TABLES | IDENTITY_TABLES else m[0], token, flags=re.I)
    return ''.join(token if index%2 else fragment(token) for index,token in enumerate(tokens))


class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)
    def __iter__(self):
        return iter(self.values())


class Cursor:
    def __init__(self,cursor,lastrowid=None):
        self.cursor=cursor
        self.lastrowid=lastrowid
    @property
    def rowcount(self): return self.cursor.rowcount
    def _row(self,values):
        return None if values is None else Row(zip((col.name for col in self.cursor.description),values))
    def fetchone(self): return self._row(self.cursor.fetchone())
    def fetchall(self): return [self._row(row) for row in self.cursor.fetchall()]
    def __iter__(self):
        while True:
            row=self.fetchone()
            if row is None: break
            yield row


class Connection:
    def __init__(self,url):
        import psycopg
        try:
            self.raw=psycopg.connect(url,autocommit=True,prepare_threshold=None,connect_timeout=10,
                sslmode='require')
            self.raw.execute("SET statement_timeout = '15s'")
            self.raw.execute("SET lock_timeout = '10s'")
        except psycopg.Error:
            raise sqlite3.OperationalError('Hosted database connection unavailable') from None
    @property
    def in_transaction(self):
        from psycopg.pq import TransactionStatus
        return self.raw.info.transaction_status != TransactionStatus.IDLE
    def execute(self,sql,params=()):
        import psycopg
        try:
            if sql.strip().upper() in ('BEGIN IMMEDIATE','BEGIN'):
                cur=self.raw.execute('BEGIN')
                # Match the single-writer guarantees relied on by existing services.
                self.raw.execute('SELECT pg_advisory_xact_lock(724301915)')
                return Cursor(cur)
            pragma=re.fullmatch(r'\s*PRAGMA table_info\(([a-z_]+)\)\s*',sql,re.I)
            if pragma:
                cur=self.raw.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_schema='avenra' AND table_name=%s ORDER BY ordinal_position",(pragma[1],))
                return Cursor(cur)
            translated=translate(sql).rstrip().rstrip(';')
            mutation=re.match(r'\s*(INSERT|UPDATE|DELETE)\b',translated,re.I)
            if mutation and not self.in_transaction:
                self.execute('BEGIN IMMEDIATE')
            match=re.match(r'\s*INSERT\s+INTO\s+(?:avenra\.)?([a-z_]+)\b',translated,re.I)
            return_id=match and match[1].lower() in IDENTITY_TABLES and not re.search(r'\bRETURNING\b',translated,re.I)
            if return_id: translated += ' RETURNING id'
            # Psycopg processes percent markers only when parameters are supplied.
            cur=self.raw.execute(translated,params if params else None)
            last_id=None
            if return_id:
                row=cur.fetchone();last_id=row[0] if row else None
            return Cursor(cur,last_id)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError('Database constraint violation') from None
        except psycopg.Error as error:
            import logging
            logging.getLogger(__name__).error('Hosted database operation failed (SQLSTATE %s)',error.sqlstate)
            raise sqlite3.OperationalError('Hosted database operation failed') from None
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()
    def __enter__(self): return self
    def __exit__(self,kind,value,tb):
        if kind: self.rollback()
        else: self.commit()
