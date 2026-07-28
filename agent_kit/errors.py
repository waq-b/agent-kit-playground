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
    """Raised by DefinitionLoader/ClassLoader.load_directory to aggregate per-file errors."""


class UnknownToolError(AgentKitError):
    """Raised when a tool name referenced by an Agent_Definition is not registered."""


class FeedFetchError(AgentKitError):
    """Raised when an RSS feed cannot be fetched or parsed."""


class ClassNotFoundError(AgentKitError):
    """Raised when a requested class name is not in the ClassRegistry."""


class DuplicateClassError(AgentKitError):
    """Raised when a class name is already registered."""


class StatRangeError(AgentKitError):
    """Raised when a stat value is outside the allowed range [0, 100]."""


class UnknownStatError(AgentKitError):
    """Raised when a card's base_stats override references a name outside the universal base stat set."""


class ReservedStatNameError(AgentKitError):
    """Raised when a class definition's stats use a name reserved for the universal base stats."""


class InvalidUnlockTableError(AgentKitError):
    """Raised when a card's unlock_table entry is malformed (missing level/unlock, or invalid level)."""


class UnknownGradeActionError(AgentKitError):
    """Raised when a grading action is not in the known XP rules table."""


class AgentCardNotFoundError(AgentKitError):
    """Raised when CardStore is queried for an agent with no seeded card state."""


class InvalidAgentNameError(AgentKitError):
    """Raised when a builder-supplied agent name is not a usable identifier."""


class InvalidFieldSpecError(AgentKitError):
    """Raised when an output-model FieldSpec is structurally malformed."""


class DuplicateFieldNameError(AgentKitError):
    """Raised when two fields at the same level of an output-model spec share a name."""


class ReservedFieldNameError(AgentKitError):
    """Raised when an output-model field name collides with a BaseModel/model_* reserved name."""


class NestingDepthExceededError(AgentKitError):
    """Raised when an output-model field spec nests more than one level deep."""


class EmptyOutputModelError(AgentKitError):
    """Raised when an output-model spec has zero fields."""


class OutputModelNotEditableError(AgentKitError):
    """Raised when an update targets the output schema of a hand-written (non-builder-generated) agent."""


class CoreAgentConfirmationRequiredError(AgentKitError):
    """Raised when deleting a core demo agent (hello/news) without the extra confirm_core flag."""


class InvalidStatEffectError(AgentKitError):
    """Raised when a class stat's effect definition is structurally malformed."""


class MissingPromptEffectError(AgentKitError):
    """Raised when a class stat has no prompt_effect bands."""


class MissingRuntimeEffectError(AgentKitError):
    """Raised when a class stat has no runtime_effect curves."""


class UnknownRuntimeParameterError(AgentKitError):
    """Raised when a runtime_effect targets a parameter outside the known RuntimeParams fields."""


class GMUnavailableError(AgentKitError):
    """Raised when the GM (Game Master) synthesis call cannot be completed."""


class GMSuggestionNotFoundError(AgentKitError):
    """Raised when a GM suggestion id is not present in the store."""
