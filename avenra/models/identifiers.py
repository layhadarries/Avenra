"""Shared database identifier and pagination limits (SQLite/Postgres bigint)."""
MAX_DATABASE_ID = 2**63 - 1
MAX_PAGE = 10000


def valid_identifier(value):
    return type(value) is int and 0 < value <= MAX_DATABASE_ID
