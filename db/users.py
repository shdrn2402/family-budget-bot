"""Bot users (`users`)."""
from psycopg import AsyncConnection


async def exists(conn: AsyncConnection, user_id: int) -> bool:
    cur = await conn.execute("SELECT id FROM users WHERE id = %s;", (user_id,))
    return await cur.fetchone() is not None


async def get(conn: AsyncConnection, user_id: int) -> dict | None:
    """id, name and is_admin, or None for an unknown user."""
    cur = await conn.execute("SELECT id, name, is_admin FROM users WHERE id = %s;", (user_id,))
    return await cur.fetchone()


async def register(conn: AsyncConnection, user_id: int, name: str, is_admin: bool = False) -> None:
    """Add a user. A user who already exists is left unchanged."""
    await conn.execute(
        "INSERT INTO users (id, name, is_admin) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
        (user_id, name, is_admin),
    )
