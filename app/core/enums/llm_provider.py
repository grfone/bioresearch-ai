"""
llm_provider.py

Enumeration of supported Large Language Model (LLM) providers.

Purpose
-------
This module defines the set of language model providers supported by
BioResearch AI.

Using an enumeration instead of raw strings provides:

- Type safety
- IDE auto-completion
- Prevention of typographical errors
- Easier validation
- Consistent provider naming throughout the application

This enumeration is primarily used by the infrastructure layer,
configuration system, and the LLM factory.

Author
------
Guillermo Ramajo Fernández
"""

from enum import StrEnum


class LLMProviderEnum(StrEnum):
    """
    Supported Large Language Model providers.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    LOCAL = "local"  # alias for OLLAMA used by the bootstrap GUI
    AZURE_OPENAI = "azure_openai"
    XAI = "xai"
    MISTRAL = "mistral"
    COHERE = "cohere"
    PERPLEXITY = "perplexity"
    BAIDU = "baidu"
    ALIBABA = "alibaba"
    TENCENT = "tencent"
    HUAWEI = "huawei"
    BYTEDANCE = "bytedance"
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    MOONSHOT = "moonshot"
    BAICHUAN = "baichuan"
    MINIMAX = "minimax"
    YI = "yi"
    SENSETIME = "sensetime"
    IFLYTEK = "iflytek"
    STEP_FUN = "step_fun"