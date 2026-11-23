"""Unit tests for bot.services.statement_batch.prepare_statement_batch (no database)."""

import pytest

from budget_core.categorize import MerchantRule
from budget_core.household import AccountRoles, HouseholdNotLoaded
from bot.services.statement_batch import (
    CASH_WITHDRAWAL_CATEGORY_ID,
    INTERNAL_TRANSFER_CATEGORY_ID,
    prepare_statement_batch,
)

SHARED_CASH_ACCOUNT_ID, TRANSIT_ACCOUNT_ID = 44, 55  # any ids: they come from the household data
ROLES = AccountRoles(by_role={"shared_cash": SHARED_CASH_ACCOUNT_ID, "transit": TRANSIT_ACCOUNT_ID})


def _rules(aliases: dict[str, int]) -> list[MerchantRule]:
    return [MerchantRule(pattern, category) for pattern, category in aliases.items()]


ALIASES = _rules(
    {"CAFE DEMO": 19, "MATRIX ATM'S": CASH_WITHDRAWAL_CATEGORY_ID, "BIT TOP UP": INTERNAL_TRANSFER_CATEGORY_ID}
)


def _line(description: str, amount: float, external_id: str = "x1", account_id: int = 1) -> dict:
    return {"description": description, "amount": amount, "external_id": external_id, "account_id": account_id}


def test_lines_are_categorized_and_unknown_ones_are_left_alone() -> None:
    known, unknown = _line("CAFE DEMO", -36, "c1"), _line("UNKNOWN PLACE", -15, "u1")

    batch = prepare_statement_batch([known, unknown], ALIASES, [], ROLES)

    assert batch == [known, unknown]
    assert known["category_id"] == 19
    assert "category_id" not in unknown


def test_cash_withdrawal_gets_an_offset_on_the_shared_cash_account() -> None:
    batch = prepare_statement_batch([_line("MATRIX ATM'S 4402", -500, "atm", account_id=3)], ALIASES, [], ROLES)

    assert [(tx["account_id"], tx["amount"], tx["external_id"]) for tx in batch] == [
        (3, -500, "atm"),
        (SHARED_CASH_ACCOUNT_ID, 500, "atm_offset"),
    ]
    assert batch[1]["category_id"] == CASH_WITHDRAWAL_CATEGORY_ID


def test_internal_transfer_gets_an_offset_on_the_transit_account_with_the_opposite_sign() -> None:
    batch = prepare_statement_batch([_line("BIT TOP UP", 70, "top")], ALIASES, [], ROLES)

    assert [(tx["account_id"], tx["amount"]) for tx in batch] == [(1, 70), (TRANSIT_ACCOUNT_ID, -70)]


def test_offsets_come_after_all_lines() -> None:
    lines = [_line("BIT TOP UP", -10, "a"), _line("CAFE DEMO", -5, "b")]

    batch = prepare_statement_batch(lines, ALIASES, [], ROLES)

    assert [tx["external_id"] for tx in batch] == ["a", "b", "a_offset"]


def test_current_behaviour_every_bit_transfer_gets_the_first_learned_counterparty_category() -> None:
    """#38: the inline menu learns 'description comment' aliases, but import categorization only
    looks at the description. Bit lines all say 'Transfer', and the partial match finds it inside
    the first learned alias, so transfers to anyone get that counterparty's category."""
    learned = _rules({"transfer dana cohen": 16, "transfer moshe levi": 19})  # as stored by the inline menu
    lines = [
        {"description": "Transfer", "comment": who, "amount": -80, "external_id": f"bit_{n}", "account_id": 5}
        for n, who in enumerate(["Dana Cohen", "Moshe Levi", "Someone New"])
    ]

    batch = prepare_statement_batch(lines, learned, [], ROLES)

    assert [tx["category_id"] for tx in batch] == [16, 16, 16]


def test_an_offset_needs_the_account_role_from_the_household_file() -> None:
    with pytest.raises(HouseholdNotLoaded, match="shared_cash"):
        prepare_statement_batch([_line("MATRIX ATM'S 4402", -500, "atm")], ALIASES, [], AccountRoles())
