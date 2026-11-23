import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot.handlers.expense import expense_message_handler

@pytest.mark.asyncio
async def test_expense_handler_allows_cash_entry():
    """Test that manual entry is allowed for cash accounts."""
    update = MagicMock()
    update.message.text = "coffee cash 10"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 123
    update.effective_user.language_code = "en"
    context = MagicMock()
    
    # Mock dependencies
    with patch("bot.handlers.expense.process_expense_text") as mock_process, \
         patch("db.accounts.get_type", new_callable=AsyncMock) as mock_get_type, \
         patch("db.transactions.insert_manual", new_callable=AsyncMock, return_value=999) as mock_insert, \
         patch("bot.handlers.expense.check_access", return_value=True):

        # Mock parsed item
        mock_process.return_value = [{
            'item_name': 'coffee',
            'amount': 10.0,
            'account_id': 3,
            'account_alias': 'cash',
            'category_id': 1
        }]
        
        # Mock account type as 'cash'
        mock_get_type.return_value = 'cash'
        
        await expense_message_handler(update, context)
        
        # Verify it inserted into DB
        mock_insert.assert_awaited_once()
        update.message.reply_text.assert_called_once()
        args, _ = update.message.reply_text.call_args
        assert "✅" in args[0]
        assert "coffee" in args[0]

@pytest.mark.asyncio
async def test_expense_handler_blocks_card_entry():
    """Test that manual entry is blocked for card accounts."""
    update = MagicMock()
    update.message.text = "coffee card 200"
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 123
    update.effective_user.language_code = "en"
    context = MagicMock()
    
    # Mock dependencies
    with patch("bot.handlers.expense.process_expense_text") as mock_process, \
         patch("db.accounts.get_type", new_callable=AsyncMock) as mock_get_type, \
         patch("db.transactions.insert_manual", new_callable=AsyncMock, return_value=999) as mock_insert, \
         patch("bot.handlers.expense.check_access", return_value=True):

        # Mock parsed item
        mock_process.return_value = [{
            'item_name': 'coffee',
            'amount': 200.0,
            'account_id': 1,
            'account_alias': 'card',
            'category_id': 1
        }]
        
        # Mock account type as 'card'
        mock_get_type.return_value = 'card'
        
        await expense_message_handler(update, context)
        
        # Verify the reply contains the "denied" message
        update.message.reply_text.assert_called_once()
        args, _ = update.message.reply_text.call_args
        assert "⚠️" in args[0]
        assert "Please use bank statements" in args[0]
        
        # Verify NO insertion attempt
        mock_insert.assert_not_called()
