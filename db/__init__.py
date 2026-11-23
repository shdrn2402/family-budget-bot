"""Database access: a connection pool and one repository module per table group.

Repositories are plain async functions that take a connection and never commit;
the caller owns the transaction (see db.pool). No imports from bot/ or telegram.
"""
