"""parse_card — resolves a `card:` YAML section into a CardDefinition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_kit.card_definition import CardDefinition, UnlockEntry
from agent_kit.class_definition import BASE_STAT_NAMES, DEFAULT_BASE_STAT_VALUE
from agent_kit.class_registry import get_class_registry
from agent_kit.errors import InvalidUnlockTableError, MissingFieldError, StatRangeError, UnknownStatError


def parse_card(card_data: dict[str, Any], source_path: Path) -> CardDefinition:
    if "main_class" not in card_data or card_data["main_class"] is None:
        raise MissingFieldError(f"card.main_class missing in {source_path}")

    main_class = get_class_registry().get(card_data["main_class"])

    sub_class = None
    if card_data.get("sub_class"):
        sub_class = get_class_registry().get(card_data["sub_class"])

    # .stat_values, not .stats — cards and CardStore carry plain ints; the
    # effect metadata stays on the ClassDefinition and is resolved at run time.
    class_stats = {**main_class.stat_values, **(sub_class.stat_values if sub_class else {})}

    base_stats = {name: DEFAULT_BASE_STAT_VALUE for name in BASE_STAT_NAMES}
    for stat_name, value in (card_data.get("base_stats") or {}).items():
        if stat_name not in BASE_STAT_NAMES:
            raise UnknownStatError(f"unknown base stat '{stat_name}' in {source_path}")
        if not (0 <= value <= 100):
            raise StatRangeError(
                f"base stat '{stat_name}' = {value!r} in {source_path} is outside the allowed range [0, 100]"
            )
        base_stats[stat_name] = int(value)

    title = card_data.get("title") or (
        f"{main_class.title} {sub_class.title}" if sub_class else main_class.title
    )

    unlock_table = []
    for entry in card_data.get("unlock_table") or []:
        if "level" not in entry or "unlock" not in entry:
            raise InvalidUnlockTableError(
                f"unlock_table entry {entry!r} in {source_path} missing 'level' or 'unlock'"
            )
        if not isinstance(entry["level"], int) or entry["level"] < 1:
            raise InvalidUnlockTableError(
                f"unlock_table 'level' must be a positive int in {source_path}, got {entry['level']!r}"
            )
        unlock_table.append(
            UnlockEntry(level=entry["level"], unlock=entry["unlock"], description=entry.get("description", ""))
        )

    return CardDefinition(
        title=title,
        backstory=card_data.get("backstory", ""),
        portrait=card_data.get("portrait", ""),
        main_class=main_class,
        sub_class=sub_class,
        class_stats=class_stats,
        base_stats=base_stats,
        unlock_table=tuple(unlock_table),
        starting_level=int(card_data.get("level", 1)),
        starting_xp=int(card_data.get("xp", 0)),
    )
