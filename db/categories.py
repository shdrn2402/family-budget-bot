"""The category tree (`categories`)."""
from psycopg import AsyncConnection


async def get_parent_id(conn: AsyncConnection, category_id: int) -> int | None:
    cur = await conn.execute("SELECT parent_id FROM categories WHERE id = %s;", (category_id,))
    row = await cur.fetchone()
    return row["parent_id"] if row else None


async def list_leaves(conn: AsyncConnection) -> list[dict]:
    """Categories without children (id, name, parent_name), grouped by parent."""
    cur = await conn.execute(
        """
        SELECT c.id, c.name, p.name AS parent_name
        FROM categories c
        JOIN categories p ON c.parent_id = p.id
        WHERE NOT EXISTS (SELECT 1 FROM categories sub WHERE sub.parent_id = c.id)
        ORDER BY p.id, c.id;
        """
    )
    return await cur.fetchall()
