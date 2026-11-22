"""What happens to parsed statement lines before they are saved: categorization and
the offsetting rows for internal transfers.

Moved unchanged from bot/handlers/document.py, so the import handler and the scenario
tests (tests/integration/test_scenarios.py) run the same code.
"""

from bot.services.categorizer import auto_categorize

# Fixed IDs, as before; they move to configuration in a later Stage 1 step.
CASH_WITHDRAWAL_CATEGORY_ID = 43
INTERNAL_TRANSFER_CATEGORY_ID = 15
SHARED_CASH_ACCOUNT_ID = 4
TRANSIT_ACCOUNT_ID = 5


def prepare_statement_batch(transactions: list[dict], db_aliases: dict[str, int]) -> list[dict]:
    """
    Categorize parsed statement lines and add the offsetting rows for internal transfers.

    - Each line gets a `category_id` when the categorizer finds one (the dicts are updated in place).
    - A cash withdrawal also gets an offsetting row on the shared cash account, and an internal
      transfer one on the transit account: same line, opposite amount, external_id + "_offset".

    Returns the lines followed by the offsetting rows.
    """
    for tx in transactions:
        cat_id = auto_categorize(tx['description'], tx['amount'], db_aliases)
        if cat_id is not None:
            tx['category_id'] = cat_id

    offsetting_transactions = []
    for tx in transactions:
        cat_id = tx.get('category_id')
        if cat_id == CASH_WITHDRAWAL_CATEGORY_ID:
            offset_account = SHARED_CASH_ACCOUNT_ID
        elif cat_id == INTERNAL_TRANSFER_CATEGORY_ID:
            offset_account = TRANSIT_ACCOUNT_ID
        else:
            continue
        offset_tx = tx.copy()
        offset_tx['amount'] = -tx['amount']
        offset_tx['account_id'] = offset_account
        offset_tx['external_id'] = f"{tx.get('external_id', '')}_offset"
        offsetting_transactions.append(offset_tx)

    return transactions + offsetting_transactions
