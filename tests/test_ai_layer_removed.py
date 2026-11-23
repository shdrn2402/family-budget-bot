"""
The AI layer (Gemini text parsing, voice transcription, NL2SQL) is removed (#20).
Text the fast parser can't read gets a format hint; voice messages get a "send text" reply.
"""
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.texts import MESSAGES, get_text

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", ["bot.services.llm", "bot.services.voice"])
def test_ai_modules_are_gone(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_config_has_no_gemini_key() -> None:
    from bot.config import Config

    assert not hasattr(Config, "GEMINI_API_KEY")


@pytest.mark.parametrize("path", ["compose.yaml", "env.example", ".github/workflows/deploy.yaml"])
def test_deploy_files_do_not_mention_gemini(path: str) -> None:
    assert "GEMINI" not in (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_matplotlib_is_not_a_dependency() -> None:
    for path in ("pyproject.toml", "uv.lock"):
        assert "matplotlib" not in (PROJECT_ROOT / path).read_text(encoding="utf-8"), path


def test_texts_for_removed_features_are_gone() -> None:
    removed = {"llm_failed", "transcribing_voice", "heard_voice", "echo_reply", "start_greeting",
               "category_updated", "db_error_alert", "manual_bank_entry_denied", "alias_added",
               "analytics_analyzing", "analytics_translation_error", "analytics_unsafe_query",
               "analytics_general_error"}
    for lang, messages in MESSAGES.items():
        assert removed.isdisjoint(messages), lang


def test_every_text_exists_in_both_languages() -> None:
    assert set(MESSAGES["en"]) == set(MESSAGES["ru"])


# --- Replies --------------------------------------------------------------------------

def _update(lang: str = "en") -> MagicMock:
    update = MagicMock()
    update.message = AsyncMock()
    update.message.reply_to_message = None
    update.effective_user.id = 123
    update.effective_user.language_code = lang
    return update


async def test_voice_message_gets_a_send_text_reply() -> None:
    from bot.handlers.voice import voice_message_handler

    update = _update("ru")
    with patch("bot.handlers.voice.check_access", new_callable=AsyncMock, return_value=True):
        await voice_message_handler(update, MagicMock())

    update.message.reply_text.assert_called_once_with(get_text("voice_not_supported", "ru"))


async def test_voice_message_from_a_stranger_is_ignored() -> None:
    from bot.handlers.voice import voice_message_handler

    update = _update()
    with patch("bot.handlers.voice.check_access", new_callable=AsyncMock, return_value=False):
        await voice_message_handler(update, MagicMock())

    update.message.reply_text.assert_not_called()


async def test_unparseable_text_gets_a_format_hint_and_nothing_is_saved() -> None:
    from bot.handlers.expense import expense_message_handler

    update = _update()
    update.message.text = "lonely, coffee nosuchaccount 5"
    errors = [
        {"original": "lonely", "error": "not_enough_words"},
        {"original": "coffee nosuchaccount 5", "error": "unknown_account", "account_alias": "nosuchaccount"},
    ]
    with patch("bot.handlers.expense.check_access", new_callable=AsyncMock, return_value=True), \
         patch("bot.handlers.expense.process_expense_text", new_callable=AsyncMock, return_value=errors), \
         patch("bot.handlers.expense.save_expense_item", new_callable=AsyncMock) as mock_save:
        await expense_message_handler(update, MagicMock())

    mock_save.assert_not_called()
    update.message.reply_text.assert_called_once()
    reply: str = update.message.reply_text.call_args.args[0]
    assert get_text("item_parse_error", "en", original="lonely") in reply
    assert get_text("account_not_found", "en", alias="nosuchaccount", original="coffee nosuchaccount 5") in reply
    assert reply.endswith(get_text("parse_error", "en"))
