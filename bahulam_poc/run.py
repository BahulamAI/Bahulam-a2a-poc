from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import httpx

from bahulam_poc.cli import run_build, show_run
from bahulam_poc.settings import settings


@dataclass
class ManagedAgent:
    name: str
    module: str
    url: str
    log_path: Path
    process: subprocess.Popen[str] | None = None
    log_file: IO[str] | None = None


def _is_agent_ready(url: str) -> bool:
    card_url = url.rstrip("/") + "/.well-known/agent-card.json"
    try:
        response = httpx.get(card_url, timeout=1.5)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _tail_log(path: Path, max_chars: int = 2000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-max_chars:].strip()


def _start_agents(log_dir: Path, startup_timeout: float = 25.0) -> list[ManagedAgent]:
    log_dir.mkdir(parents=True, exist_ok=True)
    agents = [
        ManagedAgent(
            name="Workspace Setup Agent",
            module="bahulam_poc.agents.setup_server",
            url=settings.setup_agent_url,
            log_path=log_dir / "setup_agent.log",
        ),
        ManagedAgent(
            name="Code Builder Agent",
            module="bahulam_poc.agents.builder_server",
            url=settings.builder_agent_url,
            log_path=log_dir / "builder_agent.log",
        ),
    ]

    try:
        for agent in agents:
            if _is_agent_ready(agent.url):
                print(f"[Agent] {agent.name} already running at {agent.url}")
                continue
            agent.log_file = agent.log_path.open("w", encoding="utf-8")
            agent.process = subprocess.Popen(
                [sys.executable, "-m", agent.module],
                stdout=agent.log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

        deadline = time.monotonic() + startup_timeout
        pending = list(agents)
        while pending and time.monotonic() < deadline:
            still_pending: list[ManagedAgent] = []
            for agent in pending:
                if agent.process is not None and agent.process.poll() is not None:
                    tail = _tail_log(agent.log_path)
                    raise RuntimeError(
                        f"{agent.name} exited early with code {agent.process.returncode}.\n"
                        f"Log ({agent.log_path}):\n{tail}"
                    )
                if _is_agent_ready(agent.url):
                    if agent.process is not None:
                        print(f"[Agent] {agent.name} ready at {agent.url} (log: {agent.log_path})")
                else:
                    still_pending.append(agent)
            pending = still_pending
            if pending:
                time.sleep(0.25)

        if pending:
            details = "\n".join(
                f"- {a.name} ({a.url}): {_tail_log(a.log_path, 600)}" for a in pending
            )
            raise TimeoutError(f"Timed out waiting for A2A agents to become ready:\n{details}")

        return agents
    except Exception:
        _stop_agents(agents)
        raise


def _stop_agents(agents: list[ManagedAgent]) -> None:
    for agent in reversed(agents):
        if agent.process is not None and agent.process.poll() is None:
            agent.process.terminate()
            try:
                agent.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent.process.kill()
                agent.process.wait(timeout=5)
        if agent.log_file is not None:
            agent.log_file.close()
            agent.log_file = None


def _interactive_loop(approve_execution: bool) -> int:
    print("\nBahulam single-terminal mode ready. Type a project prompt, or 'exit' to quit.")
    last_code = 0
    while True:
        try:
            goal = input("\nPrompt> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not goal:
            continue
        if goal.lower() in {"exit", "quit", "q"}:
            break
        last_code = asyncio.run(run_build(goal, approve_execution))
    return last_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run both Bahulam A2A agents and the Control Plane CLI in a single terminal."
    )
    parser.add_argument(
        "goal",
        nargs="?",
        help="Project prompt to build. Omit to enter interactive multi-prompt mode.",
    )
    parser.add_argument(
        "--approve-execution",
        action="store_true",
        help="Approve writing and running generated code without an interactive prompt.",
    )
    parser.add_argument("--show-run", help="Print a saved Control Plane run by run ID.")
    args = parser.parse_args()

    if args.show_run:
        raise SystemExit(show_run(args.show_run))

    log_dir = settings.control_plane_db.parent / "logs"
    agents = _start_agents(log_dir)
    try:
        if args.goal:
            exit_code = asyncio.run(run_build(args.goal, args.approve_execution))
        else:
            exit_code = _interactive_loop(args.approve_execution)
    finally:
        print("[Agent] Stopping managed A2A servers...")
        _stop_agents(agents)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
