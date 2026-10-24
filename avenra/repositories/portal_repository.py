"""Read models and transactional workflow persistence for the staff portal."""
from avenra.repositories.base import BaseRepository


class PortalRepository(BaseRepository):
    def alert_page(self, staff_id, filters):
        clauses = ['EXISTS (SELECT 1 FROM case_access c WHERE c.staff_id=? AND c.survivor_id=a.user_id)']
        params = [staff_id]
        for key, expression in [('status', 'a.status=?'), ('assignee', 'w.assigned_to=?'),
                                ('since', 'a.created_at>=?'), ('until', 'a.created_at<?'),
                                ('snapshot', 'a.id<=?')]:
            if filters.get(key):
                clauses.append(expression)
                params.append(filters[key])
        if filters.get('q'):
            clauses.append("instr(lower(a.case_code), lower(?)) > 0")
            params.append(filters['q'])
        where = ' AND '.join(clauses)
        source = ' FROM alerts a LEFT JOIN alert_workflow w ON w.alert_id=a.id '
        total = self.conn.execute('SELECT COUNT(*)' + source + 'WHERE ' + where, params).fetchone()[0]
        rows = self.conn.execute(
            '''SELECT a.*, w.assigned_to, w.escalated_at, COALESCE(w.revision,0) AS revision,
                      u.name AS assigned_name''' + source +
            'LEFT JOIN users u ON u.id=w.assigned_to WHERE ' + where +
            ' ORDER BY a.id DESC LIMIT ? OFFSET ?',
            [*params, filters['per_page'], (filters['page']-1)*filters['per_page']],
        ).fetchall()
        return rows, total

    def cases(self, staff_id):
        return self.conn.execute(
            '''SELECT u.case_code, COUNT(a.id) AS alert_count, MAX(a.created_at) AS last_alert
               FROM users u JOIN case_access c ON c.survivor_id=u.id
               LEFT JOIN alerts a ON a.user_id=u.id
               WHERE c.staff_id=? AND u.role='survivor'
               GROUP BY u.id ORDER BY last_alert DESC, u.case_code''', (staff_id,)).fetchall()

    def workflow(self, alert_id):
        row = self.conn.execute(
            '''SELECT assigned_to, escalated_at, revision FROM alert_workflow WHERE alert_id=?''',
            (alert_id,)).fetchone()
        return dict(row) if row else {'assigned_to': None, 'escalated_at': None, 'revision': 0}

    def history(self, alert_id):
        return [dict(row) for row in self.conn.execute(
            '''SELECT h.id, h.action, h.detail, h.created_at, u.name AS actor
               FROM alert_history h LEFT JOIN users u ON u.id=h.actor_id
               WHERE h.alert_id=? ORDER BY h.id''', (alert_id,))]

    def record(self, alert_id, actor_id, action, detail=''):
        self.conn.execute(
            'INSERT INTO alert_history(alert_id,actor_id,action,detail) VALUES (?,?,?,?)',
            (alert_id, actor_id, action, detail))

    def update_workflow(self, alert_id, assigned_to, escalated_at):
        self.conn.execute(
            '''INSERT INTO alert_workflow(alert_id,assigned_to,escalated_at,revision) VALUES (?,?,?,1)
               ON CONFLICT(alert_id) DO UPDATE SET assigned_to=excluded.assigned_to,
               escalated_at=excluded.escalated_at, revision=alert_workflow.revision+1''',
            (alert_id, assigned_to, escalated_at))

    def case_rows(self, survivor_id):
        return self.conn.execute('SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC', (survivor_id,)).fetchall()

    def audit_page(self, user, args):
        page = max(1, int(args.get('page', 1)))
        limit = min(100, max(1, int(args.get('limit', 50))))
        query = ''' FROM audit_log e WHERE (EXISTS (
                   SELECT 1 FROM users s JOIN case_access c ON c.survivor_id=s.id
                   WHERE s.case_code=e.case_code AND c.staff_id=?)'''
        params = [user.id]
        query += " OR (e.case_code IS NULL AND e.actor=?))"
        params.append(f'user:{user.id}')
        case_code = args.get("case_code", "").strip().upper()
        if len(case_code) > 80:
            raise ValueError("Invalid case filter")

        if case_code:
            query += "AND e.case_code = ?"
            params.append(case_code)

        if args.get('q'):
            query += " AND instr(lower(e.actor || ' ' || COALESCE(e.case_code,'') || ' ' || COALESCE(e.detail,'')),lower(?))>0"
            params.append(args['q'][:80])
        category = args.get('category')
        prefixes = {'alert': ('alert', 'contact'), 'referral': ('referral', 'shelter'),
                    'consent': ('consent',), 'diary': ('diary',), 'access': ('login', 'logout', 'case', 'user', 'admin')}
        if category in prefixes:
            query += ' AND (' + ' OR '.join('e.action LIKE ?' for _ in prefixes[category]) + ')'
            params.extend(p + '%' for p in prefixes[category])
        total = self.conn.execute('SELECT COUNT(*)' + query, params).fetchone()[0]
        rows = self.conn.execute('SELECT e.*' + query + ' ORDER BY e.id DESC LIMIT ? OFFSET ?',
                                 [*params, limit, (page-1)*limit]).fetchall()
        return {'events': [dict(r) for r in rows], 'page': page, 'total': total,
                'has_next': page * limit < total}

    def access_signature(self, user):
        """Change marker only, never a client-side authorization credential."""
        import hashlib
        rows = self.conn.execute(
            '''SELECT c.survivor_id, co.id, co.item, co.granted_at, co.revoked_at
               FROM case_access c LEFT JOIN consents co ON co.user_id=c.survivor_id
               WHERE c.staff_id=? ORDER BY c.survivor_id,co.id''', (user.id,)).fetchall()
        if user.role == 'shelter':
            rows = self.conn.execute(
                '''SELECT co.id, co.revoked_at FROM referrals r JOIN alerts a ON a.id=r.alert_id
                   JOIN consents co ON co.user_id=a.user_id WHERE r.shelter_id=? ORDER BY co.id''',
                (user.shelter_id,)).fetchall()
        return hashlib.sha256(repr(([tuple(r) for r in rows], user.role, user.shelter_id)).encode()).hexdigest()
