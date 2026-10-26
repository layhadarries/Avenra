"""Demo activity uses a separate database, not an operational reporting filter."""
import os
from flask import current_app, has_app_context
from avenra.repositories.environment_repository import EnvironmentRepository


class EnvironmentIsolationService:
    def __init__(self, conn):
        self.repo = EnvironmentRepository(conn)

    @staticmethod
    def operational_runtime():
        return bool(os.environ.get('APP_ENV') == 'production' or os.environ.get('VERCEL')
                    or os.environ.get('DATABASE_URL') or
                    (has_app_context() and current_app.config.get('APP_ENV') == 'production'))

    def compatible(self):
        return not self.operational_runtime() or not self.repo.contains_demo_data()

    def require_compatible(self):
        if not self.compatible():
            raise RuntimeError('Operational runtime refuses a demo database; use separate infrastructure')
