"""
environment.py

Enumeration of application environments.

Purpose
-------
Applications typically behave differently depending on the deployment
environment.

Examples include enabling debug mode during development, using different
databases for testing, or disabling verbose logging in production.

This module centralizes the supported runtime environments.

Author
------
Guillermo Ramajo Fernández
"""

from enum import StrEnum


class EnvironmentEnum(StrEnum):
    """
    Supported application environments.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"