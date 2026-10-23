"""Base repository for SQLite data access."""
import sqlite3
from typing import Optional
import db


class BaseRepository:
    """Base class providing database connection access."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        return db.get_db()
