"""Exception hierarchy for agent-kit."""

from __future__ import annotations


class AgentKitError(Exception):
    """Base exception for all agent-kit errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DuplicateAgentError(AgentKitError):
    """Raised when an agent name is already registered."""


class AgentNotFoundError(AgentKitError):
    """Raised when a requested agent name is not in the registry."""


class NoFixtureError(AgentKitError):
    """Raised when no stub fixture is registered for an agent."""


class TypeMismatchError(AgentKitError):
    """Raised when a stub fixture's type does not match the agent's output_model."""


class MissingFieldError(AgentKitError):
    """Raised when a required field is missing from an Agent_Definition YAML file."""


class YAMLSyntaxError(AgentKitError):
    """Raised when an Agent_Definition YAML file contains invalid YAML syntax."""

    def __init__(self, file_path: str, location: str) -> None:
        self.file_path = file_path
        self.location = location
        super().__init__(f"YAML syntax error in {file_path} at {location}")


class TemperatureRangeError(AgentKitError):
    """Raised when temperature is outside the range [0.0, 2.0]."""


class UnresolvableOutputModelError(AgentKitError):
    """Raised when an output_model dotted path cannot be resolved."""


class AgentConnectionError(AgentKitError):
    """Raised when the configured model provider is unreachable."""


class LoadSummaryError(AgentKitError):
    """Raised by DefinitionLoader.load_directory to aggregate per-file errors."""


class UnknownToolError(AgentKitError):
    """Raised when a tool name referenced by an Agent_Definition is not registered."""


class FeedFetchError(AgentKitError):
    """Raised when an RSS feed cannot be fetched or parsed."""
