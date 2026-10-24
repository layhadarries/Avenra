"""Record minimal, coalesced staff access denials."""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app

import db


class AccessDenialService:
    # Start with the two audit routes covered by these tests.
    # Expand only alongside tests for each additional boundary.
    ENDPOINTS = frozenset({
        "audit_log_page",
        "api_audit_log",
    })

    def record(self, user, endpoint, method):
        if (
            endpoint not in self.ENDPOINTS
            or user.role not in {"responder", "admin", "shelter"}
            or method not in {"GET", "HEAD", "OPTIONS"}
        ):
            return False

        actor = f"user:{user.id}"
        detail = (
            f"role={user.role}; "
            f"endpoint={endpoint}; "
            f"method={method}"
        )

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff = (now - timedelta(seconds=60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        conn = None

        try:
            # Separate connection: never commit another service's work.
            conn = db.connect()
            conn.execute("BEGIN IMMEDIATE")

            existing = conn.execute(
                """
                SELECT 1 FROM audit_log
                WHERE actor = ?
                  AND action = 'access_denied'
                  AND case_code IS NULL
                  AND detail = ?
                  AND ts > ?
                LIMIT 1
                """,
                (actor, detail, cutoff),
            ).fetchone()

            if existing is not None:
                conn.commit()
                return False

            conn.execute(
                """
                INSERT INTO audit_log
                    (actor, action, case_code, detail, ts)
                VALUES (?, 'access_denied', NULL, ?, ?)
                """,
                (actor, detail, timestamp),
            )
            conn.commit()
            return True

        except (sqlite3.Error, OSError):
            if conn is not None:
                conn.rollback()

            # Operational signal without exception text or request contents.
            current_app.logger.error(
                "Access-denial audit recording unavailable."
            )
            return False

        finally:
            if conn is not None:
                conn.close()