"""Writes a validated household file (budget_core.household) to the database (#70).

Idempotent and additive, in the caller's transaction:
- users and accounts are upserted by id; an account's name, type and owner change only when the
  file gives them, while its card_last4 and role are always set as the file says (missing = none);
- account aliases and merchant rules from the file are upserted; others (e.g. learned rules) stay;
- merchant names belong to the file: it's the full, ordered list, and names not in it are removed.
"""
from collections import Counter

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from budget_core.household import Household


async def apply(conn: AsyncConnection, household: Household) -> Counter:
    """Write the household and return what changed, as counts (no values)."""
    counts: Counter = Counter()
    await _check_categories(conn, household)

    for user in household.users:
        await conn.execute(
            "INSERT INTO users (id, name, is_admin) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_admin = EXCLUDED.is_admin",
            (user.id, user.name, user.is_admin),
        )
        counts["users"] += 1

    # Free the roles and card digits the file assigns first, so they can move between accounts.
    roles = [a.role for a in household.accounts if a.role]
    digits = [a.card_last4 for a in household.accounts if a.card_last4]
    await conn.execute(
        "UPDATE accounts SET role = CASE WHEN role = ANY(%s) THEN NULL ELSE role END, "
        "card_last4 = CASE WHEN card_last4 = ANY(%s) THEN NULL ELSE card_last4 END "
        "WHERE role = ANY(%s) OR card_last4 = ANY(%s)",
        (roles, digits, roles, digits),
    )
    cur = await conn.execute("SELECT id FROM accounts WHERE id = ANY(%s)", ([a.id for a in household.accounts],))
    existing = {row["id"] for row in await cur.fetchall()}
    incomplete = [a.id for a in household.accounts if a.id not in existing and (a.name is None or a.type is None)]
    if incomplete:
        raise ValueError(f"new accounts need a name and a type: ids {incomplete}")

    for account in household.accounts:
        name = Jsonb(account.name) if account.name else None
        if account.id in existing:
            # A plain UPDATE: INSERT ... ON CONFLICT checks NOT NULL before it sees the conflict.
            await conn.execute(
                """
                UPDATE accounts SET
                    name = COALESCE(%s, name), type = COALESCE(%s, type), owner_id = COALESCE(%s, owner_id),
                    card_last4 = %s, role = %s
                WHERE id = %s
                """,
                (name, account.type, account.owner, account.card_last4, account.role, account.id),
            )
            counts["accounts updated"] += 1
        else:
            await conn.execute(
                "INSERT INTO accounts (id, name, type, owner_id, card_last4, role) VALUES (%s, %s, %s, %s, %s, %s)",
                (account.id, name, account.type, account.owner, account.card_last4, account.role),
            )
            counts["accounts added"] += 1
        for alias in account.aliases:
            await conn.execute(
                "INSERT INTO account_aliases (name, account_id) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET account_id = EXCLUDED.account_id",
                (alias, account.id),
            )
            counts["account aliases"] += 1
    if household.accounts:
        await conn.execute("SELECT setval('accounts_id_seq', (SELECT max(id) FROM accounts))")

    for rule in household.merchant_rules:
        cur = await conn.execute(
            """
            INSERT INTO app.merchant_rules (pattern, category_id, match_type, min_abs_amount, max_abs_amount, priority)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (pattern, min_abs_amount, max_abs_amount) DO UPDATE SET
                category_id = EXCLUDED.category_id, match_type = EXCLUDED.match_type,
                priority = EXCLUDED.priority, updated_at = now()
            WHERE (app.merchant_rules.category_id, app.merchant_rules.match_type, app.merchant_rules.priority)
                  IS DISTINCT FROM (EXCLUDED.category_id, EXCLUDED.match_type, EXCLUDED.priority)
            RETURNING (xmax = 0) AS inserted
            """,
            (rule.pattern, rule.category, rule.match_type, rule.min_abs_amount, rule.max_abs_amount, rule.priority),
        )
        row = await cur.fetchone()
        counts["merchant rules unchanged" if row is None else
               "merchant rules added" if row["inserted"] else "merchant rules updated"] += 1

    patterns = [n.pattern for n in household.merchant_names]
    cur = await conn.execute("DELETE FROM app.merchant_names WHERE NOT (pattern = ANY(%s))", (patterns,))
    counts["merchant names removed"] += cur.rowcount
    for position, name in enumerate(household.merchant_names):
        cur = await conn.execute(
            """
            INSERT INTO app.merchant_names (pattern, canonical_name, priority) VALUES (%s, %s, %s)
            ON CONFLICT (pattern) DO UPDATE SET
                canonical_name = EXCLUDED.canonical_name, priority = EXCLUDED.priority, updated_at = now()
            WHERE (app.merchant_names.canonical_name, app.merchant_names.priority)
                  IS DISTINCT FROM (EXCLUDED.canonical_name, EXCLUDED.priority)
            RETURNING (xmax = 0) AS inserted
            """,
            (name.pattern, name.canonical_name, position),
        )
        row = await cur.fetchone()
        counts["merchant names unchanged" if row is None else
               "merchant names added" if row["inserted"] else "merchant names updated"] += 1
    return counts


async def _check_categories(conn: AsyncConnection, household: Household) -> None:
    wanted = {r.category for r in household.merchant_rules}
    cur = await conn.execute("SELECT id FROM categories WHERE id = ANY(%s)", (list(wanted),))
    missing = wanted - {row["id"] for row in await cur.fetchall()}
    if missing:
        raise ValueError(f"merchant rules use unknown category ids: {sorted(missing)}")
