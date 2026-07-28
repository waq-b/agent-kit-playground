"""Universal base-stat constants.

Deliberately dependency-free. These live in their own module (rather than in
class_definition.py, where they started) so that stat_mapping.py can use them
without creating an import cycle once class_definition.py began depending on
stat_effects.py, which in turn depends on stat_mapping.py.

class_definition.py re-exports both names, so existing
`from agent_kit.class_definition import BASE_STAT_NAMES` imports keep working.
"""

from __future__ import annotations

BASE_STAT_NAMES = ("accuracy", "insight", "speed", "reliability")
DEFAULT_BASE_STAT_VALUE = 50
