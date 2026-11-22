"""Isracard credit-card statement (.xlsx export).

One sheet holds a title block and several tables, each with a Hebrew title row above
its header: billing-date charges, charges outside the billing date and, sometimes,
pending transactions. A table ends at a blank date cell or a totals (סה"כ) row.
"""

import io
import logging
import re
from datetime import date
from typing import Any

import pandas as pd

from budget_core.models import IsracardRow, IsracardSection, IsracardStatement
from budget_core.parsers._cells import is_blank, period, text, to_date, to_date_or_none, to_decimal, to_decimal_or_none

PARSER_VERSION = "1.0.0"
SOURCE = "isracard"

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d.%m.%y"
SECTION_TITLES = {
    "עסקאות למועד חיוב": IsracardSection.BILLING,
    "עסקאות בחיוב מחוץ למועד": IsracardSection.OUTSIDE_BILLING,
    "עסקאות שטרם נקלטו": IsracardSection.PENDING,
}
HEADER_DATE = "תאריך רכישה"
HEADER_MERCHANT = "שם בית עסק"
TOTALS_MARK = 'סה"כ'
# Columns relative to the header's date column.
COL_DATE, COL_MERCHANT, COL_AMOUNT, COL_CURRENCY, COL_CHARGE, COL_CHARGE_CURRENCY, COL_VOUCHER, COL_NOTES, COL_BANK_DATE = range(9)

HEBREW_MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTH_RE = re.compile(rf"^({'|'.join(HEBREW_MONTHS)})\s+(\d{{4}})$")
BILLING_RE = re.compile(r"לחיוב ב-(\d{1,2})\.(\d{1,2})")
TOTAL_RE = re.compile(r"^₪\s*(-?[\d,]+(?:\.\d+)?)$")
# The title block is above the first table; metadata is only looked for there.
TITLE_BLOCK_ROWS = 10


def parse(data: bytes) -> IsracardStatement:
    raw = pd.read_excel(io.BytesIO(data), header=None, engine="openpyxl")
    grid = [row.tolist() for _, row in raw.iterrows()]

    rows: list[IsracardRow] = []
    section = IsracardSection.UNKNOWN
    for i, cells in enumerate(grid):
        title = text(cells[0]) if cells else None
        if title in SECTION_TITLES:
            section = SECTION_TITLES[title]
            continue
        texts = [str(c) for c in cells]
        if HEADER_DATE in texts and HEADER_MERCHANT in texts:
            rows.extend(_table(grid, i + 1, texts.index(HEADER_DATE), section))
            section = IsracardSection.UNKNOWN

    statement_month, billing_date, total = _title_metadata(grid[:TITLE_BLOCK_ROWS])
    start, end = period([r.purchase_date for r in rows])
    return IsracardStatement(
        parser_version=PARSER_VERSION,
        period_start=start,
        period_end=end,
        statement_month=statement_month,
        billing_date=billing_date,
        statement_total=total,
        rows=tuple(rows),
    )


def _table(grid: list[list[Any]], first: int, offset: int, section: IsracardSection) -> list[IsracardRow]:
    def cell(cells: list[Any], col: int) -> Any:
        idx = offset + col
        return cells[idx] if idx < len(cells) else None

    rows = []
    for cells in grid[first:]:
        if is_blank(cell(cells, COL_DATE)) or TOTALS_MARK in str(cells):
            break
        try:
            purchase_date = to_date(cell(cells, COL_DATE), DATE_FORMAT)
            charge_amount = to_decimal(cell(cells, COL_CHARGE))
        except ValueError as e:
            logger.warning("Skipping unreadable Isracard line: %s", e)
            continue
        merchant = cell(cells, COL_MERCHANT)
        rows.append(IsracardRow(
            section=section,
            purchase_date=purchase_date,
            # Not stripped: merchant text is matched against learned aliases as is.
            merchant="" if is_blank(merchant) else str(merchant),
            amount=to_decimal_or_none(cell(cells, COL_AMOUNT)),
            currency=text(cell(cells, COL_CURRENCY)),
            charge_amount=charge_amount,
            charge_currency=text(cell(cells, COL_CHARGE_CURRENCY)),
            voucher=text(cell(cells, COL_VOUCHER)),
            notes=text(cell(cells, COL_NOTES)),
            bank_charge_date=to_date_or_none(cell(cells, COL_BANK_DATE), DATE_FORMAT),
        ))
    return rows


def _title_metadata(block: list[list[Any]]) -> tuple[date | None, date | None, Any]:
    """Statement month, billing date and total from the title block. Best effort: None if absent."""
    statement_month = billing = total = None
    for cells in block:
        for value in cells:
            s = text(value)
            if s is None:
                continue
            if statement_month is None and (m := MONTH_RE.match(s)):
                statement_month = date(int(m.group(2)), HEBREW_MONTHS.index(m.group(1)) + 1, 1)
            elif billing is None and (m := BILLING_RE.search(s)):
                billing = (int(m.group(1)), int(m.group(2)))
            elif total is None and (m := TOTAL_RE.match(s)):
                total = to_decimal(m.group(1))

    billing_date = None
    if billing and statement_month:
        day, month = billing
        # The text has no year: take the one closest to the statement month, so a
        # December statement charged in January lands in the next year.
        candidates = []
        for year in (statement_month.year - 1, statement_month.year, statement_month.year + 1):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                pass
        if candidates:
            billing_date = min(candidates, key=lambda d: abs((d - statement_month).days))
    return statement_month, billing_date, total
