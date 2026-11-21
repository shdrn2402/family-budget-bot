import logging


def test_httpx_request_logging_is_silenced() -> None:
    """httpx logs full request URLs at INFO; Telegram puts the bot token in the URL."""
    import bot.main  # noqa: F401  (importing configures logging)

    # Check the level set on the logger itself: the effective level would depend on
    # the root logger, which pytest configures differently from production.
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level >= logging.WARNING
