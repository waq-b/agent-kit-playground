"""CardStore — SQLite-backed persistence for each agent's current character state."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

from pydantic import BaseModel

from agent_kit.card_definition import CardDefinition
from agent_kit.class_definition import BASE_STAT_NAMES
from agent_kit.errors import AgentCardNotFoundError
from agent_kit.xp_rules import compute_level, compute_stat_nudge, compute_tool_tier, compute_xp_delta, grade_for_action

_DEFAULT_DB_PATH = "agent_kit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_name TEXT PRIMARY KEY,
    level INTEGER NOT NULL,
    xp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_stats (
    agent_name TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (agent_name, stat_name)
);
CREATE TABLE IF NOT EXISTS tool_proficiency (
    agent_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    xp INTEGER NOT NULL,
    tier INTEGER NOT NULL,
    PRIMARY KEY (agent_name, tool_name)
);
CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    tool_used TEXT,
    action TEXT NOT NULL,
    grade TEXT NOT NULL,
    xp_delta INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


class ToolProficiency(BaseModel):
    xp: int
    tier: int


class CardState(BaseModel):
    agent_name: str
    level: int
    xp: int
    base_stats: dict[str, int]
    class_stats: dict[str, int]
    tool_proficiency: dict[str, ToolProficiency]


class XPResult(BaseModel):
    xp_delta: int
    new_xp: int
    new_level: int
    leveled_up: bool
    stat_deltas: dict[str, int]


class CardStore:
    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def ensure_seeded(self, agent_name: str, card: CardDefinition) -> None:
        """Idempotent: no-op if agent_name already has an `agents` row.

        Does NOT backfill newly-added class stats for already-seeded agents —
        a known v0.2 limitation.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM agents WHERE agent_name = ?", (agent_name,)
            ).fetchone()
            if row is not None:
                return

            self._conn.execute(
                "INSERT INTO agents (agent_name, level, xp) VALUES (?, ?, ?)",
                (agent_name, card.starting_level, card.starting_xp),
            )
            for stat_name, value in {**card.base_stats, **card.class_stats}.items():
                self._conn.execute(
                    "INSERT INTO agent_stats (agent_name, stat_name, value) VALUES (?, ?, ?)",
                    (agent_name, stat_name, value),
                )
            self._conn.commit()

    def get_state(self, agent_name: str) -> CardState:
        row = self._conn.execute(
            "SELECT level, xp FROM agents WHERE agent_name = ?", (agent_name,)
        ).fetchone()
        if row is None:
            raise AgentCardNotFoundError(f"no card state seeded for agent '{agent_name}'")
        level, xp = row

        stat_rows = self._conn.execute(
            "SELECT stat_name, value FROM agent_stats WHERE agent_name = ?", (agent_name,)
        ).fetchall()
        base_stats = {name: value for name, value in stat_rows if name in BASE_STAT_NAMES}
        class_stats = {name: value for name, value in stat_rows if name not in BASE_STAT_NAMES}

        tool_rows = self._conn.execute(
            "SELECT tool_name, xp, tier FROM tool_proficiency WHERE agent_name = ?", (agent_name,)
        ).fetchall()
        tool_proficiency = {name: ToolProficiency(xp=xp, tier=tier) for name, xp, tier in tool_rows}

        return CardState(
            agent_name=agent_name,
            level=level,
            xp=xp,
            base_stats=base_stats,
            class_stats=class_stats,
            tool_proficiency=tool_proficiency,
        )

    def record_xp_event(self, agent_name: str, action: str, tool_used: str | None = None) -> XPResult:
        state = self.get_state(agent_name)
        xp_delta = compute_xp_delta(action)
        grade = grade_for_action(action)

        new_xp = state.xp + xp_delta
        new_level = compute_level(new_xp)
        leveled_up = new_level > state.level

        stat_nudges = compute_stat_nudge(state.base_stats.keys(), xp_delta)
        stat_deltas: dict[str, int] = {}

        with self._lock:
            for stat_name, old_value in state.base_stats.items():
                new_value = max(0, min(100, old_value + stat_nudges.get(stat_name, 0)))
                stat_deltas[stat_name] = new_value - old_value
                self._conn.execute(
                    "UPDATE agent_stats SET value = ? WHERE agent_name = ? AND stat_name = ?",
                    (new_value, agent_name, stat_name),
                )

            self._conn.execute(
                "UPDATE agents SET level = ?, xp = ? WHERE agent_name = ?",
                (new_level, new_xp, agent_name),
            )

            if tool_used:
                old_tool_xp = state.tool_proficiency.get(tool_used, ToolProficiency(xp=0, tier=0)).xp
                new_tool_xp = old_tool_xp + xp_delta
                new_tier = compute_tool_tier(new_tool_xp)
                self._conn.execute(
                    "INSERT INTO tool_proficiency (agent_name, tool_name, xp, tier) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(agent_name, tool_name) DO UPDATE SET xp = excluded.xp, tier = excluded.tier",
                    (agent_name, tool_used, new_tool_xp, new_tier),
                )

            self._conn.execute(
                "INSERT INTO xp_events (agent_name, tool_used, action, grade, xp_delta, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_name, tool_used, action, grade, xp_delta, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

        return XPResult(
            xp_delta=xp_delta,
            new_xp=new_xp,
            new_level=new_level,
            leveled_up=leveled_up,
            stat_deltas=stat_deltas,
        )

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM agents")
            self._conn.execute("DELETE FROM agent_stats")
            self._conn.execute("DELETE FROM tool_proficiency")
            self._conn.execute("DELETE FROM xp_events")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


_card_store: CardStore | None = None


def get_card_store() -> CardStore:
    global _card_store
    if _card_store is None:
        _card_store = CardStore(os.environ.get("AGENT_KIT_DB_PATH", _DEFAULT_DB_PATH))
    return _card_store
