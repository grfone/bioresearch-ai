"""
base_provider.py

Base implementation for all Large Language Model (LLM) providers.

Purpose
-------
This module defines the common functionality shared by every concrete
LLM provider implementation.

While the Domain layer exposes the abstract ``LLMProvider`` interface,
this class provides reusable infrastructure behavior such as:

- Provider configuration
- Logging
- Retry policies
- Timeout management
- Request validation
- Response validation
- Exception translation

Concrete providers (e.g., OpenAI, Anthropic, Gemini, Ollama) should
inherit from this class and implement only the provider-specific API
communication.

This separation avoids code duplication while maintaining compliance
with the Dependency Inversion Principle.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC

from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.prompt import Prompt
from app.domain.models.llm_response import LLMResponse


class BaseLLMProvider(LLMProvider, ABC):
    """
    Base class for all LLM providers.

    This class contains behavior common to every provider while leaving
    the actual communication with external APIs to subclasses.

    Notes
    -----
    Concrete implementations should only override the ``generate()``
    method. Shared logic such as logging, validation, retries and
    configuration belongs here.
    """

    def __init__(self) -> None:
        """
        Initialize the provider.

        Future implementations may initialize:

        - Logger
        - Configuration
        - Retry strategy
        - Timeout policy
        - Authentication credentials
        """
        pass

    def validate_prompt(
        self,
        prompt: Prompt,
    ) -> None:
        """
        Validate a prompt before sending it to an LLM.

        Parameters
        ----------
        prompt
            Prompt to validate.

        Raises
        ------
        ValueError
            If the prompt is invalid.
        """
        if prompt is None:
            raise ValueError("Prompt cannot be None.")

    def validate_response(
        self,
        response: LLMResponse,
    ) -> None:
        """
        Validate a normalized LLM response.

        Parameters
        ----------
        response
            Response returned by the provider.

        Raises
        ------
        ValueError
            If the response is invalid.
        """
        if response is None:
            raise ValueError("LLM response cannot be None.")