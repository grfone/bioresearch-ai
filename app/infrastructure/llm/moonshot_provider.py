"""
moonshot_provider.py

Moonshot implementation of the LLMProvider interface.

Purpose
-------
This module implements the infrastructure adapter responsible for
communicating with Moonshot language models.

The implementation isolates all provider-specific communication from the
rest of the application, ensuring that business logic depends only on
the abstract ``LLMProvider`` interface.

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


class MoonshotProvider(BaseLLMProvider):
    """
    Moonshot implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using Moonshot.

        Parameters
        ----------
        prompt
            Structured prompt describing the task.

        Returns
        -------
        LLMResponse
            Normalized response independent of the provider.

        Raises
        ------
        NotImplementedError
            Raised until the provider implementation is completed.
        """
        raise NotImplementedError(
            "MoonshotProvider.generate() has not been implemented yet."
        )
