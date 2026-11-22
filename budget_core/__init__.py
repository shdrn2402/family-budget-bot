"""Pure domain layer of the family budget: typed records and statement parsers.

No Telegram, no database and no file I/O live here (tests/core/test_core_boundaries.py
checks it), so the same code runs in the bot and, from Stage 3, in the ingestion Lambda.
"""
