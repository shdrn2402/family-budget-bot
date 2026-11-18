from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _callback_update(data: str) -> MagicMock:
    update = MagicMock()
    update.callback_query = AsyncMock()
    update.callback_query.data = data
    update.effective_user.language_code = "en"
    return update


@pytest.mark.asyncio
async def test_inline_menu_rejects_users_without_access() -> None:
    """A user who fails the access check must not reach any callback action."""
    from bot.handlers.inline_menu import inline_menu_handler

    update = _callback_update("delete_tx:99:99,100:")

    with patch("bot.handlers.inline_menu.check_access", new_callable=AsyncMock) as mock_access, \
         patch("bot.handlers.inline_menu.get_db_connection") as mock_db:
        mock_access.return_value = False
        await inline_menu_handler(update, MagicMock())

    mock_db.assert_not_called()
    update.callback_query.edit_message_reply_markup.assert_not_called()
    update.callback_query.answer.assert_awaited_once()
    assert update.callback_query.answer.call_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_inline_menu_allows_users_with_access() -> None:
    """Allowed users still get the normal flow (here: the no-op 'ignore' button)."""
    from bot.handlers.inline_menu import inline_menu_handler

    update = _callback_update("ignore")

    with patch("bot.handlers.inline_menu.check_access", new_callable=AsyncMock) as mock_access:
        mock_access.return_value = True
        await inline_menu_handler(update, MagicMock())

    update.callback_query.answer.assert_awaited_once_with()


def _command_update() -> MagicMock:
    update = MagicMock()
    update.effective_user.id = 42
    update.effective_user.language_code = "en"
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_backup_is_refused_for_non_admin() -> None:
    """/backup sends a full database dump, so only admins may run it."""
    from bot.handlers.admin import backup_handler
    from bot.texts import get_text

    update = _command_update()

    with patch("bot.handlers.admin.check_access", new_callable=AsyncMock, return_value=True), \
         patch("bot.handlers.admin.get_user_info", new_callable=AsyncMock,
               return_value={"id": 42, "name": "x", "is_admin": False}), \
         patch("bot.handlers.admin.create_database_dump", new_callable=AsyncMock) as mock_dump:
        await backup_handler(update, MagicMock())

    mock_dump.assert_not_called()
    update.message.reply_text.assert_awaited_once_with(get_text("admin_only", "en"))


@pytest.mark.asyncio
async def test_backup_is_refused_when_user_info_is_unavailable() -> None:
    """If the user record can't be loaded, fail closed."""
    from bot.handlers.admin import backup_handler

    update = _command_update()

    with patch("bot.handlers.admin.check_access", new_callable=AsyncMock, return_value=True), \
         patch("bot.handlers.admin.get_user_info", new_callable=AsyncMock, return_value=None), \
         patch("bot.handlers.admin.create_database_dump", new_callable=AsyncMock) as mock_dump:
        await backup_handler(update, MagicMock())

    mock_dump.assert_not_called()


@pytest.mark.asyncio
async def test_backup_runs_for_admin() -> None:
    from bot.handlers.admin import backup_handler

    update = _command_update()
    status_message = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_message)

    with patch("bot.handlers.admin.check_access", new_callable=AsyncMock, return_value=True), \
         patch("bot.handlers.admin.get_user_info", new_callable=AsyncMock,
               return_value={"id": 42, "name": "x", "is_admin": True}), \
         patch("bot.handlers.admin.create_database_dump", new_callable=AsyncMock,
               return_value=None) as mock_dump, \
         patch("bot.handlers.admin.export_aliases_to_yaml", new_callable=AsyncMock, return_value=None):
        await backup_handler(update, MagicMock())

    mock_dump.assert_awaited_once()
