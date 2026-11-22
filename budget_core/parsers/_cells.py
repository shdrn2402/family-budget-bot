"""Helpers for reading spreadsheet and CSV cells as pandas returns them."""

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


def is_blank(value: Any) -> bool:
    """None, NaN/NaT, or text that is empty after stripping (the Leumi export uses ' ')."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def text(value: Any) -> str | None:
    """The cell as text, stripped; None when blank."""
    return None if is_blank(value) else str(value).strip()


def to_decimal(value: Any) -> Decimal | None:
    """An exact Decimal from a number or text like '1,250.00'; None when blank.

    Floats go through their shortest repr (0.35 -> Decimal('0.35')), as Excel shows them.
    Raises ValueError on anything that isn't a finite number.
    """
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"not a number: {value!r}")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as e:
        raise ValueError(f"not a number: {value!r}") from e
    if not result.is_finite():
        raise ValueError(f"not a number: {value!r}")
    return result


def to_decimal_or_none(value: Any) -> Decimal | None:
    try:
        return to_decimal(value)
    except ValueError:
        return None


def to_date(value: Any, fmt: str) -> date:
    """A date from a datetime cell or from text in `fmt`. Raises ValueError otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if is_blank(value):
        raise ValueError("blank date")
    return datetime.strptime(str(value).strip(), fmt).date()


def to_date_or_none(value: Any, fmt: str) -> date | None:
    try:
        return to_date(value, fmt)
    except ValueError:
        return None


def period(dates: list[date]) -> tuple[date | None, date | None]:
    return (min(dates), max(dates)) if dates else (None, None)
