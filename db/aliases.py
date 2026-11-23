"""Learned merchant/item names and their categories (`item_aliases`)."""
from psycopg import AsyncConnection


async def get_all(conn: AsyncConnection) -> dict[str, int]:
    """Every alias as name -> category_id."""
    cur = await conn.execute("SELECT name, category_id FROM item_aliases;")
    return {row["name"]: row["category_id"] for row in await cur.fetchall()}


async def find_category(conn: AsyncConnection, name: str) -> int | None:
    """The category of an exact alias name (case-sensitive, see #42), or None."""
    cur = await conn.execute("SELECT category_id FROM item_aliases WHERE name = %s;", (name,))
    row = await cur.fetchone()
    return row["category_id"] if row else None


async def learn(conn: AsyncConnection, alias_name: str, category_id: int, user_id: int) -> int:
    """
    Remember alias_name -> category_id (overwriting an existing alias, #37), then give that
    category to the user's uncategorized rows whose text contains the alias (substring, #44).
    Returns the number of rows categorized.
    """
    await conn.execute(
        """
        INSERT INTO item_aliases (name, category_id)
        VALUES (%s, %s)
        ON CONFLICT (name) DO UPDATE SET category_id = EXCLUDED.category_id;
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
