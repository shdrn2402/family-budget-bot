"""
Normalized description of a schema built from the system catalogs.

Two databases have the same schema when their snapshots are equal. Catalog
queries are used instead of pg_dump so the comparison doesn't depend on the
pg_dump client version or on object creation order.
"""
from typing import Any

import psycopg

SCHEMA = "budget"

_QUERIES: dict[str, str] = {
    "columns": """
        SELECT c.relname AS table_name, a.attnum AS position, a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS data_type, a.attnotnull AS not_null,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid AND c.relkind = 'r'
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %(schema)s
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attnum > 0 AND NOT a.attisdropped
        ORDER BY 1, 2
    """,
    "constraints": """
        SELECT c.relname AS table_name, k.conname, k.contype::text AS contype,
               pg_get_constraintdef(k.oid) AS definition
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %(schema)s
        WHERE k.contype <> 'n'
        ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes WHERE schemaname = %(schema)s
        ORDER BY 1, 2
    """,
    "sequences": """
        SELECT s.sequencename, s.data_type::text AS data_type, s.start_value, s.increment_by,
               s.min_value, s.max_value, s.cache_size, s.cycle,
               dep_table.relname AS owned_by_table, dep_col.attname AS owned_by_column
        FROM pg_sequences s
        JOIN pg_class seq ON seq.relname = s.sequencename
        JOIN pg_namespace n ON n.oid = seq.relnamespace AND n.nspname = s.schemaname
        LEFT JOIN pg_depend dep ON dep.objid = seq.oid AND dep.deptype = 'a'
        LEFT JOIN pg_class dep_table ON dep_table.oid = dep.refobjid
        LEFT JOIN pg_attribute dep_col ON dep_col.attrelid = dep.refobjid AND dep_col.attnum = dep.refobjsubid
        WHERE s.schemaname = %(schema)s
        ORDER BY 1
    """,
    "functions": """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args,
               pg_get_function_result(p.oid) AS result, l.lanname AS language, p.prosrc AS body
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace AND n.nspname = %(schema)s
        JOIN pg_language l ON l.oid = p.prolang
        ORDER BY 1, 2
    """,
    "triggers": """
        SELECT c.relname AS table_name, t.tgname, pg_get_triggerdef(t.oid) AS definition
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %(schema)s
        WHERE NOT t.tgisinternal
        ORDER BY 1, 2
    """,
}


def schema_snapshot(conn: psycopg.Connection, schema: str = SCHEMA) -> dict[str, list[tuple[Any, ...]]]:
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    with conn.cursor() as cur:
        for name, query in _QUERIES.items():
            cur.execute(query, {"schema": schema})
            snapshot[name] = [tuple(row) for row in cur.fetchall()]
    return snapshot
