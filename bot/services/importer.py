"""Statement import for the bot: picks the parser by file name and books the lines.

Parsing itself is in budget_core.parsers (pure, typed, keeps every line). The functions
here are the bot's adapter on top: they apply today's filters and account assignment
and return the dicts the import handler saves.
"""

import logging
import os
import re
from datetime import datetime, time

from budget_core.household import AccountRoles
from budget_core.parsers import bit, isracard, leumi

logger = logging.getLogger(__name__)

BIT_BANK_ACCOUNT = 'חשבון בנק'
BIT_CARD = 'כרטיס אשראי'
BIT_BALANCE = 'יתרה'


class BitCardAccountMissing(Exception):
    """A Bit export needs the uploader's own card account for its card-paid lines."""


def _read(file_path) -> bytes:
    with open(file_path, 'rb') as f:
        return f.read()


def _at_midnight(d) -> datetime:
    return datetime.combine(d, time())


def parse_leumi(file_path, roles: AccountRoles):
    """Bank Leumi lines on the bank account (role 'bank'). Card-company lines are skipped:
    the card statement has their detail."""
    bank_account = roles.require("bank")
    transactions = []
    for row in leumi.parse(_read(file_path)).rows:
        if 'ISRACARD' in row.description.upper():
            logger.info(f"Skipping Isracard record in Bank statement: {row.description}")
            continue

        # Debit is negative, credit positive; a debit cell wins when both are filled.
        if row.debit is not None:
            amount = -abs(float(row.debit))
        else:
            amount = abs(float(row.credit))
        if amount == 0:
            continue

        date_obj = _at_midnight(row.date)
        reference = row.reference if row.reference is not None else 'no_ref'
        transactions.append({
            'date': date_obj,
            'amount': amount,
            'description': row.description,
            'external_id': f"leumi_{reference}_{date_obj.strftime('%Y%m%d')}_{amount}",
            'account_id': bank_account,
            'source_type': 'import_xls'
        })
    return transactions


def parse_isracard(file_path, account_id):
    """Isracard charges on the given card account. Pending lines (no voucher yet) are
    skipped: they come back with a voucher on next month's statement."""
    transactions = []
    for row in isracard.parse(_read(file_path)).rows:
        if row.voucher is None or row.charge_amount is None:
            continue
        transactions.append({
            'date': _at_midnight(row.purchase_date),
            'amount': -abs(float(row.charge_amount)),  # card charges are always expenses
            'description': row.merchant,
            'external_id': f"isracard_{row.voucher}",
            'account_id': account_id,
            'source_type': 'import_xls'
        })
    return transactions

def import_excel_file(file_path, roles: AccountRoles, hint=None, bit_card_account_id: int | None = None):
    """
    Detects file type based on hint (from Telegram caption) or filename patterns.
    - FibiSave -> Bank Leumi (the bank account)
    - Starts with 4 digits -> Isracard: the card with those last digits, else the default card
    - Bit CSV -> card-paid lines go to `bit_card_account_id`, the uploader's own card.
      Raises BitCardAccountMissing if it isn't known.
    The accounts come from `roles` (the household file); HouseholdNotLoaded if one is missing.
    """
    filename = os.path.basename(file_path)
    search_text = (filename + (hint if hint else "")).lower()

    # Precise patterns
    if 'fibisave' in search_text or 'leumi' in search_text or 'benleumi' in search_text:
        return parse_leumi(file_path, roles)

    # Isracard pattern: the file name starts with the card's last 4 digits
    match = re.match(r'^(\d{4})', filename)
    if match or 'isracard' in search_text:
        card_last4 = match.group(1) if match else None
        return parse_isracard(file_path, account_id=roles.isracard_account(card_last4))

    # Bit CSV pattern
    if 'bit' in search_text and search_text.endswith('.csv'):
        if bit_card_account_id is None:
            raise BitCardAccountMissing()
        return parse_bit_csv(file_path, account_id=bit_card_account_id, roles=roles)

    logger.warning(f"Unknown file format: {filename} (hint: {hint})")
    return []

def parse_bit_csv(file_path, account_id, roles: AccountRoles):
    """
    Done Bit lines, booked by payment method:
    - Bit balance -> transit account; card -> `account_id` (the uploader's card);
      bank account -> the bank account (roles 'transit' and 'bank').
    - A withdrawal to the bank account becomes two lines: out of transit, into the bank.
    """
    bank_account, transit_account = roles.require("bank"), roles.require("transit")
    transactions = []
    for row in bit.parse(_read(file_path)).rows:
        if row.status.lower() != 'done':
            continue
        amount_val = float(row.amount)
        if amount_val == 0:
            continue

        date_obj = _at_midnight(row.date)
        day = date_obj.strftime('%Y%m%d')
        from_to = row.counterparty
        base_amount = abs(amount_val) if row.direction.lower() == 'credit' else -abs(amount_val)

        def line(account, amount):
            return {
                'date': date_obj,
                'amount': amount,
                'description': row.description,
                'comment': from_to,
                'external_id': f"bit_{day}_{account}_{amount}_{from_to}",
                'account_id': account,
                'source_type': 'import_bit',
                'status': 'confirmed'
            }

        if row.payment_method == BIT_BANK_ACCOUNT:
            if 'withdrawal' in row.description.lower():
                # Transfer from transit to the bank: out of one, into the other.
                transactions.append(line(transit_account, -abs(amount_val)))
                transactions.append(line(bank_account, abs(amount_val)))
                continue
            target_account = bank_account
        elif row.payment_method == BIT_CARD:
            target_account = account_id
        elif row.payment_method == BIT_BALANCE:
            target_account = transit_account
        else:
            logger.warning(f"Unknown payment method in Bit CSV: {row.payment_method}")
            continue

        transactions.append(line(target_account, base_amount))
    return transactions
