import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot.services.expense import process_expense_text, save_expense_item

from bot.handlers.common import check_access
from db import pool, transactions
from bot.texts import get_text

logger = logging.getLogger(__name__)

async def expense_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Text message handler: renames/re-prices a transaction (reply to the bot) or saves expenses.
    """
    if not await check_access(update):
        return

    text = update.message.text
    if not text:
        return

    lang = update.effective_user.language_code
    user_id = update.effective_user.id

    # --- RENAME OR REPRICE TRANSACTION INTERCEPT ---
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        original_text = update.message.reply_to_message.text
        if "напишите новое название" in original_text or "write the new name" in original_text:
            import re
            match = re.search(r"\[ID:\s*(\d+)\]", original_text)
            if match:
                tx_id = int(match.group(1))
                new_name = text.strip().lower()
                
                async with pool.connection() as conn:
                    await transactions.rename(conn, tx_id, new_name)
                
                success_msg = f"✅ Название изменено на '{new_name}'" if lang == 'ru' else f"✅ Name changed to '{new_name}'"
                await update.message.reply_text(success_msg)
                return
        elif "напишите новую сумму" in original_text or "write the new amount" in original_text:
            import re
            match = re.search(r"\[ID_SUM:\s*(\d+)\]", original_text)
            if match:
                tx_id = int(match.group(1))
                try:
                    new_amount = float(text.strip().replace(',', '.'))
                    db_amount = -abs(new_amount)
                    
                    async with pool.connection() as conn:
                        await transactions.set_amount(conn, tx_id, db_amount)
                    
                    success_msg = f"✅ Сумма изменена на '{new_amount}'" if lang == 'ru' else f"✅ Amount changed to '{new_amount}'"
                    await update.message.reply_text(success_msg)
                except ValueError:
                    error_msg = "❌ Пожалуйста, введите корректное число." if lang == 'ru' else "❌ Please enter a valid number."
                    await update.message.reply_text(error_msg)
                return

    # --- EXPENSE PROCESSING ---
    async with pool.connection() as conn:
        parsed_items = await process_expense_text(text, user_id, conn)

        if not parsed_items:
            return

        parse_errors = [item for item in parsed_items if 'error' in item]
        if parse_errors:
            # Nothing is saved; say what couldn't be read and how to write it.
            lines = []
            for item in parse_errors:
                original = item.get('original', text)
                if item['error'] == 'unknown_account':
                    lines.append(get_text("account_not_found", lang, alias=item.get('account_alias', ''),
                                          original=original))
                else:
                    lines.append(get_text("item_parse_error", lang, original=original))
            await update.message.reply_text("\n".join(lines) + "\n\n" + get_text("parse_error", lang))
            return

        responses = []
        inserted_ids = []
        total_amount = 0.0

        for item in parsed_items:
            save_res = await save_expense_item(item, user_id, lang, conn, 'manual_text')
            
            if "error" in save_res:
                if save_res["error"] == "account_not_found":
                    responses.append(f"❌ Account not found for '{item.get('original', text)}'")
                elif save_res["error"] == "card_limit_exceeded":
                    responses.append(
                        "⚠️ Траты по картам свыше 150 ₪ вносятся только через загрузку выписки." if lang == 'ru'
                        else "⚠️ Manual entry for bank cards over 150 is restricted. Please use bank statements."
                    )
                else:
                    responses.append(f"❌ Error: {save_res['error']} for '{item.get('original', text)}'")
                continue
                
            if save_res.get("id"):
                inserted_ids.append(str(save_res["id"]))
                
            db_amount = save_res["db_amount"]
            status = save_res["status"]
            
            comment = item.get('comment')
            item_name = item.get('item_name', '')
            category_id = item.get('category_id')
            
            comment_text = f" ({comment})" if comment else ""
            formatted_amount = f"{db_amount:+.2f} ₪"
            
            pending_note = ""
            if status == 'pending':
                pending_note = " (⚠️ Ожидает выписки. Важно: проверьте точность суммы!)" if lang == 'ru' else " (⚠️ Pending bank statement. Verify amount!)"
                
            if category_id:
                responses.append(f"✅ {item_name}: {formatted_amount}{comment_text}{pending_note}")
            else:
                warning_text = " (категория не задана)" if lang == 'ru' else " (category missing)"
                responses.append(f"❓ {item_name}: {formatted_amount}{comment_text}{warning_text}{pending_note}")
            
            total_amount += db_amount

    # The block above has committed, so the entries are saved before we say so.
    if responses:
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        
        reply_text = "\n".join(responses)
        if len(inserted_ids) > 1:
            total_label = "Итого:" if lang == 'ru' else "Total:"
            reply_text += f"\n\n<b>{total_label}</b> {total_amount:+.2f} ₪"

        if inserted_ids:
            keyboard = [
                [InlineKeyboardButton(get_text("edit_records_button", lang), callback_data=f"edit_main:{','.join(inserted_ids)}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(reply_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(reply_text, parse_mode='HTML')
