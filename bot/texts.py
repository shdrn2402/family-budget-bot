MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "access_denied": "Sorry, this bot is private.",
        "admin_only": "⛔ This command is available to admins only.",
        "parse_error": "Nothing was saved. Format: 'item account amount [comment]', several items separated by commas, e.g. 'coffee cash 15, bus card 6'",
        "voice_not_supported": "🎙 Voice messages aren't supported. Please send the expense as text, e.g. 'coffee cash 15'.",
        "item_parse_error": "❌ Error in '{original}': check format.",
        "account_not_found": "❌ Account '{alias}' not found for '{original}'",
        "expense_saved": "✅ {item} ({amount}) saved to account {account}. [{cat_status}]",
        "category_found": "Category found",
        "category_not_found": "⚠️ Category not found",
        "database_error": "An error occurred while saving to the database.",
        "total_saved": "💰 Total saved: {amount}",
        "edit_records_button": "⚙️ Edit Records",
        "close_menu": "🔙 Close Menu",
        "cancel": "🔙 Cancel",
        "change_category": "🏷 Change Category",
        "delete": "❌ Delete",
        "record_deleted": "🗑 Record deleted!",
        "unexpected_error_alert": "An error occurred",
        "history_empty": "Transaction history is empty.",
        "history_header": "📊 Last 10 transactions:",
        "category_saved": "✅ Category successfully saved!",
        "import_invalid_extension": "Please send an Excel or CSV file (.xls, .xlsx, .csv)",
        "import_status_received": "⏳ Received {count} file(s). Preparing to process...",
        "import_status_processing": "⏳ Processing {count} file(s)...",
        "import_report_success": "✅ <b>Import complete!</b>\n\n📥 Total found: {total_count}\n✨ New records: {inserted_count}\n⏭ Duplicates skipped: {duplicates}",
        "import_report_errors": "\n\n⚠️ <b>Errors during file processing:</b>",
        "import_no_transactions": "❌ Could not recognize data in the statement files.",
        "import_bit_no_card": "Bit export needs your own card account. Link it with /start, then send the file again."
    },
    "ru": {
        "access_denied": "Извините, этот бот приватный и работает только для моей семьи.",
        "admin_only": "⛔ Эта команда доступна только администраторам.",
        "parse_error": "Ничего не сохранено. Формат: 'товар счёт сумма [комментарий]', несколько через запятую, например 'кофе нал 15, автобус карта 6'",
        "voice_not_supported": "🎙 Голосовые сообщения не поддерживаются. Отправьте трату текстом, например 'кофе нал 15'.",
        "item_parse_error": "❌ Ошибка в '{original}': проверьте формат.",
        "account_not_found": "❌ Не найден счет для '{alias}' в '{original}'",
        "expense_saved": "✅ {item} ({amount}) сохранен на счет {account}. [{cat_status}]",
        "category_found": "Категория найдена",
        "category_not_found": "⚠️ Категория не найдена",
        "database_error": "Произошла ошибка при сохранении в базу данных.",
        "total_saved": "💰 Итого сохранено: {amount}",
        "edit_records_button": "⚙️ Редактировать записи",
        "close_menu": "🔙 Закрыть меню",
        "cancel": "🔙 Отмена",
        "change_category": "🏷 Изменить категорию",
        "delete": "❌ Удалить",
        "record_deleted": "🗑 Запись удалена!",
        "unexpected_error_alert": "Произошла ошибка",
        "history_empty": "История транзакций пуста.",
        "history_header": "📊 Последние 10 транзакций:",
        "category_saved": "✅ Категория успешно сохранена!",
        "import_invalid_extension": "Пожалуйста, пришлите файл в формате Excel или CSV (.xls, .xlsx, .csv)",
        "import_status_received": "⏳ Получено файлов: {count}. Подготовка к обработке...",
        "import_status_processing": "⏳ Обрабатываю {count} файл(ов)...",
        "import_report_success": "✅ <b>Импорт завершен!</b>\n\n📥 Всего найдено: {total_count}\n✨ Добавлено новых: {inserted_count}\n⏭ Пропущено дубликатов: {duplicates}",
        "import_report_errors": "\n\n⚠️ <b>Ошибки при обработке файлов:</b>",
        "import_no_transactions": "❌ Не удалось распознать данные в файлах выписок.",
        "import_bit_no_card": "Для выписки Bit нужен ваш собственный счёт карты. Привяжите его через /start и отправьте файл снова."
    }
}

def get_text(key: str, lang_code: str | None = "ru", **kwargs: str) -> str:
    """
    Retrieve translated text by key.
    Fallback to English if language is not supported.
    """
    if not lang_code:
        lang_code = "en"
    lang: str = lang_code if lang_code in MESSAGES else "en"
    text: str = MESSAGES[lang].get(key, f"Missing text for {key}")
    if kwargs:
        return text.format(**kwargs)
    return text
