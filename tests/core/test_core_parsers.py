"""Golden and behaviour tests for the pure parsers in budget_core/parsers/.

Each fixture in tests/fixtures/statements/ has a `<name>.core.json` with the
parsed statement (metadata + rows, as the parser returns them). The bot-side
output built on top of it is pinned separately in `<name>.expected.json`
(tests/test_statement_fixtures.py). To accept a change on purpose:

    UPDATE_GOLDENS=1 uv run pytest tests/budget_core/test_core_parsers.py
"""

import io
import json
import os
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook
from pydantic import BaseModel, ValidationError

from budget_core.models import IsracardSection
from budget_core.parsers import bit, isracard, leumi

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "statements"
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"

CASES: dict[str, Callable[[bytes], BaseModel]] = {
    "isracard/1111_06_2026.xlsx": isracard.parse,
    "isracard/1111_07_2026_with_pending.xlsx": isracard.parse,
    "leumi/FibiSave0000_06.xls": leumi.parse,
    "bit/bit_transactions_2026.csv": bit.parse,
}


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize("name", sorted(CASES))
def test_core_output_matches_golden(name: str) -> None:
    actual = CASES[name](_read(name)).model_dump(mode="json")
    golden = (FIXTURES / name).with_name(Path(name).name + ".core.json")

    if UPDATE:
        golden.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    assert golden.exists(), f"missing {golden.name}; run with UPDATE_GOLDENS=1"
    assert actual == json.loads(golden.read_text(encoding="utf-8"))


def test_every_fixture_file_has_a_core_case() -> None:
    files = {str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*") if p.suffix in {".xlsx", ".xls", ".csv"}}
    assert files == set(CASES)


@pytest.mark.parametrize("module", [isracard, leumi, bit])
def test_parser_version_is_stamped_on_the_statement(module) -> None:
    name = next(n for n, fn in CASES.items() if fn is module.parse)
    statement = module.parse(_read(name))
    assert module.PARSER_VERSION
    assert statement.parser_version == module.PARSER_VERSION
    assert statement.source == module.SOURCE


def test_records_are_immutable() -> None:
    statement = bit.parse(_read("bit/bit_transactions_2026.csv"))
    with pytest.raises(ValidationError):
        statement.rows[0].amount = Decimal("1")


# --- Isracard ------------------------------------------------------------------------


def test_isracard_statement_metadata() -> None:
    statement = isracard.parse(_read("isracard/1111_06_2026.xlsx"))
    assert statement.statement_month == date(2026, 6, 1)
    assert statement.billing_date == date(2026, 6, 15)
    assert statement.statement_total == Decimal("1610.30")
    assert statement.period_start == date(2026, 5, 2)
    assert statement.period_end == date(2026, 6, 5)


def test_isracard_keeps_section_notes_original_amount_and_bank_charge_date() -> None:
    """#46: the bot still drops these, but the parser keeps them for later stages."""
    rows = {r.voucher: r for r in isracard.parse(_read("isracard/1111_06_2026.xlsx")).rows}

    installment = rows["1000004"]
    assert installment.section is IsracardSection.BILLING
    assert installment.amount == Decimal("1200")
    assert installment.charge_amount == Decimal("100")
    assert installment.notes == "תשלום 3 מתוך 12"
    assert installment.bank_charge_date is None

    foreign = rows["2000002"]
    assert foreign.section is IsracardSection.OUTSIDE_BILLING
    assert (foreign.amount, foreign.currency) == (Decimal("20"), "$")
    assert (foreign.charge_amount, foreign.charge_currency) == (Decimal("74.6"), "₪")
    assert foreign.bank_charge_date == date(2026, 6, 4)


def test_isracard_keeps_pending_lines_without_voucher_or_charge() -> None:
    statement = isracard.parse(_read("isracard/1111_07_2026_with_pending.xlsx"))
    pending = [r for r in statement.rows if r.section is IsracardSection.PENDING]
    assert [(r.merchant, r.amount, r.currency) for r in pending] == [
        ("מסעדה לדוגמה", Decimal("120"), "₪"),
        ("DEMO APP STORE", Decimal("9.99"), "$"),
    ]
    assert all(r.voucher is None and r.charge_amount is None for r in pending)
    assert statement.statement_month == date(2026, 7, 1)
    assert statement.billing_date == date(2026, 7, 15)


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            if value is not None:
                wb.active.cell(row=r, column=c, value=value)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_isracard_metadata_is_best_effort() -> None:
    """A file without the title block still parses; the metadata is just unknown."""
    data = _xlsx([
        ["תאריך רכישה", "שם בית עסק", "סכום עסקה", "מטבע עסקה", "סכום חיוב", "מטבע חיוב", "מס' שובר"],
        ["02.05.26", "סופר", 10, "₪", 10, "₪", "1"],
    ])
    statement = isracard.parse(data)
    assert (statement.statement_month, statement.billing_date, statement.statement_total) == (None, None, None)
    assert [r.section for r in statement.rows] == [IsracardSection.UNKNOWN]


def test_isracard_billing_date_in_the_previous_year() -> None:
    data = _xlsx([
        [None, None, "ינואר 2027"],
        [None, None, None, None, None, None, None, "לחיוב ב-31.12"],
    ])
    assert isracard.parse(data).billing_date == date(2026, 12, 31)


def test_isracard_billing_date_in_the_next_year() -> None:
    data = _xlsx([
        [None, None, "דצמבר 2026"],
        [None, None, None, None, None, None, None, "לחיוב ב-02.01"],
    ])
    assert isracard.parse(data).billing_date == date(2027, 1, 2)


# --- Leumi ---------------------------------------------------------------------------


def test_leumi_metadata_and_card_company_lines_are_kept() -> None:
    statement = leumi.parse(_read("leumi/FibiSave0000_06.xls"))
    assert statement.opening_balance == Decimal("-1520.4")
    assert (statement.period_start, statement.period_end) == (date(2026, 6, 1), date(2026, 6, 20))
    assert not any("OPENING BALANCE" in r.description for r in statement.rows)
    card_lines = [r for r in statement.rows if r.description.startswith("ISRACARD")]
    assert [r.debit for r in card_lines] == [Decimal("2310.75"), Decimal("412")]


def test_leumi_amounts_are_exact_decimals() -> None:
    rows = leumi.parse(_read("leumi/FibiSave0000_06.xls")).rows
    fee = next(r for r in rows if r.description.startswith("ACCOUNT FEE"))
    assert (fee.debit, fee.credit) == (Decimal("0.35"), None)


# --- Bit -----------------------------------------------------------------------------


def test_bit_keeps_every_status_and_skips_the_footer() -> None:
    statement = bit.parse(_read("bit/bit_transactions_2026.csv"))
    assert [r.status for r in statement.rows].count("Done") == 10
    assert {r.status for r in statement.rows} == {"Done", "Expired", "Failed"}
    assert (statement.period_start, statement.period_end) == (date(2026, 6, 3), date(2026, 6, 20))


def test_bit_row_fields() -> None:
    row = bit.parse(_read("bit/bit_transactions_2026.csv")).rows[2]
    assert row.model_dump() == {
        "date": date(2026, 6, 7),
        "status": "Done",
        "description": "Перевод другу",
        "amount": Decimal("45.5"),
        "fee": Decimal("0"),
        "payment_method": "יתרה",
        "direction": "Debit",
        "counterparty": "Иван Петров",
    }
