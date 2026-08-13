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


class IllegalWorkspaceActionError(ApplicationError):
    """
    Raised when an action is requested from a state that does not allow it.

    This is the primary guard against the workspace being advanced
    illegitimately — even by bugs or by a future refactor that bypasses
    the orchestrator. The error carries the offending state, the
    rejected action, and the list of actions that would have been legal
    from that state, so the caller (typically a FastAPI handler) can
    return a useful 409 Conflict with the allowed next moves.
    """

    def __init__(
        self,
        current_state: str,
        action: str,
        allowed: list[str],
    ) -> None:
        self.current_state = current_state
        self.action = action
        self.allowed = allowed
        super().__init__(
            f"Action '{action}' is not allowed from state '{current_state}'. "
            f"Allowed actions: {allowed}"
        )


class CitationValidationError(DomainError):
    """
    Raised when an AI-generated artefact references papers that were
    not part of the input set.

    This is the anti-fabrication guard. The LLM is given a closed set
    of papers and instructed to cite only those papers. If the parsed
    output cites a paper ID that was not in the input set, the
    citation is rejected and this exception is raised so the caller
    can retry, log, or surface the failure to the user.
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