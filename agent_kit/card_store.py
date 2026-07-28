"""CardStore — SQLite-backed persistence for each agent's current character state."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

from pydantic import BaseModel

from agent_kit.card_definition import CardDefinition
from agent_kit.class_definition import BASE_STAT_NAMES
from agent_kit.errors import AgentCardNotFoundError, GMSuggestionNotFoundError
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
CREATE TABLE IF NOT EXISTS agent_traits (
    agent_name TEXT PRIMARY KEY,
    band_signature TEXT NOT NULL,
    trait_paragraph TEXT NOT NULL,
    synthesized_at TEXT NOT NULL,
    is_stale INTEGER NOT NULL DEFAULT 0,
    pending_since TEXT
);
CREATE TABLE IF NOT EXISTS gm_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    current_system_prompt TEXT NOT NULL,
    suggested_system_prompt TEXT NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL,
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


class TraitState(BaseModel):
    agent_name: str
    band_signature: str
    trait_paragraph: str
    synthesized_at: str
    is_stale: bool
    pending_since: str | None = None


class GMSuggestion(BaseModel):
    id: int
    agent_name: str
    current_system_prompt: str
    suggested_system_prompt: str
    rationale: str
    status: str
    created_at: str


class CardStore:
    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # Every statement — read or write — goes through this lock. A single
        # sqlite3 connection is not safe for concurrent use even with
        # check_same_thread=False: two threads calling execute() at once raise
        # "bad parameter or other API misuse". FastAPI runs the playground's
        # sync endpoints in a threadpool, so any two overlapping requests can
        # do exactly that. Re-entrant so a locked method may call another one
        # without deadlocking.
        self._lock = threading.RLock()
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
        with self._lock:
            row = self._conn.execute(
                "SELECT level, xp FROM agents WHERE agent_name = ?", (agent_name,)
            ).fetchone()
            if row is None:
                raise AgentCardNotFoundError(f"no card state seeded for agent '{agent_name}'")
            level, xp = row

            stat_rows = self._conn.execute(
                "SELECT stat_name, value FROM agent_stats WHERE agent_name = ?", (agent_name,)
            ).fetchall()
            tool_rows = self._conn.execute(
                "SELECT tool_name, xp, tier FROM tool_proficiency WHERE agent_name = ?",
                (agent_name,),
            ).fetchall()

        base_stats = {name: value for name, value in stat_rows if name in BASE_STAT_NAMES}
        class_stats = {name: value for name, value in stat_rows if name not in BASE_STAT_NAMES}
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

    # --- GM trait cache, respec debuff, and suggestions (v0.4) ---

    def get_traits(self, agent_name: str) -> TraitState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT agent_name, band_signature, trait_paragraph, synthesized_at, is_stale, pending_since "
                "FROM agent_traits WHERE agent_name = ?",
                (agent_name,),
            ).fetchone()
        if row is None:
            return None
        return TraitState(
            agent_name=row[0], band_signature=row[1], trait_paragraph=row[2],
            synthesized_at=row[3], is_stale=bool(row[4]), pending_since=row[5],
        )

    def store_traits(self, agent_name: str, band_signature: str, trait_paragraph: str) -> None:
        """Cache a freshly synthesized paragraph, clearing any respec debuff."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_traits "
                "(agent_name, band_signature, trait_paragraph, synthesized_at, is_stale, pending_since) "
                "VALUES (?, ?, ?, ?, 0, NULL) "
                "ON CONFLICT(agent_name) DO UPDATE SET "
                "band_signature = excluded.band_signature, "
                "trait_paragraph = excluded.trait_paragraph, "
                "synthesized_at = excluded.synthesized_at, is_stale = 0, pending_since = NULL",
                (agent_name, band_signature, trait_paragraph, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def mark_traits_stale(self, agent_name: str) -> None:
        """Apply the "needs respec" debuff and enter the retry queue.

        A no-op when there is no cached row at all — there is nothing stale to
        flag, and the caller will have used the deterministic fallback instead.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE agent_traits SET is_stale = 1, "
                "pending_since = COALESCE(pending_since, ?) WHERE agent_name = ?",
                (datetime.now(timezone.utc).isoformat(), agent_name),
            )
            self._conn.commit()

    def list_stale_agents(self) -> list[TraitState]:
        """The respec queue: everything waiting for the GM to come back."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent_name, band_signature, trait_paragraph, synthesized_at, is_stale, pending_since "
                "FROM agent_traits WHERE is_stale = 1 ORDER BY pending_since"
            ).fetchall()
        return [
            TraitState(
                agent_name=r[0], band_signature=r[1], trait_paragraph=r[2],
                synthesized_at=r[3], is_stale=bool(r[4]), pending_since=r[5],
            )
            for r in rows
        ]

    def count_events_since_synthesis(self, agent_name: str) -> int:
        """Grade events recorded since this agent's traits were last synthesized.

        The respec-threshold setting counts against this. `xp_events` already
        timestamps every grade, so no new counter column is needed — the count
        resets naturally whenever `store_traits` writes a new `synthesized_at`.
        Agents with no traits row yet return 0: there is nothing to re-synthesize,
        so there is nothing for a threshold to trip.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT synthesized_at FROM agent_traits WHERE agent_name = ?", (agent_name,)
            ).fetchone()
            if row is None:
                return 0
            return self._conn.execute(
                "SELECT COUNT(*) FROM xp_events WHERE agent_name = ? AND created_at > ?",
                (agent_name, row[0]),
            ).fetchone()[0]

    def record_suggestion(
        self, agent_name: str, current_system_prompt: str, suggested_system_prompt: str, rationale: str
    ) -> GMSuggestion:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO gm_suggestions "
                "(agent_name, current_system_prompt, suggested_system_prompt, rationale, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (
                    agent_name, current_system_prompt, suggested_system_prompt, rationale,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()
            suggestion_id = cursor.lastrowid
        return self.get_suggestion(suggestion_id)

    def get_suggestion(self, suggestion_id: int) -> GMSuggestion:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, agent_name, current_system_prompt, suggested_system_prompt, rationale, status, created_at "
                "FROM gm_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        if row is None:
            raise GMSuggestionNotFoundError(f"no GM suggestion with id {suggestion_id}")
        return GMSuggestion(
            id=row[0], agent_name=row[1], current_system_prompt=row[2],
            suggested_system_prompt=row[3], rationale=row[4], status=row[5], created_at=row[6],
        )

    def list_suggestions(self, status: str | None = "pending") -> list[GMSuggestion]:
        query = (
            "SELECT id, agent_name, current_system_prompt, suggested_system_prompt, rationale, status, created_at "
            "FROM gm_suggestions"
        )
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            GMSuggestion(
                id=r[0], agent_name=r[1], current_system_prompt=r[2],
                suggested_system_prompt=r[3], rationale=r[4], status=r[5], created_at=r[6],
            )
            for r in rows
        ]

    def resolve_suggestion(self, suggestion_id: int, status: str) -> GMSuggestion:
        self.get_suggestion(suggestion_id)  # raises GMSuggestionNotFoundError if unknown
        with self._lock:
            self._conn.execute(
                "UPDATE gm_suggestions SET status = ? WHERE id = ?", (status, suggestion_id)
            )
            self._conn.commit()
        return self.get_suggestion(suggestion_id)

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM agents")
            self._conn.execute("DELETE FROM agent_stats")
            self._conn.execute("DELETE FROM tool_proficiency")
            self._conn.execute("DELETE FROM xp_events")
            self._conn.execute("DELETE FROM agent_traits")
            self._conn.execute("DELETE FROM gm_suggestions")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


_card_store: CardStore | None = None


def get_card_store() -> CardStore:
    global _card_store
    if _card_store is None:
        _card_store = CardStore(os.environ.get("AGENT_KIT_DB_PATH", _DEFAULT_DB_PATH))
    return _card_store


def reset_card_store() -> None:
    """Drop the singleton so the next `get_card_store()` re-reads AGENT_KIT_DB_PATH.

    Needed because the db path is bound once at construction. `settings.py`
    calls this when the configured path actually changes; nothing else should.
    """
    global _card_store
    if _card_store is not None:
        _card_store.close()
        _card_store = None
