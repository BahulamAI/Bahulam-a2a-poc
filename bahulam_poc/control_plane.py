from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bahulam_poc.settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ControlPlane:
    """Small SQLite-backed POC run ledger (Bahulam PRD-124 / Work Graph analogue)."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.control_plane_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workspace_id TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    a2a_task_id TEXT,
                    state TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                """
            )

    def create_run(self, run_id: str, goal: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, goal, "created", now, now),
            )
        self.add_event(run_id, "control_plane", "run.created", {"goal": goal})

    def add_event(self, run_id: str, actor: str, event_type: str, payload: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO run_events(run_id, actor, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, actor, event_type, json.dumps(payload, ensure_ascii=False), now),
            )
            connection.execute("UPDATE runs SET updated_at=? WHERE run_id=?", (now, run_id))

    def set_status(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE run_id=?", (status, utc_now(), run_id)
            )
        self.add_event(run_id, "control_plane", "run.status", {"status": status})

    def set_workspace(self, run_id: str, workspace_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET workspace_id=?, updated_at=? WHERE run_id=?",
                (workspace_id, utc_now(), run_id),
            )
        self.add_event(run_id, "control_plane", "workspace.linked", {"workspace_id": workspace_id})

    def record_agent_task(self, run_id: str, agent_name: str, task_id: str | None, state: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_tasks(run_id, agent_name, a2a_task_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, agent_name, task_id, state, utc_now()),
            )
        self.add_event(run_id, agent_name, "a2a.task_recorded", {"task_id": task_id, "state": state})

    def save_result(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status=?, result_json=?, updated_at=? WHERE run_id=?",
                (status, json.dumps(result, ensure_ascii=False), now, run_id),
            )
        self.add_event(run_id, "control_plane", "run.finished", {"status": status})

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
            events = connection.execute(
                "SELECT actor, event_type, payload_json, created_at FROM run_events WHERE run_id=? ORDER BY event_id",
                (run_id,),
            ).fetchall()
            result["events"] = [
                {"actor": e["actor"], "event_type": e["event_type"], "payload": json.loads(e["payload_json"]), "created_at": e["created_at"]}
                for e in events
            ]
            tasks = connection.execute(
                "SELECT agent_name, a2a_task_id, state, created_at FROM agent_tasks WHERE run_id=? ORDER BY record_id",
                (run_id,),
            ).fetchall()
            result["agent_tasks"] = [dict(t) for t in tasks]
            return result
