"""The ledger (`transactions`): manual entries, statement imports and edits."""
from datetime import date
from decimal import Decimal

from psycopg import AsyncConnection, AsyncCursor

from db import accounts

Amount = float | Decimal


# --- Reads ----------------------------------------------------------------------------

async def list_recent(conn: AsyncConnection, user_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    """The user's rows, newest first (id, description, amount, date, account_name)."""
    cur = await conn.execute(
        """
        SELECT t.id, t.description, t.amount, t.date, a.name AS account_name
        FROM transactions t
        LEFT JOIN accounts a ON t.account_id = a.id
        WHERE t.user_id = %s
        ORDER BY t.date DESC
        LIMIT %s OFFSET %s;
        """,
        (user_id, limit, offset),
    )
    return await cur.fetchall()


async def count(conn: AsyncConnection, user_id: int) -> int:
    cur = await conn.execute("SELECT COUNT(*) AS count FROM transactions WHERE user_id = %s;", (user_id,))
    row = await cur.fetchone()
    return row["count"] if row else 0


async def list_by_ids(conn: AsyncConnection, ids: list[int]) -> list[dict]:
    """The given rows (id, description, amount), by id."""
    cur = await conn.execute(
        "SELECT id, description, amount FROM transactions WHERE id = ANY(%s) ORDER BY id;", (ids,)
    )
    return await cur.fetchall()


async def get(conn: AsyncConnection, tx_id: int) -> dict | None:
    """One row (id, user_id, amount, description, comment, category_id), or None."""
    cur = await conn.execute(
        "SELECT id, user_id, amount, description, comment, category_id FROM transactions WHERE id = %s;",
        (tx_id,),
    )
    return await cur.fetchone()


async def list_uncategorized(conn: AsyncConnection) -> list[dict]:
    """Every row without a category, newest first (id, description, amount, date)."""
    cur = await conn.execute(
        "SELECT id, description, amount, date FROM transactions WHERE category_id IS NULL ORDER BY date DESC;"
    )
    return await cur.fetchall()


async def latest_date(conn: AsyncConnection, source_type: str) -> date | None:
    """The newest row date from one source (e.g. 'import_bit'), or None."""
    cur = await conn.execute("SELECT MAX(date) AS max FROM transactions WHERE source_type = %s;", (source_type,))
    row = await cur.fetchone()
    return row["max"] if row else None


# --- Edits ----------------------------------------------------------------------------

async def insert_manual(
    conn: AsyncConnection,
    *,
    user_id: int,
    account_id: int,
    category_id: int | None,
    amount: Amount,
    description: str,
    comment: str | None,
    day: str,
    source_type: str,
    status: str,
) -> int:
    """Insert a typed entry and return its id."""
    cur = await conn.execute(
        """
        INSERT INTO transactions (user_id, account_id, category_id, amount, description, comment, date, source_type, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s::date, %s, %s)
        RETURNING id;
        """,
        (user_id, account_id, category_id, amount, description, comment, day, source_type, status),
    )
    row = await cur.fetchone()
    return row["id"]


async def delete(conn: AsyncConnection, tx_id: int) -> None:
    await conn.execute("DELETE FROM transactions WHERE id = %s;", (tx_id,))


async def rename(conn: AsyncConnection, tx_id: int, description: str) -> None:
    await conn.execute("UPDATE transactions SET description = %s WHERE id = %s;", (description, tx_id))


async def set_amount(conn: AsyncConnection, tx_id: int, amount: Amount) -> None:
    await conn.execute("UPDATE transactions SET amount = %s WHERE id = %s;", (amount, tx_id))


async def set_category(conn: AsyncConnection, tx_id: int, category_id: int, amount: Amount) -> None:
    """Change the category, with the amount re-signed for it by the caller."""
    await conn.execute(
        "UPDATE transactions SET category_id = %s, amount = %s WHERE id = %s;", (category_id, amount, tx_id)
    )


# --- Statement import -------------------------------------------------------------------

async def _append_to_comment(cur: AsyncCursor, transaction_id: int, text: str | None) -> bool:
    """
    Append `text` to a transaction's comment unless it's already there.
    Compares literally (position(), not LIKE), so '%' and '_' in names are ordinary characters.
    Returns True if the comment changed.
    """
    text = (text or "").strip()
    if not text:
        return False
    await cur.execute(
        """
        UPDATE transactions
        SET comment = CASE WHEN comment IS NULL OR comment = '' THEN %s ELSE comment || ', ' || %s END
        WHERE id = %s AND (comment IS NULL OR position(%s IN comment) = 0);
        """,
        (text, text, transaction_id, text),
    )
    return cur.rowcount > 0


async def save_statement_rows(conn: AsyncConnection, user_id: int, rows: list[dict]) -> int:
    """
    Save imported statement rows, reconciling them with existing rows.

    A row matches an existing one on the same account, with the same amount, within ±3 days,
    that is either pending or comes from the other import source (Bit <-> card/bank statement).
    Exception: a pending entry on a transit account ("paid with Bit") may be confirmed by a Bit
    row on any account, and moves to that account. Among several candidates, a same-account row
    comes first, then the closest date, then the oldest row (#17). Then:
    - existing row is pending (manual entry): it's confirmed with the imported details;
    - importing Bit, existing card/bank row: the counterparty is appended to its comment;
    - importing card/bank, existing Bit row: its external_id and source are taken over.
    Rows whose external_id is already stored are skipped as duplicates before any matching.
    Rows without a match are inserted, owned by the account's owner (else by `user_id`).

    Returns the number of new or merged rows. The batch is atomic: on a database error nothing
    is saved and the error is raised. On a connection with no open transaction it commits.
    """
    inserted_count = 0
    async with conn.transaction():
        account_owners = await accounts.owners(conn)

        async with conn.cursor() as cur:
            for tx in rows:
                # Already stored (e.g. a statement uploaded again): a duplicate. This must come before
                # matching, which could otherwise try to give another row this same external_id (#15).
                if tx.get('external_id'):
                    await cur.execute("SELECT 1 FROM transactions WHERE external_id = %s;", (tx['external_id'],))
                    if await cur.fetchone():
                        continue

                current_source = tx.get('source_type', 'import_xls')
                target_sources = ['import_xls'] if current_source == 'import_bit' else ['import_bit']

                # Find a pending manual entry or a row from the other import source on the same
                # account, or a pending "paid with Bit" entry on transit for an incoming Bit row.
                await cur.execute(
                    """
                    SELECT id, source_type, status FROM transactions
                    WHERE amount = %s
                      AND (status = 'pending' OR source_type = ANY(%s))
                      AND date BETWEEN %s::date - INTERVAL '3 days' AND %s::date + INTERVAL '3 days'
                      AND (account_id = %s
                           OR (%s AND status = 'pending'
                               AND account_id IN (SELECT id FROM accounts WHERE type = 'transit')))
                    ORDER BY account_id <> %s, abs(date::date - %s::date), id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (tx['amount'], target_sources, tx['date'], tx['date'],
                     tx['account_id'], current_source == 'import_bit', tx['account_id'], tx['date'])
                )
                match = await cur.fetchone()

                if match is None:
                    tx_user_id = account_owners.get(tx['account_id'])
                    if tx_user_id is None:
                        tx_user_id = user_id

                    await cur.execute(
                        """
                        INSERT INTO transactions (user_id, account_id, category_id, amount, description, comment, date, external_id, source_type, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
                        ON CONFLICT (external_id) DO NOTHING;
                        """,
                        (
                            tx_user_id,
                            tx['account_id'],
                            tx.get('category_id'),
                            tx['amount'],
                            tx['description'],
                            tx.get('comment'),
                            tx['date'],
                            tx['external_id'],
                            current_source,
                        )
                    )
                    if cur.rowcount > 0:
                        inserted_count += 1

                elif match['status'] == 'pending':
                    # A manual entry waiting for a statement (card/bank or Bit): confirm it with the
                    # imported details. Its own text moves to the comment, followed by the imported
                    # comment (e.g. the Bit counterparty).
                    await cur.execute(
                        """
                        UPDATE transactions
                        SET status = 'confirmed',
                            external_id = %s,
                            date = %s,
                            source_type = %s,
                            account_id = %s,
                            comment = concat_ws(', ', description, NULLIF(comment, ''), NULLIF(%s, '')),
                            description = %s
                        WHERE id = %s;
                        """,
                        (tx['external_id'], tx['date'], current_source, tx['account_id'],
                         tx.get('comment'), tx['description'], match['id'])
                    )
                    inserted_count += 1

                elif current_source == 'import_bit':
                    # Bit row matching a card/bank row: keep the statement's external_id and only add
                    # the counterparty. If it's already there (re-import), it's a duplicate.
                    if await _append_to_comment(cur, match['id'], tx.get('comment')):
                        inserted_count += 1

                else:
                    # Card/bank row matching a Bit row: the statement is the source of truth, so take
                    # over external_id and source, and add the statement text to the comment.
                    description = (tx.get('description') or "").strip()
                    await cur.execute(
                        """
                        UPDATE transactions
                        SET external_id = %s,
                            source_type = 'import_xls',
                            comment = CASE
                                          WHEN comment IS NULL OR comment = '' THEN %s
                                          WHEN position(%s IN comment) > 0 THEN comment
                                          ELSE comment || ', ' || %s
                                      END
                        WHERE id = %s;
                        """,
                        (tx['external_id'], description, description, description, match['id'])
                    )
                    inserted_count += 1

    return inserted_count
