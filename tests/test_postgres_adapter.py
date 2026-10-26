"""SQL boundary tests never connect to production or use actual credentials."""
import unittest
from avenra.postgres import translate, Row

class PostgresAdapterTests(unittest.TestCase):
    def test_parameters_stay_bound_and_literals_are_preserved(self):
        result=translate("SELECT * FROM users WHERE email=? AND name='why?' AND org=?")
        self.assertEqual(result,"SELECT * FROM avenra.users WHERE email=%s AND name='why?' AND org=%s")
        self.assertNotIn("DROP TABLE",result)

    def test_case_grants_use_postgres_conflict_handling(self):
        self.assertEqual(translate('INSERT OR IGNORE INTO case_access(staff_id,survivor_id) VALUES(?,?)'),
                         'INSERT INTO avenra.case_access(staff_id,survivor_id) VALUES(%s,%s) ON CONFLICT DO NOTHING')

    def test_row_supports_existing_model_and_portal_contract(self):
        row=Row(id=12,name='Test')
        self.assertEqual(row[0],12)
        self.assertEqual(row['name'],'Test')
        self.assertEqual(tuple(row),(12,'Test'))
        self.assertEqual(dict(row),{'id':12,'name':'Test'})

    def test_time_and_text_functions_are_translated(self):
        result=translate("UPDATE push_invites SET used_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?")
        self.assertNotIn('strftime',result)
        self.assertIn('UPDATE avenra.push_invites',result)
        self.assertIn('avenra.instr(',translate('SELECT instr(name,?) FROM users'))

    def test_schema_qualified_insert_preserves_generated_id(self):
        from unittest.mock import Mock, patch, PropertyMock
        from avenra.postgres import Connection
        connection=object.__new__(Connection)
        connection.raw=Mock()
        connection.raw.execute.return_value.fetchone.return_value=(42,)
        with patch.object(Connection,'in_transaction',new_callable=PropertyMock,return_value=True):
            result=connection.execute('INSERT INTO alerts(user_id,case_code,client_id) VALUES(?,?,?)',(1,'Synthetic','unique'))
        self.assertEqual(result.lastrowid,42)
        sql,params=connection.raw.execute.call_args.args
        self.assertIn('INSERT INTO avenra.alerts',sql)
        self.assertTrue(sql.endswith('RETURNING id'))
        self.assertEqual(params,(1,'Synthetic','unique'))

    def test_device_tables_use_private_schema(self):
        for table in ('device_enrollments','survivor_devices','device_pairing_attempts'):
            self.assertIn('FROM avenra.'+table,translate('SELECT * FROM '+table+' WHERE token_hash=?'))

    def test_hosted_connections_require_verified_tls(self):
        from unittest.mock import patch,Mock
        from avenra.postgres import Connection
        with patch('psycopg.connect',return_value=Mock()) as connect:
            Connection('postgresql://synthetic.invalid/example')
        self.assertEqual(connect.call_args.kwargs['sslmode'],'verify-full')
        self.assertTrue(connect.call_args.kwargs['sslrootcert'])

    def test_error_mapping_retains_only_sqlstate_for_auth_diagnostics(self):
        import sqlite3
        import psycopg
        from unittest.mock import Mock
        from avenra.postgres import Connection
        connection = object.__new__(Connection)
        connection.raw = Mock()
        connection.raw.execute.side_effect = psycopg.errors.UndefinedColumn('synthetic-sensitive-database-detail')
        with self.assertRaises(sqlite3.OperationalError) as caught:
            connection.execute('SELECT missing FROM staff_mfa')
        self.assertEqual(getattr(caught.exception, 'sqlstate', None), '42703')
        self.assertNotIn('synthetic-sensitive', str(caught.exception))
