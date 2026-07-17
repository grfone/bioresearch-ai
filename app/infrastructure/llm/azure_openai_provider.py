"""
azure_openai_provider.py

Azure OpenAI implementation of the LLMProvider interface.

Purpose
-------
This module implements the adapter responsible for communicating with
Azure-hosted OpenAI models.

Although Azure OpenAI exposes models similar to the OpenAI platform,
authentication, deployment configuration, and endpoint management differ.
Keeping this provider separate avoids mixing Azure-specific concerns
with the standard OpenAI implementation.

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


class AzureOpenAIProvider(BaseLLMProvider):
    """
    Azure OpenAI implementation of the LLM provider.
    """

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using an Azure OpenAI deployment.
        """
        raise NotImplementedError