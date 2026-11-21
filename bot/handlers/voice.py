from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.common import check_access
from bot.texts import get_text


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Voice input was removed with the AI layer (#20): ask for a text message instead."""
    if not await check_access(update):
        return
    await update.message.reply_text(get_text("voice_not_supported", update.effective_user.language_code))
