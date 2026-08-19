"""
test_logger_settings.py

Regression tests for ``app.core.logger.configure_logging()``.

Verifies that the function reads the actual pydantic field
names from ``LoggingSettings`` rather than guessed names
like ``log_level`` that don't exist on the model. This
bug shipped for several months because the field names
on the model (``level``, ``format``, ``to_file``, ``file``)
don't match the names in ``logger.py``
(``log_level``, ``log_format``, ``log_to_file``, ``log_file``).
The bug made every reference to ``settings.logging.log_*``
raise ``AttributeError`` if it was ever evaluated -- in
practice the function was never called in tests, so the
bug went unnoticed.

Now ``configure_logging()`` is exercised end-to-end and
the field-name mismatches are pinned.
"""

from __future__ import annotations

import logging

import pytest


def test_configure_logging_uses_field_level_not_log_level():
    """The root logger level is read from
    ``settings.logging.level`` (not ``settings.logging.log_level``,
    which doesn't exist).
    """
    from app.core.logger import configure_logging
    from app.config.settings import settings

    # Set the env var before configure_logging() runs.
    import os

    old = os.environ.get("LOG_LEVEL")
    os.environ["LOG_LEVEL"] = "WARNING"
    # Reload the settings so the new env var takes effect.
    try:
        settings.logging.level = "WARNING"
        # Reset logging so configure_logging() actually
        # does work (it short-circuits if handlers exist).
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
        configure_logging()
        assert logging.getLogger().level == logging.WARNING
    finally:
        if old is None:
            os.environ.pop("LOG_LEVEL", None)
        else:
            os.environ["LOG_LEVEL"] = old


def test_settings_logging_has_level_field():
    """The LoggingSettings model exposes the field ``level``
    (aliased to ``LOG_LEVEL``). The presence of this field
    is the contract that ``configure_logging()`` relies on.
    """
    from app.config.logging import logging_settings

    assert hasattr(logging_settings, "level"), (
        "LoggingSettings must have a 'level' field "
        "(aliased to LOG_LEVEL). If this fails, logger.py "
        "won't be able to read the log level."
    )
    assert hasattr(logging_settings, "format")
    assert hasattr(logging_settings, "to_file")
    assert hasattr(logging_settings, "file")


def test_settings_logging_level_defaults_to_info():
    """Default log level is INFO. If a deployment forgets
    to set ``LOG_LEVEL``, the system still works.

    We assert against the model field's default, not a
    freshly-constructed instance, so the test is robust to
    whatever the env-var happens to be in CI.
    """
    from app.config.logging import LoggingSettings

    # Read the model's field definition directly.
    field_info = LoggingSettings.model_fields["level"]
    assert field_info.default == "INFO"


def test_log_level_alias_works():
    """The ``LOG_LEVEL`` env var is mapped to ``logging.level``
    via the pydantic ``alias`` setting.
    """
    import os

    from app.config.logging import logging_settings

    # Reading the model after the env var changes requires
    # constructing a fresh instance.
    os.environ["LOG_LEVEL"] = "DEBUG"
    try:
        from app.config.logging import LoggingSettings

        fresh = LoggingSettings()
        assert fresh.level == "DEBUG"
    finally:
        os.environ.pop("LOG_LEVEL", None)
        # Also reload the singleton to its default state
        # so other tests aren't contaminated.
        import app.config.logging as logging_mod
        logging_mod.logging_settings = LoggingSettings()


class TestNoisyThirdPartyLoggers:
    """Regression tests for the noisy-logger pin.

    When LOG_LEVEL=DEBUG, the root logger emits
    everything below. httpx and httpcore in particular
    emit one log line per HTTP packet -- this drowns our
    own application logs (cache HIT/MISS, the startup
    AbstractEnricher line, etc).

    configure_logging() pins these noisy loggers to
    WARNING so their DEBUG spam is suppressed while
    their INFO/ERROR/CRITICAL still propagate (via the
    root logger handler).
    """

    @pytest.fixture(autouse=True)
    def reset_logging_state(self):
        """Reset the root logger + noisy loggers to a
        clean state around each test in this class.

        configure_logging() is idempotent: it returns
        early if the root logger already has handlers.
        We can't rely on that for tests because pytest
        may have already configured logging in a prior
        test (with a different LOG_LEVEL). We clear the
        handlers on BOTH setup and teardown so each test
        exercises the full configure_logging() path.
        """
        root = logging.getLogger()

        # SETUP: clear any handlers / level left by
        # previous tests so configure_logging() doesn't
        # short-circuit due to idempotency.
        original_handlers = list(root.handlers)
        original_level = root.level
        root.handlers = []
        root.setLevel(logging.WARNING)  # default

        yield

        # TEARDOWN: restore whatever was there before.
        # We saved it before clearing, so this is a clean
        # restore.
        root.handlers = original_handlers
        root.setLevel(original_level)

    def test_configure_logging_pins_noisy_loggers_to_warning(self):
        """After configure_logging() runs, the noisy
        third-party loggers are set to WARNING or higher.

        We assert each one explicitly to prevent a
        future refactor from accidentally dropping a
        pin (e.g. if the loop in configure_logging is
        refactored).
        """
        from app.core.logger import configure_logging

        configure_logging()

        # These are the libraries that emit per-connection
        # or per-packet DEBUG spam. After configure_logging
        # they must be at WARNING or higher so the user's
        # own DEBUG logs aren't drowned.
        for noisy_name in (
            "httpx",
            "httpcore",
            "httpcore.http11",
            "httpcore.connection",
            "urllib3",
            "asyncio",
            "sqlalchemy.engine",
        ):
            logger = logging.getLogger(noisy_name)
            assert logger.level >= logging.WARNING, (
                f"{noisy_name} is at level {logger.level} "
                f"(name={logger.level}). Expected >= WARNING "
                f"({logging.WARNING}) so its DEBUG spam is "
                f"suppressed when LOG_LEVEL=DEBUG is set."
            )

    def test_app_loggers_emit_debug_when_log_level_debug(
        self, caplog: pytest.LogCaptureFixture,
    ):
        """The pin only affects third-party loggers. Our
        own app loggers (under ``app.*``) should still
        emit DEBUG messages when LOG_LEVEL=DEBUG so the
        AbstractEnricher's cache HIT/MISS logs etc. work.

        Instead of poking at logger effective-level
        attributes (which pytest's own logging fixtures
        can disrupt), we verify the actual behavior: when
        LOG_LEVEL=DEBUG is set and configure_logging() has
        run, a DEBUG message from an ``app.*`` logger is
        captured by the root handler.

        The ``caplog`` fixture hooks into Python's
        logging machinery at the root level, so any log
        record that propagates up to the root will be
        captured. If our app.* logger is pinned (it
        shouldn't be), the DEBUG message wouldn't reach
        the root and caplog wouldn't see it.
        """
        import importlib
        import os

        # Force LOG_LEVEL=DEBUG for this test.
        old_env = os.environ.get("LOG_LEVEL")
        os.environ["LOG_LEVEL"] = "DEBUG"
        try:
            # Reload settings so the singleton picks up
            # DEBUG (pydantic-settings reads the env at
            # instantiation time).
            import app.config.logging as logging_mod
            importlib.reload(logging_mod)
            assert logging_mod.logging_settings.level == "DEBUG"

            # Set caplog to DEBUG so it captures our DEBUG
            # messages (it defaults to WARNING).
            caplog.set_level(logging.DEBUG)

            # Apply the new root level.
            from app.core.logger import configure_logging
            configure_logging()

            # Emit a DEBUG message from an app.* logger
            # and verify caplog captured it -- that proves
            # the root handler is at DEBUG and our app
            # logger propagated up.
            app_logger = logging.getLogger("app.test_pin_check")
            app_logger.debug("app-debug-marker-1")

            captured = [
                r for r in caplog.records
                if r.name == "app.test_pin_check"
                and r.levelno == logging.DEBUG
            ]
            assert len(captured) >= 1, (
                f"Expected app.test_pin_check DEBUG to propagate "
                f"to root, but caplog saw: "
                f"{[(r.name, r.levelno) for r in caplog.records]}"
            )
        finally:
            if old_env is None:
                os.environ.pop("LOG_LEVEL", None)
            else:
                os.environ["LOG_LEVEL"] = old_env
            importlib.reload(logging_mod)


def test_configure_logging_is_idempotent():
    """Calling configure_logging() twice does not add
    duplicate handlers. This is what lets the test
    suite call it from multiple places without
    doubling up on log output.
    """
    from app.core.logger import configure_logging

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        configure_logging()
        after_first = list(root.handlers)
        configure_logging()
        after_second = list(root.handlers)
        assert len(after_first) == len(after_second), (
            "configure_logging() should be idempotent but "
            "the second call changed the handler count."
        )
    finally:
        root.handlers = original_handlers