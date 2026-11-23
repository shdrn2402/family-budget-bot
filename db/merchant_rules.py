"""Merchant and typed-item names and their categories (`app.merchant_rules`)."""
from psycopg import AsyncConnection


async def get_all(conn: AsyncConnection) -> dict[str, int]:
    """Every rule as pattern -> category_id."""
    cur = await conn.execute("SELECT pattern, category_id FROM app.merchant_rules;")
    return {row["pattern"]: row["category_id"] for row in await cur.fetchall()}


async def find_category(conn: AsyncConnection, name: str) -> int | None:
    """The category of a rule whose pattern equals `name` (case-sensitive, see #42), or None."""
    cur = await conn.execute("SELECT category_id FROM app.merchant_rules WHERE pattern = %s;", (name,))
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
        ON CONFLICT (pattern) DO UPDATE SET category_id = EXCLUDED.category_id, updated_at = now();
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
