"""Bit payment-app history (.csv export).

UTF-8 with BOM, ', ' separators, data lines end with a trailing ', ', and a free-text
footer follows the data. Every status is kept (Done, Expired, Failed, ...); only lines
without a status (the footer) are dropped.
"""

import io
import logging
import warnings

import pandas as pd

from budget_core.models import BitRow, BitStatement
from budget_core.parsers._cells import period, text, to_date, to_decimal, to_decimal_or_none

PARSER_VERSION = "1.0.0"
SOURCE = "bit"

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d.%m.%y"


def parse(data: bytes) -> BitStatement:
    with warnings.catch_warnings():
        # Data lines have one more (empty) field than the header: expected, not data loss.
        warnings.simplefilter("ignore", pd.errors.ParserWarning)
        df = pd.read_csv(
            io.BytesIO(data),
            dtype=str,
            on_bad_lines="skip",
            skipinitialspace=True,
            index_col=False,
        )

    rows: list[BitRow] = []
    for record in df.to_dict("records"):
        status = text(record.get("Status"))
        if status is None:
            continue
        try:
            amount = to_decimal(record.get("Amount"))
            raw_date = text(record.get("Date"))
            row_date = to_date(raw_date.strip(",") if raw_date else raw_date, DATE_FORMAT)
        except ValueError as e:
            logger.warning("Skipping unreadable Bit line: %s", e)
            continue
        if amount is None:
            continue
        rows.append(BitRow(
            date=row_date,
            status=status,
            description=text(record.get("Description")) or "",
            amount=amount,
            fee=to_decimal_or_none(record.get("Fee Amount")),
            payment_method=text(record.get("Payment Method")) or "",
            direction=text(record.get("Credit/Debit")) or "",
            counterparty=text(record.get("From/To")) or "",
        ))

    start, end = period([r.date for r in rows])
    return BitStatement(parser_version=PARSER_VERSION, period_start=start, period_end=end, rows=tuple(rows))
