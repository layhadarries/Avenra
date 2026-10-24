"""Audit log data access repository."""
from typing import Optional, List, Dict
from avenra.repositories.base import BaseRepository
from avenra.models.audit import AuditEntry
from avenra.config import Config


class AuditRepository(BaseRepository):
    """Encapsulates SQL operations on the audit_log table."""

    def log(
            self,
            actor: str,
            action: str,
            case_code: Optional[str] = None,
            detail: Optional[str] = None,
            *,
            commit: bool = True,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_log (actor, action, case_code, detail)
            VALUES (?, ?, ?, ?)
            """,
            (actor, action, case_code, detail),
        )

        if commit:
            self.conn.commit()

    def list_entries(self, case_code: Optional[str] = None, limit: int = 100) -> List[AuditEntry]:
        if case_code:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE case_code = ? ORDER BY ts DESC, id DESC LIMIT ?",
                (case_code, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AuditEntry.from_row(r) for r in rows]

    def table_counts(self) -> Dict[str, int]:
        return {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in Config.COUNT_TABLES
        }
