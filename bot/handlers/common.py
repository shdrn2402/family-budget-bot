import logging
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from bot.config import Config
from bot.texts import get_text
from db import accounts, pool, users

logger = logging.getLogger(__name__)

async def check_access(update: Update) -> bool:
    """
    Check if user is allowed to use the bot.
    First checks database, then falls back to ALLOWED_USER_IDS from .env
    and auto-registers the user if they are in the allowed list.
    """
    if not update.effective_user:
        return False
        
    user_id: int = update.effective_user.id

    try:
        async with pool.connection() as conn:
            if await users.exists(conn, user_id):
                return True
            if user_id in Config.ALLOWED_USER_IDS:
                await _register_allowed_user(conn, user_id, update.effective_user.first_name)
                return True
    except Exception:
        # Fail closed: without the database we can't tell who may use the bot.
        logger.exception(f"Database error checking access for user {user_id}")
        return False

    logger.warning(f"Unauthorized access attempt by ID {user_id}")
    lang_code: str | None = update.effective_user.language_code
    if update.message:
        await update.message.reply_text(get_text("access_denied", lang_code))
    return False


def _match_account_by_name(free_accounts: list[dict], telegram_name: str) -> dict | None:
    """The free account whose English or Russian name equals the Telegram first name (any case)."""
    tg_name_lower = telegram_name.lower()
    for acc in free_accounts:
        if tg_name_lower in (acc['name'].get('en', '').lower(), acc['name'].get('ru', '').lower()):
            return acc
    return None


async def _register_allowed_user(conn, user_id: int, first_name: str | None) -> None:
    """Register a user from ALLOWED_USER_IDS (the first one is the admin) and link their account by name."""
    logger.info(f"Auto-registering allowed user {user_id}")
    name: str = first_name or f"User {user_id}"
    is_admin: bool = user_id == Config.ALLOWED_USER_IDS[0]
    await users.register(conn, user_id, name, is_admin=is_admin)

    acc = _match_account_by_name(await accounts.list_unlinked_cards(conn), name)
    if acc and await accounts.claim(conn, user_id, acc['id']):
        logger.info(f"Auto-linked user {user_id} to account {acc['id']}")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command with automated or manual account linking."""
    if not await check_access(update) or not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    lang = update.effective_user.language_code or 'ru'
    
    telegram_name = update.effective_user.first_name or ""

    async with pool.connection() as conn:
        # 1. Check if user already has a linked account
        linked_account = await accounts.find_linked(conn, user_id)
        if not linked_account:
            # 2. Attempt auto-recognition (case-insensitive first name check) among the free accounts
            free_accounts = await accounts.list_unlinked_cards(conn)
            matched_account = _match_account_by_name(free_accounts, telegram_name)
            linked_now = bool(matched_account) and await accounts.claim(conn, user_id, matched_account['id'])

    if linked_account:
        account_name = linked_account['name'].get(lang, linked_account['name'].get('ru'))
        reply_text = (
            f"👋 С возвращением, {account_name}!\nЯ готов записывать ваши расходы."
            if lang == 'ru' else f"👋 Welcome back, {account_name}!\nI'm ready to track your expenses."
        )
        await update.message.reply_text(reply_text)
        return

    if matched_account:
        if linked_now:
            acc_name = matched_account['name'].get(lang, matched_account['name'].get('ru'))
            reply_text = (
                f"🎉 Ура! Я автоматически распознал ваш профиль и привязал вас к счету <b>«{acc_name}»</b>.\n"
                f"Теперь ваши расходы будут записываться на этот счет."
                if lang == 'ru' else
                f"🎉 Great! I automatically recognized your profile and linked you to the account <b>«{acc_name}»</b>.\n"
                f"Your expenses will now be recorded under this account."
            )
            await update.message.reply_text(reply_text, parse_mode='HTML')
            return

    # 4. Fallback: Show interactive choices
    if not free_accounts:
        reply_text = (
            "⚠️ Все доступные персональные счета в вашей семье уже заняты.\n"
            "Пожалуйста, обратитесь к главе семьи для добавления нового счета."
            if lang == 'ru' else
            "⚠️ All available accounts in your family are already linked.\n"
            "Please ask the family head to add a new account."
        )
        await update.message.reply_text(reply_text)
        return

    keyboard = []
    for acc in free_accounts:
        acc_name = acc['name'].get(lang, acc['name'].get('ru'))
        keyboard.append([InlineKeyboardButton(f"👤 {acc_name}", callback_data=f"link_acc:{acc['id']}")] )

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    reply_text = (
        "🔍 Я не смог автоматически распознать ваш профиль.\n"
        "Пожалуйста, выберите ваш аккаунт из списка ниже:"
        if lang == 'ru' else
        "🔍 I couldn't automatically recognize your profile.\n"
        "Please select your account from the list below:"
    )
    await update.message.reply_text(reply_text, reply_markup=reply_markup)


async def link_account_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback button click for linking account."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = query.from_user.id
    lang = query.from_user.language_code or 'ru'
    
    account_id = int(query.data.split(":")[1])

    try:
        async with pool.connection() as conn:
            success = await accounts.claim(conn, user_id, account_id)
            name = await accounts.get_name(conn, account_id) if success else None
    except Exception:
        logger.exception(f"Database error linking user {user_id} to account {account_id}")
        success = False

    if success:
        acc_name = name.get(lang, name.get('ru')) if name else ""
        
        reply_text = (
            f"✅ Успешно! Вы связали свой Telegram со счетом <b>«{acc_name}»</b>.\n"
            f"Теперь ваши расходы будут записываться на этот счет."
            if lang == 'ru' else
            f"✅ Success! You have linked your Telegram with the account <b>«{acc_name}»</b>.\n"
            f"Your expenses will now be recorded under this account."
        )
        await query.edit_message_text(reply_text, parse_mode='HTML')
    else:
        reply_text = (
            "❌ Ошибка: этот счет уже был привязан кем-то другим, либо произошел сбой базы данных.\n"
            "Пожалуйста, запустите команду /start заново."
            if lang == 'ru' else
            "❌ Error: this account has already been linked by someone else, or a database error occurred.\n"
            "Please run /start again."
        )
        await query.edit_message_text(reply_text)
