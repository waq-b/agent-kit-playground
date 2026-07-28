"""yaml_io — writes agent/class definition dicts back to YAML.

Matches the readable style DefinitionLoader/ClassLoader already expect to read
(plain strings for single-line values, block scalars for multi-line ones,
like news.yaml's system_prompt), without PyYAML's default 80-column line-wrap
silently corrupting long single-line values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class _AgentKitDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_AgentKitDumper.add_representer(str, _str_representer)


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(
        data,
        Dumper=_AgentKitDumper,
        default_flow_style=False,
        sort_keys=False,
        width=float("inf"),
    )


def write_yaml_file(path: Path, data: dict[str, Any]) -> None:
    path.write_text(dump_yaml(data))
