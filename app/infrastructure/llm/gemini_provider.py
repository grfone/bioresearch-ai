"""
gemini_provider.py

Google Gemini implementation of the LLMProvider interface.

Purpose
-------
This module implements the adapter responsible for communicating with
Google Gemini language models.

The rest of the application remains provider-agnostic by interacting
only with the abstract LLMProvider interface.

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


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using a Gemini model.
        """
        raise NotImplementedError