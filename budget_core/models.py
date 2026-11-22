"""Typed records the parsers return.

They describe what a statement file says, not how the household books it: no account
IDs, no categories, no filtering. Amounts are exact Decimals, unsigned as in the file;
the side (debit/credit, card charge) is a separate field.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Statement(_Record):
    parser_version: str
    # First and last transaction date in the file; None when it has no rows.
    period_start: date | None
    period_end: date | None


# --- Isracard (credit card, .xlsx) ---------------------------------------------------


class IsracardSection(StrEnum):
    BILLING = "billing"  # עסקאות למועד חיוב: charged on the statement's billing date
    OUTSIDE_BILLING = "outside_billing"  # עסקאות בחיוב מחוץ למועד: charged on their own date
    PENDING = "pending"  # עסקאות שטרם נקלטו: not yet received, charged next month
    UNKNOWN = "unknown"  # a table without a recognised title


class IsracardRow(_Record):
    section: IsracardSection
    purchase_date: date
    merchant: str
    amount: Decimal | None  # transaction amount, in `currency`
    currency: str | None
    charge_amount: Decimal | None  # this statement's charge, in `charge_currency`; None on pending lines
    charge_currency: str | None
    voucher: str | None  # None on pending lines
    notes: str | None  # e.g. installment number, standing order, foreign site
    bank_charge_date: date | None  # outside-billing lines only


class IsracardStatement(_Statement):
    source: Literal["isracard"] = "isracard"
    statement_month: date | None  # first day of the month in the title
    billing_date: date | None  # when the bank account is charged for the billing section
    statement_total: Decimal | None
    rows: tuple[IsracardRow, ...]


# --- Leumi (bank account, .xls) ------------------------------------------------------


class LeumiRow(_Record):
    date: date
    value_date: date | None
    description: str
    credit: Decimal | None
    debit: Decimal | None
    balance: Decimal | None
    reference: str | None
    code: str | None


class LeumiStatement(_Statement):
    source: Literal["leumi"] = "leumi"
    opening_balance: Decimal | None
    rows: tuple[LeumiRow, ...]


# --- Bit (payment app, .csv) ---------------------------------------------------------


class BitRow(_Record):
    date: date
    status: str  # "Done", "Expired", "Failed", ...
    description: str
    amount: Decimal
    fee: Decimal | None
    payment_method: str  # יתרה (Bit balance), כרטיס אשראי (card), חשבון בנק (bank account)
    direction: str  # "Credit" or "Debit", as in the file
    counterparty: str


class BitStatement(_Statement):
    source: Literal["bit"] = "bit"
    rows: tuple[BitRow, ...]
