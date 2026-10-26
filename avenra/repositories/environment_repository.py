"""Database-wide fixture provenance; never relabel or rewrite historical rows."""
from avenra.repositories.base import BaseRepository


class EnvironmentRepository(BaseRepository):
    def contains_demo_data(self):
        # Include legacy seed databases created before the explicit marker existed.
        return bool(self.conn.execute(
            "SELECT 1 FROM app_metadata WHERE key='evaluation_fixture'"
        ).fetchone() or self.conn.execute(
            "SELECT 1 FROM users WHERE lower(email) LIKE ? LIMIT 1", ('%@avenra.demo',)
        ).fetchone())
