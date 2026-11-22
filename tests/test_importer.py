import pytest
from unittest.mock import patch

from bot.services.importer import BitCardAccountMissing, import_excel_file

def test_import_excel_file_routing():
    """Test that the main router correctly identifies file types based on new patterns."""
    with patch('bot.services.importer.parse_leumi') as mock_leumi, \
         patch('bot.services.importer.parse_isracard') as mock_isra:
         
        # Test Bank Leumi (FibiSave)
        import_excel_file("FibiSave_Activities.xls")
        mock_leumi.assert_called_once()
        mock_isra.assert_not_called()
        
        mock_leumi.reset_mock()
        
        # Test Isracard (starts with 4787)
        import_excel_file("4787_isracard_report.xlsx")
        mock_isra.assert_called_with("4787_isracard_report.xlsx", account_id=1)
        
        mock_isra.reset_mock()

        # Test Isracard (starts with 6747 - Wife)
        import_excel_file("6747_wife_report.xlsx")
        mock_isra.assert_called_with("6747_wife_report.xlsx", account_id=2)

    with patch('bot.services.importer.parse_bit_csv') as mock_bit:
        import_excel_file("bit_transactions_2026.csv", bit_card_account_id=7)
        mock_bit.assert_called_with("bit_transactions_2026.csv", account_id=7)


def test_bit_export_without_the_uploaders_card_is_refused():
    """#12: card-paid Bit lines used to be filed on a hard-coded account."""
    with patch('bot.services.importer.parse_bit_csv') as mock_bit:
        with pytest.raises(BitCardAccountMissing):
            import_excel_file("bit_transactions_2026.csv")
        mock_bit.assert_not_called()
