"""
prompt.py

Defines the Prompt domain model.

A Prompt encapsulates all information required by a Large Language Model
to perform a task.

The application layer is responsible for constructing prompts.
The infrastructure layer is responsible for translating them into
provider-specific API requests.

Keeping prompts as domain objects rather than raw strings makes them
testable, reusable, and provider-independent.

Author
------
Guillermo Ramajo Fernández
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Prompt:
    """
    Represents a prompt sent to an LLM.

    Parameters
    ----------
    system
        High-level instructions that define the assistant's behavior.

    user
        The user request or task.

    context
        Optional contextual information such as scientific papers,
        retrieved documents, or structured knowledge.

    temperature
        Sampling temperature.

    max_tokens
        Maximum number of tokens to generate.
    """

    system: str

    user: str

    context: str = ""

    temperature: float = 0.2

    max_tokens: int = 4096

    metadata: dict[str, str] = field(default_factory=dict)