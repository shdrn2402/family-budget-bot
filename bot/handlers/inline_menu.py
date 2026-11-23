import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from bot.handlers.common import check_access
from bot.services.expense import resolve_amount_sign
from db import aliases, categories, pool, transactions

from bot.texts import get_text

logger = logging.getLogger(__name__)

async def inline_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline keyboard callback queries."""
    query = update.callback_query
    user_lang = update.effective_user.language_code if update.effective_user else None

    # Callback buttons can be pressed by anyone who sees the message, so check access here too.
    if not await check_access(update):
        await query.answer(get_text("access_denied", user_lang), show_alert=True)
        return

    await query.answer()  # Tell Telegram we received the click
    
    data = query.data
    
    if data == "ignore":
        return
    
    try:
        # 1. History Pagination
        if data.startswith("hist_page:"):
            from bot.handlers.history import build_history_page
            page = int(data.split(":")[1])
            text, reply_markup = await build_history_page(update.effective_user.id, user_lang, page)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            return

        # 1b. Account Binding
        elif data.startswith("link_acc:"):
            from bot.handlers.common import link_account_callback_handler
            await link_account_callback_handler(update, context)
            return

        # 2. Main Edit Menu (List of transactions)
        if data.startswith("edit_main:"):
            parts = data.split(":")
            tx_ids_str = parts[1]
            page = parts[2] if len(parts) > 2 else None
            
            tx_ids = [int(x) for x in tx_ids_str.split(",") if x.strip()]
            if not tx_ids:
                await query.edit_message_reply_markup(reply_markup=None)
                return
                
            async with pool.connection() as conn:
                rows = await transactions.list_by_ids(conn, tx_ids)

            keyboard = []
            for tx in rows:
                # Pass both the context IDs and page to the next level
                keyboard.append([InlineKeyboardButton(
                    f"📝 {tx['description'].capitalize()} ({tx['amount']})", 
                    callback_data=f"edit_tx:{tx['id']}:{tx_ids_str}:{page or ''}"
                )])
            
            # Back/Close button
            if page is not None and page != "":
                # Go back to history list
                keyboard.append([InlineKeyboardButton(get_text("close_menu", user_lang), callback_data=f"hist_page:{page}")])
            else:
                # Just close (or minimize back to edit button)
                keyboard.append([InlineKeyboardButton(get_text("close_menu", user_lang), callback_data=f"minimize:{tx_ids_str}")])
                
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif data.startswith("minimize:"):
            tx_ids_str = data.split(":")[1]
            keyboard = [[InlineKeyboardButton(get_text("edit_records_button", user_lang), callback_data=f"edit_main:{tx_ids_str}")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

        # 3. Transaction Actions (Change Category / Delete)
        elif data.startswith("edit_tx:"):
            _, tx_id, tx_ids_str, page = data.split(":")
            
            lang = user_lang or "ru"
            rename_text = "✏️ Изменить название" if lang == 'ru' else "✏️ Edit name"
            reprice_text = "💰 Изменить сумму" if lang == 'ru' else "💰 Edit amount"
            
            keyboard = [
                [InlineKeyboardButton(get_text("change_category", user_lang), callback_data=f"set_cat:{tx_id}:{tx_ids_str}:{page}")],
                [InlineKeyboardButton(rename_text, callback_data=f"rename_tx:{tx_id}:{tx_ids_str}:{page}")],
                [InlineKeyboardButton(reprice_text, callback_data=f"reprice_tx:{tx_id}:{tx_ids_str}:{page}")],
                [InlineKeyboardButton(get_text("delete", user_lang), callback_data=f"delete_tx:{tx_id}:{tx_ids_str}:{page}")],
                [InlineKeyboardButton("⬅️ " + get_text("cancel", user_lang), callback_data=f"edit_main:{tx_ids_str}:{page}")]
            ]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif data.startswith("delete_tx:"):
            _, tx_id, tx_ids_str, page = data.split(":")
            async with pool.connection() as conn:
                await transactions.delete(conn, int(tx_id))
            
            await query.answer(get_text("record_deleted", user_lang))
            
            # Remove this ID from the list and go back
            remaining_ids = [x for x in tx_ids_str.split(",") if x != tx_id]
            if remaining_ids:
                new_ids_str = ",".join(remaining_ids)
                # Offer a button back to the remaining records.
                keyboard = [[InlineKeyboardButton("⬅️ " + get_text("close_menu", user_lang), callback_data=f"edit_main:{new_ids_str}:{page}")]]
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                # No more items, go back to history if possible
                if page:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ " + get_text("close_menu", user_lang), callback_data=f"hist_page:{page}")]
                    ]))
                else:
                    await query.edit_message_reply_markup(reply_markup=None)
            
        elif data.startswith("rename_tx:"):
            _, tx_id, tx_ids_str, page = data.split(":")
            lang = user_lang or "ru"
            prompt_text = (
                f"Пожалуйста, напишите новое название в ответ на это сообщение.\n[ID: {tx_id}]"
                if lang == 'ru' else
                f"Please write the new name as a reply to this message.\n[ID: {tx_id}]"
            )
            from telegram import ForceReply
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=prompt_text,
                reply_markup=ForceReply(selective=True)
            )
            await query.answer()

        elif data.startswith("reprice_tx:"):
            _, tx_id, tx_ids_str, page = data.split(":")
            lang = user_lang or "ru"
            prompt_text = (
                f"Пожалуйста, напишите новую сумму в ответ на это сообщение.\n[ID_SUM: {tx_id}]"
                if lang == 'ru' else
                f"Please write the new amount as a reply to this message.\n[ID_SUM: {tx_id}]"
            )
            from telegram import ForceReply
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=prompt_text,
                reply_markup=ForceReply(selective=True)
            )
            await query.answer()
            
        elif data.startswith("set_cat:"):
            _, tx_id, tx_ids_str, page = data.split(":")
            lang = user_lang or "ru"
            
            async with pool.connection() as conn:
                leaves = await categories.list_leaves(conn)

            keyboard = []
            row = []
            current_parent = None

            for cat in leaves:
                # get parent name
                p_name_dict = cat['parent_name']
                p_name = p_name_dict.get(lang, p_name_dict.get('ru', p_name_dict.get('en', 'Unknown')))
                
                if p_name != current_parent:
                    if row:
                        keyboard.append(row)
                        row = []
                    # Add parent separator
                    keyboard.append([InlineKeyboardButton(f"--- {p_name.upper()} ---", callback_data="ignore")])
                    current_parent = p_name
                    
                name_dict = cat['name']
                cat_name = name_dict.get(lang, name_dict.get('ru', name_dict.get('en', 'Unknown')))
                row.append(InlineKeyboardButton(cat_name, callback_data=f"save_cat:{tx_id}:{cat['id']}:{tx_ids_str}:{page}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
                
            keyboard.append([InlineKeyboardButton("⬅️ " + get_text("cancel", user_lang), callback_data=f"edit_tx:{tx_id}:{tx_ids_str}:{page}")])
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif data.startswith("save_cat:"):
            _, tx_id, cat_id, tx_ids_str, page = data.split(":")
            lang = user_lang or "ru"
            cat_id_int = int(cat_id)

            # Known issue #37: this also rewrites the merchant rule for future imports.
            async with pool.connection() as conn:
                tx = await transactions.get(conn, int(tx_id))
                if tx:
                    parent_id = await categories.get_parent_id(conn, cat_id_int)
                    new_amount = resolve_amount_sign(tx['amount'], parent_id)
                    await transactions.set_category(conn, tx['id'], cat_id_int, new_amount)

                    alias_name = f"{tx['description'] or ''} {tx['comment'] or ''}".strip()
                    if alias_name:
                        await aliases.learn(conn, alias_name, cat_id_int, tx['user_id'])

            confirm_text = get_text("category_saved", lang)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=confirm_text)
            
            # Go back to transaction actions
            keyboard = [[InlineKeyboardButton("⬅️ " + get_text("close_menu", user_lang), callback_data=f"edit_tx:{tx_id}:{tx_ids_str}:{page}")]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

            
    except Exception as e:
        logger.error(f"Error in inline menu: {e}")
        await query.answer(get_text("unexpected_error_alert", user_lang), show_alert=True)
