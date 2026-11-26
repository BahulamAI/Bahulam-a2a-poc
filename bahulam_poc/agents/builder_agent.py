from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from bahulam_poc.a2a_client import invoke_a2a_agent
from bahulam_poc.llm import generate_project_spec
from bahulam_poc.settings import settings
from bahulam_poc.specs import validate_project_spec
from bahulam_poc.workspaces import WorkspaceManager


class CodeBuilderAgent:
    """Generates project specs, delegates setup over A2A, then writes and verifies code."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None):
        self.workspaces = workspace_manager or WorkspaceManager()

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action == "prepare_and_plan":
            return await self.prepare_and_plan(payload)
        if action == "write_and_run":
            return await self.write_and_run(payload)
        raise ValueError(f"Unsupported builder action: {action!r}")

    async def _call_setup(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
        result = await invoke_a2a_agent(settings.setup_agent_url, payload, timeout=600.0)
        try:
            artifact = json.loads(result.artifact_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Workspace Setup Agent returned invalid JSON artifact: {exc}") from exc
        if not isinstance(artifact, dict):
            raise RuntimeError("Workspace Setup Agent artifact must be a JSON object.")
        if result.state and "FAILED" in result.state.upper():
            raise RuntimeError(f"Workspace Setup Agent task failed: {artifact}")
        return artifact, result.task_id, result.state

    async def prepare_and_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        goal = payload.get("goal")
        if not isinstance(run_id, str) or not isinstance(goal, str) or not goal.strip():
            raise ValueError("prepare_and_plan requires run_id and a non-empty goal.")

        # 1. Agent-to-agent A2A handoff: Builder asks Setup Agent to create the workspace.
        workspace_result, setup_prepare_task, setup_prepare_state = await self._call_setup({
            "action": "prepare_workspace",
            "workspace_id": run_id,
            "requested_by": "code_builder_agent",
            "reason": "Create a project workspace and virtual environment before code generation.",
        })
        if not workspace_result.get("venv_ready"):
            raise RuntimeError("Setup Agent did not confirm that the virtual environment is ready.")

        # 2. Generate a bounded code specification (live LLM by default, or deterministic demo).
        spec = validate_project_spec(await generate_project_spec(goal))

        # 3. Agent-to-agent A2A handoff: Builder asks Setup Agent to validate and install deps.
        install_result, setup_install_task, setup_install_state = await self._call_setup({
            "action": "install_dependencies",
            "workspace_id": run_id,
            "dependencies": spec["dependencies"],
            "requested_by": "code_builder_agent",
        })
        installed = set(install_result.get("installed_dependencies", []))
        missing = sorted(set(spec["dependencies"]) - installed)
        if missing:
            raise RuntimeError(f"Setup Agent did not confirm installation of: {missing}")

        return {
            "status": "planned_and_environment_ready",
            "run_id": run_id,
            "workspace_id": run_id,
            "summary": spec["summary"],
            "dependencies": spec["dependencies"],
            "installed_dependencies": sorted(installed),
            "files_to_create": sorted(spec["files"].keys()),
            "file_count": len(spec["files"]),
            "entrypoint": spec["entrypoint"],
            "execution_requires_human_approval": True,
            "approval_note": "Review the file list and approve before the generated code is written and executed.",
            "project_spec": spec,
            "setup_agent_tasks": [
                {"task_id": setup_prepare_task, "state": setup_prepare_state, "action": "prepare_workspace"},
                {"task_id": setup_install_task, "state": setup_install_state, "action": "install_dependencies"},
            ],
        }

    def _write_project_files(self, project_dir: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
        manifest = []
        for relative_name, content in spec["files"].items():
            relative = PurePosixPath(relative_name)
            target = (project_dir / Path(*relative.parts)).resolve()
            if project_dir.resolve() not in target.parents:
                raise ValueError(f"Generated path escaped workspace: {relative_name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_symlink():
                raise ValueError(f"Refusing to write through symlink: {relative_name}")
            target.write_text(content, encoding="utf-8")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            manifest.append({"path": relative_name, "sha256": digest})
        return manifest

    @staticmethod
    def _restricted_env(venv_dir: Path) -> dict[str, str]:
        # Do not pass API keys or the full parent environment to generated code.
        allowed = ["PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"]
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env["VIRTUAL_ENV"] = str(venv_dir)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONUTF8"] = "1"
        return env

    def _run_command(self, command: list[str], project_dir: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                cwd=str(project_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return {
                "command": command,
                "return_code": completed.returncode,
                "stdout": completed.stdout[-6000:],
                "stderr": completed.stderr[-6000:],
                "timed_out": False,
                "passed": completed.returncode == 0,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "command": command,
                "return_code": None,
                "stdout": (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-3000:] if isinstance(exc.stderr, str) else "",
                "timed_out": True,
                "passed": False,
            }


    def _run_http_smoke(
        self, workspace_id: str, app_target: str, health_path: str, project_dir: Path, env: dict[str, str]
    ) -> dict[str, Any]:
        """Start a local ASGI app briefly, probe one endpoint, and always stop it."""
        python_path = self.workspaces.python_path(workspace_id)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log_path = project_dir / "server-smoke.log"
        command = [
            str(python_path), "-m", "uvicorn", app_target, "--host", "127.0.0.1",
            "--port", str(port), "--log-level", "warning"
        ]
        process = None
        try:
            with log_path.open("w", encoding="utf-8") as log_file:
                process = subprocess.Popen(
                    command, cwd=str(project_dir), env=env, stdout=log_file, stderr=subprocess.STDOUT
                )
                url = f"http://127.0.0.1:{port}{health_path}"
                deadline = time.monotonic() + min(settings.code_execution_timeout_seconds, 20)
                last_error = "server did not become ready"
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        last_error = f"server exited early with code {process.returncode}"
                        break
                    try:
                        with urllib.request.urlopen(url, timeout=1.5) as response:
                            body = response.read(3000).decode("utf-8", errors="replace")
                            return {
                                "command": command, "url": url, "http_status": response.status,
                                "response_body": body, "passed": 200 <= response.status < 300,
                                "timed_out": False,
                            }
                    except (urllib.error.URLError, TimeoutError, OSError) as exc:
                        last_error = str(exc)
                        time.sleep(0.25)
                return {
                    "command": command, "url": url, "http_status": None,
                    "error": last_error, "log_tail": log_path.read_text(encoding="utf-8", errors="replace")[-4000:],
                    "passed": False, "timed_out": time.monotonic() >= deadline,
                }
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    async def write_and_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        approved = payload.get("execution_approved") is True
        if not isinstance(run_id, str):
            raise ValueError("write_and_run requires run_id.")
        if not approved:
            raise PermissionError("Execution was not approved by the user.")
        spec = validate_project_spec(payload.get("project_spec", {}))
        project_dir = self.workspaces.project_path(run_id)
        python_path = self.workspaces.python_path(run_id)
        venv_dir = project_dir / ".venv"

        # The POC writes only the generated project files. Dependency installation remains Setup Agent-owned.
        file_manifest = self._write_project_files(project_dir, spec)
        env = self._restricted_env(venv_dir)

        compile_result = await asyncio.to_thread(
            self._run_command,
            [str(python_path), "-m", "compileall", "-q", "-x", r"\.venv", "."],
            project_dir,
            env,
            settings.code_execution_timeout_seconds,
        )

        test_files = [
            path
            for path in (*project_dir.rglob("test_*.py"), *project_dir.rglob("*_test.py"))
            if ".venv" not in path.relative_to(project_dir).parts
        ]
        test_result = None
        if test_files:
            test_result = await asyncio.to_thread(
                self._run_command,
                [str(python_path), "-m", "pytest", "-q", "-o", "norecursedirs=.venv"],
                project_dir,
                env,
                max(settings.code_execution_timeout_seconds, 60),
            )

        # Only run a short, declared Python entrypoint; never execute a model-provided shell command.
        entrypoint = (project_dir / Path(*PurePosixPath(spec["entrypoint"]).parts)).resolve()
        if project_dir.resolve() not in entrypoint.parents or not entrypoint.exists():
            raise ValueError("Declared entrypoint is missing or escaped the workspace.")
        entry_result = None
        tests_passed = test_result is None or test_result["passed"]
        if compile_result["passed"] and tests_passed:
            entry_result = await asyncio.to_thread(
                self._run_command,
                [str(python_path), str(entrypoint)],
                project_dir,
                env,
                settings.code_execution_timeout_seconds,
            )

        http_smoke_result = None
        if compile_result["passed"] and tests_passed and (entry_result is None or entry_result["passed"]) and spec.get("http_smoke"):
            http_smoke_result = await asyncio.to_thread(
                self._run_http_smoke,
                run_id,
                spec["http_smoke"]["app_target"],
                spec["http_smoke"]["health_path"],
                project_dir,
                env,
            )

        success = (
            compile_result["passed"]
            and tests_passed
            and (entry_result is None or entry_result["passed"])
            and (http_smoke_result is None or http_smoke_result["passed"])
        )
        report = {
            "status": "completed" if success else "verification_failed",
            "run_id": run_id,
            "workspace_id": run_id,
            "summary": spec["summary"],
            "files": file_manifest,
            "dependencies": spec["dependencies"],
            "compile_check": compile_result,
            "test_result": test_result,
            "entrypoint_result": entry_result,
            "http_smoke_result": http_smoke_result,
            "all_checks_passed": success,
            "project_directory": str(project_dir),
            "safety_note": "Executed locally in a project virtual environment with timeouts and a reduced environment. A virtualenv is NOT a security sandbox; use a disposable VM/container for untrusted code.",
        }
        return report
