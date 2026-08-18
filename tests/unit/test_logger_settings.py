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