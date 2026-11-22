"""Unit tests for bot.services.statement_batch.prepare_statement_batch (no database)."""

from bot.services.statement_batch import (
    CASH_WITHDRAWAL_CATEGORY_ID,
    INTERNAL_TRANSFER_CATEGORY_ID,
    SHARED_CASH_ACCOUNT_ID,
    TRANSIT_ACCOUNT_ID,
    prepare_statement_batch,
)

ALIASES = {"CAFE DEMO": 19, "MATRIX ATM'S": CASH_WITHDRAWAL_CATEGORY_ID, "BIT TOP UP": INTERNAL_TRANSFER_CATEGORY_ID}


def _line(description: str, amount: float, external_id: str = "x1", account_id: int = 1) -> dict:
    return {"description": description, "amount": amount, "external_id": external_id, "account_id": account_id}


def test_lines_are_categorized_and_unknown_ones_are_left_alone() -> None:
    known, unknown = _line("CAFE DEMO", -36, "c1"), _line("UNKNOWN PLACE", -15, "u1")

    batch = prepare_statement_batch([known, unknown], ALIASES)

    assert batch == [known, unknown]
    assert known["category_id"] == 19
    assert "category_id" not in unknown


def test_cash_withdrawal_gets_an_offset_on_the_shared_cash_account() -> None:
    batch = prepare_statement_batch([_line("MATRIX ATM'S 4402", -500, "atm", account_id=3)], ALIASES)

    assert [(tx["account_id"], tx["amount"], tx["external_id"]) for tx in batch] == [
        (3, -500, "atm"),
        (SHARED_CASH_ACCOUNT_ID, 500, "atm_offset"),
    ]
    assert batch[1]["category_id"] == CASH_WITHDRAWAL_CATEGORY_ID


def test_internal_transfer_gets_an_offset_on_the_transit_account_with_the_opposite_sign() -> None:
    batch = prepare_statement_batch([_line("BIT TOP UP", 70, "top")], ALIASES)

    assert [(tx["account_id"], tx["amount"]) for tx in batch] == [(1, 70), (TRANSIT_ACCOUNT_ID, -70)]


def test_offsets_come_after_all_lines() -> None:
    lines = [_line("BIT TOP UP", -10, "a"), _line("CAFE DEMO", -5, "b")]

    batch = prepare_statement_batch(lines, ALIASES)

    assert [tx["external_id"] for tx in batch] == ["a", "b", "a_offset"]
