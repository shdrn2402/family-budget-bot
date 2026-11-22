"""Bank Leumi account statement (.xls export, sheet 'Activities', header on row 2).

Blank cells are a single space. The first line is the opening balance, which goes to
the statement metadata. Card-company lines (ISRACARD - ...) are kept: whether to book
them is the caller's decision.
"""

import io
import logging
from typing import Any

import pandas as pd

from budget_core.models import LeumiRow, LeumiStatement
from budget_core.parsers._cells import is_blank, period, text, to_date, to_date_or_none, to_decimal, to_decimal_or_none

PARSER_VERSION = "1.0.0"
SOURCE = "leumi"

logger = logging.getLogger(__name__)

SHEET = "Activities"
DATE_FORMAT = "%d/%m/%Y"
OPENING_BALANCE = "OPENING BALANCE"


def parse(data: bytes) -> LeumiStatement:
    df = pd.read_excel(io.BytesIO(data), sheet_name=SHEET, header=1, engine="xlrd")

    rows: list[LeumiRow] = []
    opening_balance = None
    for record in df.to_dict("records"):
        description = text(record.get("Transaction"))
        if description is None:
            continue
        if OPENING_BALANCE in description.upper():
            if opening_balance is None:
                opening_balance = to_decimal_or_none(record.get("Balance"))
            continue
        try:
            credit = to_decimal(record.get("Credit"))
            debit = to_decimal(record.get("Debit"))
            row_date = to_date(record.get("Date"), DATE_FORMAT)
        except ValueError as e:
            logger.warning("Skipping unreadable Leumi line %r: %s", description, e)
            continue
        if credit is None and debit is None:
            continue
        rows.append(LeumiRow(
            date=row_date,
            value_date=to_date_or_none(record.get("Value date"), DATE_FORMAT),
            description=description,
            credit=credit,
            debit=debit,
            balance=to_decimal_or_none(record.get("Balance")),
            reference=_code(record.get("Reference")),
            code=_code(record.get("Code")),
        ))

    start, end = period([r.date for r in rows])
    return LeumiStatement(
        parser_version=PARSER_VERSION,
        period_start=start,
        period_end=end,
        opening_balance=opening_balance,
        rows=tuple(rows),
    )


def _code(value: Any) -> str | None:
    """Reference/code cells as the export's text: str() of the cell, not stripped."""
    return None if is_blank(value) else str(value)
