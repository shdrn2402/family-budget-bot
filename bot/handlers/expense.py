import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot.database import get_db_connection
from bot.services.expense import process_expense_text
from bot.handlers.common import check_access
from bot.texts import get_text
import psycopg

logger = logging.getLogger(__name__)

async def expense_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles regular text messages for quick expense entry.
    Example: "продукты кредитка 150.5"
    """
    if not update.message or not update.message.text:
        return

    # 0. Check access and auto-register allowed user if needed
    if not await check_access(update):
        return

    text = update.message.text
    user_id = update.effective_user.id
    lang = update.effective_user.language_code
    
    try:
        async with await get_db_connection() as conn:
            # 1. Parse the text using the smart router
            parsed_items = await process_expense_text(text, conn)
            
            if not parsed_items:
                await update.message.reply_text(get_text("parse_error", lang))
                return
                
            responses = []
            
            # 2. Save each parsed item
            total_sum = 0.0
            inserted_ids = []
            async with conn.cursor() as cur:
                for item in parsed_items:
                    if 'error' in item:
                        if item['error'] == 'llm_failed':
                            responses.append(get_text("llm_failed", lang, details=item.get('details', '')))
                        else:
                            responses.append(get_text("item_parse_error", lang, original=item.get('original', text)))
                        continue
                        
                    # Prepare data
                    amount = item['amount']
                    account_id = item['account_id']
                    category_id = item['category_id']
                    item_name = item['item_name']
                    
                    if not account_id:
                        responses.append(get_text("account_not_found", lang, alias=item['account_alias'], original=item.get('original', text)))
                        continue
                    
                    # NEW: Restrict manual entry to cash accounts only
                    from bot.database import get_account_type
                    account_type = await get_account_type(account_id, conn)
                    if account_type != 'cash':
                        responses.append(get_text("manual_bank_entry_denied", lang))
                        continue
                        
                    # Insert into transactions
                    await cur.execute(
                        """
                        INSERT INTO transactions (user_id, account_id, category_id, amount, description, date, source_type)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, 'manual')
                        RETURNING id;
                        """,
                        (user_id, account_id, category_id, amount, item_name)
                    )
                    
                    row = await cur.fetchone()
                    if row:
                        inserted_ids.append(str(row['id']))
                    
                    total_sum += amount
                    cat_status = get_text("category_found", lang) if category_id else get_text("category_not_found", lang)
                    responses.append(get_text("expense_saved", lang, 
                        item=item_name, 
                        amount=f"{amount:.2f}", 
                        account=item['account_alias'], 
                        cat_status=cat_status
                    ))
                
                await conn.commit()
                
            # Add total sum if there's more than one successful transaction
            final_text = "\n".join(responses)
            if total_sum > 0:
                final_text += f"\n" + get_text("total_saved", lang, amount=f"{total_sum:.2f}")
                
            # 3. Reply to user with Inline Keyboard
            if inserted_ids:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                
                ids_str = ",".join(inserted_ids)
                keyboard = [
                    [InlineKeyboardButton(get_text("edit_records_button", lang), callback_data=f"edit_main:{ids_str}:")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(final_text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(final_text)
            
    except psycopg.Error as e:
        logger.error(f"Database error in expense handler: {e}")
        await update.message.reply_text(get_text("database_error", lang))
    except Exception as e:
        logger.error(f"Unexpected error in expense handler: {e}")
        await update.message.reply_text(get_text("database_error", lang))
