from pathlib import Path

import yaml

from agent_kit.yaml_io import dump_yaml, write_yaml_file

REAL_AGENT_YAML_DIR = Path(__file__).parent.parent / "agent_kit" / "agents"


def test_round_trip_single_line_string():
    data = {"name": "a", "system_prompt": "You are a greeter."}
    assert yaml.safe_load(dump_yaml(data)) == data


def test_round_trip_multi_line_string_uses_block_style():
    data = {"name": "a", "system_prompt": "Line one.\nLine two.\nLine three.\n"}
    dumped = dump_yaml(data)
    assert "|" in dumped
    assert yaml.safe_load(dumped) == data


def test_long_single_line_string_is_not_wrapped():
    long_value = "x" * 300
    data = {"name": "a", "description": long_value}
    dumped = dump_yaml(data)
    matching_lines = [line for line in dumped.splitlines() if "description" in line]
    assert len(matching_lines) == 1
    assert long_value in matching_lines[0]
    assert yaml.safe_load(dumped) == data


def test_key_order_is_preserved():
    data = {"zebra": 1, "apple": 2, "mango": 3}
    dumped = dump_yaml(data)
    keys_in_order = [line.split(":")[0] for line in dumped.splitlines()]
    assert keys_in_order == ["zebra", "apple", "mango"]


def test_nested_structures_round_trip():
    data = {
        "name": "a",
        "tools": ["fetch_rss_feed"],
        "card": {"main_class": "greeter", "base_stats": {"accuracy": 60}},
    }
    assert yaml.safe_load(dump_yaml(data)) == data


def test_write_yaml_file(tmp_path):
    path = tmp_path / "out.yaml"
    data = {"name": "a", "system_prompt": "hi"}
    write_yaml_file(path, data)
    assert yaml.safe_load(path.read_text()) == data


def test_real_hello_yaml_round_trips():
    original = yaml.safe_load((REAL_AGENT_YAML_DIR / "hello.yaml").read_text())
    assert yaml.safe_load(dump_yaml(original)) == original


def test_real_news_yaml_round_trips():
    original = yaml.safe_load((REAL_AGENT_YAML_DIR / "news.yaml").read_text())
    assert yaml.safe_load(dump_yaml(original)) == original
