"""
openai_provider.py

OpenAI implementation of the LLMProvider interface.

Purpose
-------
This module implements the adapter responsible for communicating with
OpenAI language models.

The implementation isolates all OpenAI-specific logic from the rest of
the application, ensuring that the application layer depends only on the
abstract LLMProvider interface.

Current Status
--------------
Skeleton implementation.

The API integration will be implemented in a future milestone.

Author
------
Guillermo Ramajo Fernández
"""

from app.domain.models.prompt import Prompt
from app.domain.models.llm_response import LLMResponse

from app.infrastructure.llm.base_provider import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using an OpenAI model.
        """
        raise NotImplementedError