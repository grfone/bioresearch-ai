"""
ollama_provider.py

Ollama implementation of the LLMProvider interface.

Purpose
-------
This module implements the adapter responsible for communicating with
locally hosted language models through Ollama.

Using Ollama allows BioResearch AI to operate with self-hosted,
privacy-preserving language models.

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


class OllamaProvider(BaseLLMProvider):
    """
    Ollama implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using an Ollama-hosted model.
        """
        raise NotImplementedError