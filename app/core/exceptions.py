"""
exceptions.py

Custom exception hierarchy for BioResearch AI.

Purpose
-------
This module defines the application's exception hierarchy.

Instead of propagating generic Python exceptions throughout the
application, components should raise meaningful domain-specific
exceptions that clearly communicate the nature of the failure.

Benefits
--------
- Improves readability.
- Simplifies exception handling.
- Decouples business logic from third-party libraries.
- Enables centralized error handling.
- Provides a stable public exception API.

Hierarchy
---------

Exception
│
└── BioResearchAIError
    ├── ConfigurationError
    ├── ValidationError
    ├── NotFoundError
    ├── AuthenticationError
    │
    ├── DomainError
    ├── ApplicationError
    │
    ├── InfrastructureError
    │   ├── DatabaseError
    │   ├── PubMedError
    │   ├── LLMProviderError
    │   ├── MCPError
    │   └── A2AError
    │
    └── AgentError

Author
------
Guillermo Ramajo Fernández
"""


class BioResearchAIError(Exception):
    """
    Base exception for the BioResearch AI application.

    Every custom exception defined by the project should inherit,
    directly or indirectly, from this class.
    """


# ---------------------------------------------------------------------
# General Exceptions
# ---------------------------------------------------------------------


class ConfigurationError(BioResearchAIError):
    """
    Raised when the application configuration is invalid.
    """


class ValidationError(BioResearchAIError):
    """
    Raised when input validation fails.
    """


class NotFoundError(BioResearchAIError):
    """
    Raised when a requested resource cannot be found.
    """


class AuthenticationError(BioResearchAIError):
    """
    Raised when authentication with an external service fails.
    """


# ---------------------------------------------------------------------
# Domain Layer
# ---------------------------------------------------------------------


class DomainError(BioResearchAIError):
    """
    Raised when a domain rule or business invariant is violated.
    """


# ---------------------------------------------------------------------
# Application Layer
# ---------------------------------------------------------------------


class ApplicationError(BioResearchAIError):
    """
    Raised when an application use case cannot be completed.
    """


# ---------------------------------------------------------------------
# Infrastructure Layer
# ---------------------------------------------------------------------


class InfrastructureError(BioResearchAIError):
    """
    Base class for infrastructure-related failures.
    """


class DatabaseError(InfrastructureError):
    """
    Raised when a database operation fails.
    """


class PubMedError(InfrastructureError):
    """
    Raised when communication with PubMed fails.
    """


class LLMProviderError(InfrastructureError):
    """
    Raised when an LLM provider cannot complete a request.
    """


class MCPError(InfrastructureError):
    """
    Raised when an MCP operation fails.
    """


class A2AError(InfrastructureError):
    """
    Raised when an Agent-to-Agent communication fails.
    """


# ---------------------------------------------------------------------
# Agent Layer
# ---------------------------------------------------------------------


class AgentError(BioResearchAIError):
    """
    Raised when an autonomous agent fails to complete its task.
    """