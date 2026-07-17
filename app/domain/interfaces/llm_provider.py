"""
llm_provider.py

Abstract interface implemented by every Large Language Model provider.

The objective of this interface is to isolate the application layer from
vendor-specific SDKs such as OpenAI, Anthropic, Azure OpenAI, Gemini,
or Ollama.

Only the infrastructure layer should know how to communicate with
external APIs.

Application services interact exclusively with this interface.

This follows the Dependency Inversion Principle (SOLID) and allows
providers to be replaced without modifying business logic.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models.prompt import Prompt
from app.domain.models.llm_response import LLMResponse


class LLMProvider(ABC):
    """
    Abstract interface for every Large Language Model.

    Implementations are responsible for:

    - Authentication
    - API communication
    - Retries
    - Rate limiting
    - Error translation
    - Response normalization

    They are NOT responsible for deciding *what* should be generated.
    That belongs to the application layer.
    """

    @abstractmethod
    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion for the supplied prompt.

        Parameters
        ----------
        prompt
            Structured prompt describing the generation task.

        Returns
        -------
        LLMResponse
            Normalized response independent of the underlying provider.

        Raises
        ------
        LLMProviderError
            If the provider fails to generate a response.
        """
        raise NotImplementedError