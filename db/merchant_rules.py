"""Merchant rules (`app.merchant_rules`) and name normalization (`app.merchant_names`)."""
from psycopg import AsyncConnection

from budget_core.categorize import MerchantName, MerchantRule

_RULE_ORDER = "ORDER BY priority, id"


async def get_rules(conn: AsyncConnection) -> list[MerchantRule]:
    """Every rule, in the order the categorizer tries them (priority, then the older rule; #65)."""
    cur = await conn.execute(
        "SELECT pattern, category_id, match_type, min_abs_amount, max_abs_amount "
        f"FROM app.merchant_rules {_RULE_ORDER};"
    )
    return [MerchantRule(r["pattern"], r["category_id"], r["match_type"], r["min_abs_amount"], r["max_abs_amount"])
            for r in await cur.fetchall()]


async def get_names(conn: AsyncConnection) -> list[MerchantName]:
    """Name normalization from app.merchant_names, in the order it's tried."""
    cur = await conn.execute(f"SELECT pattern, canonical_name FROM app.merchant_names {_RULE_ORDER};")
    return [MerchantName(r["pattern"], r["canonical_name"]) for r in await cur.fetchall()]


async def find_category(conn: AsyncConnection, name: str) -> int | None:
    """The category of a rule whose pattern equals `name` (case-sensitive, see #42), or None.

    Typed entries have no amount to compare, so rules with an amount band don't apply.
    """
    cur = await conn.execute(
        "SELECT category_id FROM app.merchant_rules WHERE pattern = %s AND match_type IN ('exact', 'legacy') "
        f"AND min_abs_amount IS NULL AND max_abs_amount IS NULL {_RULE_ORDER} LIMIT 1;",
        (name,),
    )
    row = await cur.fetchone()
    return row["category_id"] if row else None


async def learn(conn: AsyncConnection, alias_name: str, category_id: int, user_id: int) -> int:
    """
    Remember alias_name -> category_id (overwriting an existing rule, #37), then give that
    category to the user's uncategorized rows whose text contains the name (substring, #44).
    Returns the number of rows categorized.
    """
    await conn.execute(
        """
        INSERT INTO app.merchant_rules (pattern, category_id)
        VALUES (%s, %s)
        ON CONFLICT (pattern, min_abs_amount, max_abs_amount)
        DO UPDATE SET category_id = EXCLUDED.category_id, updated_at = now();
        """,
        (alias_name.lower().strip(), category_id),
    )
    cur = await conn.execute(
        """
        UPDATE transactions
        SET category_id = %s
        WHERE user_id = %s
          AND category_id IS NULL
          AND (description ILIKE %s OR (description || ' ' || COALESCE(comment, '')) ILIKE %s);
        """,
        (category_id, user_id, f"%{alias_name}%", f"%{alias_name}%"),
    )
    return cur.rowcount
