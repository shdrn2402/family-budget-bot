"""Accounts (`accounts`) and the words that name them in typed entries (`account_aliases`)."""
from psycopg import AsyncConnection


async def get_type(conn: AsyncConnection, account_id: int) -> str | None:
    """'card', 'cash', 'transit'…, or None for an unknown account."""
    cur = await conn.execute("SELECT type FROM accounts WHERE id = %s;", (account_id,))
    row = await cur.fetchone()
    return row["type"] if row else None


async def get_name(conn: AsyncConnection, account_id: int) -> dict | None:
    """The account's localized name ({'en': …, 'ru': …}), or None."""
    cur = await conn.execute("SELECT name FROM accounts WHERE id = %s;", (account_id,))
    row = await cur.fetchone()
    return row["name"] if row else None


async def owners(conn: AsyncConnection) -> dict[int, int | None]:
    """Every account's owner_id (None for shared accounts)."""
    cur = await conn.execute("SELECT id, owner_id FROM accounts;")
    return {row["id"]: row["owner_id"] for row in await cur.fetchall()}


async def find_owned_card(conn: AsyncConnection, user_id: int) -> dict | None:
    """The user's own card account (id, name), or None."""
    cur = await conn.execute(
        "SELECT id, name FROM accounts WHERE owner_id = %s AND type = 'card' ORDER BY id LIMIT 1;",
        (user_id,),
    )
    return await cur.fetchone()


async def find_linked(conn: AsyncConnection, user_id: int) -> dict | None:
    """Any account linked to the user (id, name, type), or None."""
    cur = await conn.execute("SELECT id, name, type FROM accounts WHERE owner_id = %s LIMIT 1;", (user_id,))
    return await cur.fetchone()


async def list_unlinked_cards(conn: AsyncConnection) -> list[dict]:
    """Card accounts no user has claimed yet (id, name)."""
    cur = await conn.execute("SELECT id, name FROM accounts WHERE owner_id IS NULL AND type = 'card' ORDER BY id;")
    return await cur.fetchall()


async def claim(conn: AsyncConnection, user_id: int, account_id: int) -> bool:
    """Link the account to the user. False if someone already owns it (the row is locked meanwhile)."""
    cur = await conn.execute("SELECT owner_id FROM accounts WHERE id = %s FOR UPDATE;", (account_id,))
    row = await cur.fetchone()
    if row and row["owner_id"] is not None:
        return False
    await conn.execute("UPDATE accounts SET owner_id = %s WHERE id = %s;", (user_id, account_id))
    return True


async def find_by_alias(conn: AsyncConnection, alias: str) -> int | None:
    """The account a typed word names (exact match on account_aliases.name), or None."""
    cur = await conn.execute("SELECT account_id FROM account_aliases WHERE name = %s;", (alias,))
    row = await cur.fetchone()
    return row["account_id"] if row else None
