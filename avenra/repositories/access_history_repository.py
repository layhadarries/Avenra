"""Read-only, survivor-scoped access history."""
from avenra.repositories.base import BaseRepository


class AccessHistoryRepository(BaseRepository):
    def get_page(self, survivor_id, limit, before=None):
        query = """
            SELECT
                e.id,
                e.ts,
                e.action,
                u.name AS actor_name,
                u.role AS actor_role
            FROM audit_log e
            LEFT JOIN users u
                ON e.actor = 'user:' || CAST(u.id AS TEXT)
                AND u.role IN ('responder', 'admin', 'shelter')
            WHERE e.case_code = (
                SELECT case_code
                FROM users
                WHERE id = ? AND role = 'survivor'
            )
            AND e.action IN ('case_viewed', 'diary_viewed', 'diary_photo_viewed')
        """
        params = [survivor_id]

        if before is not None:
            timestamp, event_id = before
            query += """
                AND (
                    e.ts < ?
                    OR (e.ts = ? AND e.id < ?)
                )
            """
            params.extend([timestamp, timestamp, event_id])

        query += " ORDER BY e.ts DESC, e.id DESC LIMIT ?"
        params.append(limit)

        return self.conn.execute(query, params).fetchall()