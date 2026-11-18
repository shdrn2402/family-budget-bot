import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from bot.config import Config


def _gemini_response(text: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json = lambda: {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return response


def _assert_key_sent_in_header_only(mock_post: MagicMock) -> None:
    mock_post.assert_called_once()
    url: str = mock_post.call_args.args[0]
    headers: dict[str, str] = mock_post.call_args.kwargs.get("headers", {})
    assert "key=" not in url, "API key must not be part of the request URL"
    assert Config.GEMINI_API_KEY not in url
    assert headers.get("x-goog-api-key") == Config.GEMINI_API_KEY


def test_httpx_request_logging_is_silenced() -> None:
    """httpx logs full request URLs at INFO; Telegram puts the bot token in the URL."""
    import bot.main  # noqa: F401  (importing configures logging)

    # Check the level set on the logger itself: the effective level would depend on
    # the root logger, which pytest configures differently from production.
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level >= logging.WARNING


@pytest.mark.asyncio
async def test_parse_natural_language_sends_key_in_header() -> None:
    from bot.services.llm import parse_natural_language

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _gemini_response(json.dumps({"items": []}))
        await parse_natural_language("coffee cash 5")
    _assert_key_sent_in_header_only(mock_post)


@pytest.mark.asyncio
async def test_translate_question_to_sql_sends_key_in_header() -> None:
    from bot.services.llm import translate_question_to_sql

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _gemini_response(
            json.dumps({"sql": "SELECT 1", "explanation": "", "is_safe": True})
        )
        await translate_question_to_sql("how much?", user_id=1)
    _assert_key_sent_in_header_only(mock_post)


@pytest.mark.asyncio
async def test_generate_answer_from_data_sends_key_in_header() -> None:
    from bot.services.llm import generate_answer_from_data

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _gemini_response("answer")
        await generate_answer_from_data("how much?", [{"total": 1}])
    _assert_key_sent_in_header_only(mock_post)


@pytest.mark.asyncio
async def test_transcribe_voice_sends_key_in_header() -> None:
    from bot.services.voice import transcribe_voice

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _gemini_response("text")
        await transcribe_voice(b"fake_ogg_data")
    _assert_key_sent_in_header_only(mock_post)
