import pytest
from unittest.mock import patch

from budget_core.household import AccountRoles, HouseholdNotLoaded
from bot.services.importer import BitCardAccountMissing, import_excel_file

# Fake household data (the real card digits are private and live in the database).
ROLES = AccountRoles(
    by_role={"default_card": 1, "bank": 3, "transit": 5},
    by_card_last4={"1111": 1, "2222": 2},
)


def test_import_excel_file_routing():
    """The router picks the parser and the account from the file name and the household data."""
    with patch('bot.services.importer.parse_leumi') as mock_leumi, \
         patch('bot.services.importer.parse_isracard') as mock_isra:

        # Bank Leumi (FibiSave)
        import_excel_file("FibiSave_Activities.xls", ROLES)
        mock_leumi.assert_called_once_with("FibiSave_Activities.xls", ROLES)
        mock_isra.assert_not_called()

        # Isracard: the file name starts with the card's last 4 digits
        import_excel_file("2222_report.xlsx", ROLES)
        mock_isra.assert_called_with("2222_report.xlsx", account_id=2)

        # Unknown digits, or only the 'isracard' hint: the default card
        import_excel_file("9999_report.xlsx", ROLES)
        mock_isra.assert_called_with("9999_report.xlsx", account_id=1)
        import_excel_file("report.xlsx", ROLES, hint="isracard")
        mock_isra.assert_called_with("report.xlsx", account_id=1)

    with patch('bot.services.importer.parse_bit_csv') as mock_bit:
        import_excel_file("bit_transactions_2026.csv", ROLES, bit_card_account_id=7)
        mock_bit.assert_called_with("bit_transactions_2026.csv", account_id=7, roles=ROLES)


def test_bit_export_without_the_uploaders_card_is_refused():
    """#12: card-paid Bit lines used to be filed on a hard-coded account."""
    with patch('bot.services.importer.parse_bit_csv') as mock_bit:
        with pytest.raises(BitCardAccountMissing):
            import_excel_file("bit_transactions_2026.csv", ROLES)
        mock_bit.assert_not_called()


def test_an_isracard_file_without_a_default_card_asks_for_the_household_file():
    roles = AccountRoles(by_card_last4={"1111": 1})
    with pytest.raises(HouseholdNotLoaded, match="default_card"):
        import_excel_file("9999_report.xlsx", roles)
