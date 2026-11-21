import logging
import psycopg
from psycopg.rows import dict_row
from bot.config import Config

logger = logging.getLogger(__name__)

async def get_db_connection() -> psycopg.AsyncConnection:
    """
    Create and return an async connection to the PostgreSQL database.
    Uses dict_row to return results as dictionaries instead of tuples.
    """
    return await psycopg.AsyncConnection.connect(
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        row_factory=dict_row,
        options="-c search_path=budget,public"
    )

async def check_user_exists(user_id: int, conn: psycopg.AsyncConnection | None = None) -> bool:
    """Check if a user exists in the database."""
    try:
        connection = conn or await get_db_connection()
        # If conn was provided, we don't manage its lifecycle here (no `async with connection`)
        # But for simplicity, we manage cursor
        async with connection.cursor() as cur:
            await cur.execute("SELECT id FROM users WHERE id = %s;", (user_id,))
            result = await cur.fetchone()
            
        if conn is None:
            await connection.close()
            
        return result is not None
    except Exception as e:
        logger.error(f"Database error checking user {user_id}: {e}")
        return False

async def get_user_info(user_id: int, conn: psycopg.AsyncConnection | None = None) -> dict | None:
    """Get full user information including is_admin status."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute("SELECT id, name, is_admin FROM users WHERE id = %s;", (user_id,))
            result = await cur.fetchone()
            
        if conn is None:
            await connection.close()
            
        return result
    except Exception as e:
        logger.error(f"Database error getting user info for {user_id}: {e}")
        return None

async def register_user(user_id: int, name: str, is_admin: bool = False, conn: psycopg.AsyncConnection | None = None) -> bool:
    """
    Register a new user in the database.
    """
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute(
                "INSERT INTO users (id, name, is_admin) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                (user_id, name, is_admin)
            )
        await connection.commit()
        
        if conn is None:
            await connection.close()
            
        return True
    except Exception as e:
        logger.error(f"Database error registering user {user_id}: {e}")
        return False

async def get_recent_transactions(user_id: int, limit: int = 10, offset: int = 0, conn: psycopg.AsyncConnection | None = None) -> list:
    """
    Fetch transactions from the DB for a specific user with pagination support.
    """
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute(
                """
                SELECT 
                    t.id, 
                    t.description, 
                    t.amount, 
                    t.date, 
                    a.name as account_name
                FROM transactions t
                LEFT JOIN accounts a ON t.account_id = a.id
                WHERE t.user_id = %s
                ORDER BY t.date DESC
                LIMIT %s OFFSET %s;
                """,
                (user_id, limit, offset)
            )
            result = await cur.fetchall()
            
        if conn is None:
            await connection.close()
            
        return result
    except Exception as e:
        logger.error(f"Database error fetching transactions for user {user_id}: {e}")
        return []

async def get_transactions_count(user_id: int, conn: psycopg.AsyncConnection | None = None) -> int:
    """Return total number of transactions for a user."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute("SELECT COUNT(*) as count FROM transactions WHERE user_id = %s;", (user_id,))
            result = await cur.fetchone()
            
        if conn is None:
            await connection.close()
            
        return result['count'] if result else 0
    except Exception as e:
        logger.error(f"Database error counting transactions for user {user_id}: {e}")
        return 0
async def get_account_type(account_id: int, conn: psycopg.AsyncConnection | None = None) -> str | None:
    """Return the type of the account (e.g., 'card', 'cash')."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute("SELECT type FROM accounts WHERE id = %s;", (account_id,))
            result = await cur.fetchone()
            
        if conn is None:
            await connection.close()
            
        return result['type'] if result else None
    except Exception as e:
        logger.error(f"Database error getting account type for {account_id}: {e}")
        return None

async def _append_to_comment(cur: psycopg.AsyncCursor, transaction_id: int, text: str | None) -> bool:
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


async def save_transactions_bulk(user_id: int, transactions: list, conn: psycopg.AsyncConnection | None = None) -> int:
    """
    Save imported statement rows, reconciling them with existing rows.

    A row matches an existing one with the same amount, within ±3 days, that is either pending
    or comes from the other import source (Bit <-> card/bank statement):
    - existing row is pending (manual entry): it's confirmed with the imported details;
    - importing Bit, existing card/bank row: the counterparty is appended to its comment;
    - importing card/bank, existing Bit row: its external_id and source are taken over.
    Rows whose external_id is already stored are skipped as duplicates before any matching.
    Rows without a match are inserted.

    Returns the number of new or merged rows. On a database error the whole batch is rolled
    back and the error is raised (it used to be returned as 0, which looked like "duplicates").
    """
    connection = conn or await get_db_connection()
    try:
        inserted_count = 0

        # 1. Fetch all accounts and their owner_ids in one query
        account_owners = {}
        async with connection.cursor() as cur:
            await cur.execute("SELECT id, owner_id FROM accounts;")
            for row in await cur.fetchall():
                account_owners[row['id']] = row['owner_id']

        async with connection.cursor() as cur:
            for tx in transactions:
                # Already stored (e.g. a statement uploaded again): a duplicate. This must come before
                # matching, which could otherwise try to give another row this same external_id (#15).
                if tx.get('external_id'):
                    await cur.execute("SELECT 1 FROM transactions WHERE external_id = %s;", (tx['external_id'],))
                    if await cur.fetchone():
                        continue

                current_source = tx.get('source_type', 'import_xls')
                target_sources = ['import_xls'] if current_source == 'import_bit' else ['import_bit']

                # Find a pending manual entry or a row from the other import source (ignoring account_id)
                await cur.execute(
                    """
                    SELECT id, source_type, status FROM transactions
                    WHERE amount = %s
                      AND (status = 'pending' OR source_type = ANY(%s))
                      AND date BETWEEN %s::date - INTERVAL '3 days' AND %s::date + INTERVAL '3 days'
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (tx['amount'], target_sources, tx['date'], tx['date'])
                )
                match = await cur.fetchone()

                if match is None:
                    # Resolve user_id based on account owner
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

        await connection.commit()
        return inserted_count
    except Exception:
        logger.exception(f"Database error in bulk save for user {user_id}; rolling back the batch")
        try:
            await connection.rollback()
        except Exception:
            logger.warning("Rollback after a failed bulk save also failed", exc_info=True)
        raise
    finally:
        if conn is None:
            await connection.close()


async def get_user_card_account(user_id: int, conn: psycopg.AsyncConnection | None = None) -> dict | None:
    """The user's own card account (used for card-paid lines in their Bit export), or None."""
    connection = conn or await get_db_connection()
    try:
        async with connection.cursor() as cur:
            await cur.execute(
                "SELECT id, name FROM accounts WHERE owner_id = %s AND type = 'card' ORDER BY id LIMIT 1;",
                (user_id,),
            )
            return await cur.fetchone()
    finally:
        if conn is None:
            await connection.close()


async def get_latest_import_date(source_type, conn=None):
    """
    Returns the maximum date for a given source_type.
    Used to filter out old transactions before bulk insert.
    """
    connection = conn or await get_db_connection()
    try:
        async with connection.cursor() as cur:
            await cur.execute("SELECT MAX(date) FROM transactions WHERE source_type = %s;", (source_type,))
            row = await cur.fetchone()
            if row and row['max']:
                return row['max']
        return None
    except Exception as e:
        logger.error(f"Error fetching latest import date for {source_type}: {e}")
        return None
    finally:
        if conn is None:
            await connection.close()

async def sync_category_by_alias(alias_name, category_id, user_id, conn=None):
    """
    1. Adds/updates an alias in item_aliases (using composite alias_name).
    2. Updates all transactions with matching description+comment and NULL category.
    """
    connection = conn if conn else await get_db_connection()
    try:
        async with connection.cursor() as cur:
            # 1. Upsert into item_aliases
            await cur.execute("""
                INSERT INTO item_aliases (name, category_id)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET category_id = EXCLUDED.category_id;
            """, (alias_name.lower().strip(), category_id))
            
            # 2. Bulk update transactions
            # We match where the composite of description and comment ILIKE the alias_name
            await cur.execute("""
                UPDATE transactions
                SET category_id = %s
                WHERE user_id = %s 
                  AND category_id IS NULL
                  AND (
                      description ILIKE %s OR 
                      (description || ' ' || COALESCE(comment, '')) ILIKE %s
                  );
            """, (category_id, user_id, f"%{alias_name}%", f"%{alias_name}%"))
            
            updated_count = cur.rowcount
            await connection.commit()
            return updated_count
    finally:
        if conn is None:
            await connection.close()

async def get_all_item_aliases(conn: psycopg.AsyncConnection | None = None) -> dict[str, int]:
    """
    Fetches all item aliases from the database and returns them as a dictionary mapping name -> category_id.
    """
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute("SELECT name, category_id FROM item_aliases;")
            result = await cur.fetchall()
            
        if conn is None:
            await connection.close()
            
        # Ensure keys are upper case for robust matching if needed, 
        # though clean_business_name already makes them upper.
        return {row['name']: row['category_id'] for row in result}
    except Exception as e:
        logger.error(f"Database error fetching all item aliases: {e}")
        return {}


async def get_user_linked_account(user_id: int, conn: psycopg.AsyncConnection | None = None) -> dict | None:
    """Get the account currently linked to the user, if any."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute(
                "SELECT id, name, type FROM accounts WHERE owner_id = %s LIMIT 1;", 
                (user_id,)
            )
            result = await cur.fetchone()
        if conn is None:
            await connection.close()
        return result
    except Exception as e:
        logger.error(f"Error getting linked account for user {user_id}: {e}")
        return None

async def get_unlinked_accounts(conn: psycopg.AsyncConnection | None = None) -> list[dict]:
    """Get accounts that haven't been linked to a user yet."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute(
                "SELECT id, name FROM accounts WHERE owner_id IS NULL AND type = 'card' ORDER BY id;"
            )
            result = await cur.fetchall()
        if conn is None:
            await connection.close()
        return result
    except Exception as e:
        logger.error(f"Error getting unlinked accounts: {e}")
        return []

async def link_user_to_account(user_id: int, account_id: int, conn: psycopg.AsyncConnection | None = None) -> bool:
    """Link user to specified account, with concurrency safety."""
    try:
        connection = conn or await get_db_connection()
        async with connection.cursor() as cur:
            await cur.execute("SELECT owner_id FROM accounts WHERE id = %s FOR UPDATE;", (account_id,))
            res = await cur.fetchone()
            if res and res['owner_id'] is not None:
                return False # Already claimed
                
            await cur.execute(
                "UPDATE accounts SET owner_id = %s WHERE id = %s;", 
                (user_id, account_id)
            )
        await connection.commit()
        if conn is None:
            await connection.close()
        return True
    except Exception as e:
        logger.error(f"Error linking user {user_id} to account {account_id}: {e}")
        return False
