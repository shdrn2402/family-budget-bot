"""What happens to parsed statement lines before they are saved: categorization and
the offsetting rows for internal transfers.

The import handler and the scenario tests (tests/integration/test_scenarios.py) run the
same code. The rules, names and accounts come from the household data in the database.
"""
from collections.abc import Sequence

from budget_core.categorize import MerchantName, MerchantRule, categorize
from budget_core.household import AccountRoles

# Reference categories (the public category tree, scripts/seed_data.sql).
CASH_WITHDRAWAL_CATEGORY_ID = 43
INTERNAL_TRANSFER_CATEGORY_ID = 15


def prepare_statement_batch(
    transactions: list[dict],
    rules: Sequence[MerchantRule],
    names: Sequence[MerchantName],
    roles: AccountRoles,
) -> list[dict]:
    """
    Categorize parsed statement lines and add the offsetting rows for internal transfers.

    - Each line gets a `category_id` when the categorizer finds one (the dicts are updated in place).
    - A cash withdrawal also gets an offsetting row on the shared cash account, and an internal
      transfer one on the transit account: same line, opposite amount, external_id + "_offset".

    Returns the lines followed by the offsetting rows.
    """
    for tx in transactions:
        cat_id = categorize(tx['description'], tx['amount'], rules, names)
        if cat_id is not None:
            tx['category_id'] = cat_id

    offsetting_transactions = []
    for tx in transactions:
        cat_id = tx.get('category_id')
        if cat_id == CASH_WITHDRAWAL_CATEGORY_ID:
            offset_account = roles.require("shared_cash")
        elif cat_id == INTERNAL_TRANSFER_CATEGORY_ID:
            offset_account = roles.require("transit")
        else:
            continue
        offset_tx = tx.copy()
        offset_tx['amount'] = -tx['amount']
        offset_tx['account_id'] = offset_account
        offset_tx['external_id'] = f"{tx.get('external_id', '')}_offset"
        offsetting_transactions.append(offset_tx)

    return transactions + offsetting_transactions
