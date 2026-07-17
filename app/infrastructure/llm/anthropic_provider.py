"""
anthropic_provider.py

Anthropic implementation of the LLMProvider interface.

Purpose
-------
This module implements the infrastructure adapter responsible for
communicating with Anthropic Claude models.

The application layer remains completely independent of Anthropic APIs.

Current Status
--------------
Skeleton implementation.

Author
------
Guillermo Ramajo Fernández
"""

from app.domain.models.prompt import Prompt
from app.domain.models.llm_response import LLMResponse

from app.infrastructure.llm.base_provider import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using an Anthropic model.
        """
        raise NotImplementedError