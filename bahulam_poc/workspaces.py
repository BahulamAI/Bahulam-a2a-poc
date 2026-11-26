from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from bahulam_poc.settings import settings

# Deliberately small allowlist. Extend only after reviewing package provenance and risk.
ALLOWED_PACKAGES = {
    "fastapi",
    "uvicorn",
    "httpx",
    "pydantic",
    "pytest",
    "requests",
    "python-dotenv",
    "jinja2",
    "sqlalchemy",
}
RUN_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class WorkspaceError(RuntimeError):
    pass


class WorkspaceManager:
    def __init__(self, root: Path | None = None):
        self.root = (root or settings.workspace_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, workspace_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(workspace_id):
            raise WorkspaceError("workspace_id must be a 32-character lowercase UUID hex string.")
        path = (self.root / workspace_id).resolve()
        if self.root not in path.parents:
            raise WorkspaceError("Workspace path escaped the configured workspace root.")
        return path

    def prepare(self, workspace_id: str) -> dict:
        project_dir = self._project_dir(workspace_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        venv_dir = project_dir / ".venv"
        if not venv_dir.exists():
            completed = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if completed.returncode != 0:
                raise WorkspaceError(f"Could not create virtual environment: {completed.stderr[-2000:]}")
        if os.name == "nt":
            python_path = venv_dir / "Scripts" / "python.exe"
        else:
            python_path = venv_dir / "bin" / "python"
        if not python_path.exists():
            raise WorkspaceError(f"Virtual environment Python executable not found: {python_path}")
        return {
            "workspace_id": workspace_id,
            "workspace_ready": True,
            "python_version": sys.version.split()[0],
            "venv_ready": True,
            "installed_dependencies": [],
            "message": "Created an isolated project directory and virtual environment.",
        }

    def validate_packages(self, packages: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for item in packages:
            if not isinstance(item, str):
                raise WorkspaceError("Each dependency must be a package-name string.")
            name = item.strip().lower().replace("_", "-")
            # No version syntax, URL, local path, extras, or pip flags in this POC.
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                raise WorkspaceError(f"Unsafe dependency specification rejected: {item!r}")
            if name not in ALLOWED_PACKAGES:
                raise WorkspaceError(
                    f"Package '{name}' is not on the POC allowlist. Allowed: {', '.join(sorted(ALLOWED_PACKAGES))}"
                )
            if name not in normalized:
                normalized.append(name)
        return normalized

    def _python(self, workspace_id: str) -> Path:
        project_dir = self._project_dir(workspace_id)
        venv_dir = project_dir / ".venv"
        python_path = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python_path.exists():
            raise WorkspaceError("Workspace is not prepared. Call prepare first.")
        return python_path

    def install(self, workspace_id: str, packages: Iterable[str]) -> dict:
        validated = self.validate_packages(packages)
        # pytest is the controlled test runner used by the POC.
        if "pytest" not in validated:
            validated.append("pytest")
        python_path = self._python(workspace_id)
        project_dir = self._project_dir(workspace_id)
        if validated:
            command = [
                str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *validated
            ]
            # Keep model/API credentials out of pip build backends and package subprocesses.
            allowed_env_keys = ["PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"]
            install_env = {key: os.environ[key] for key in allowed_env_keys if key in os.environ}
            install_env["PYTHONNOUSERSITE"] = "1"
            install_env["PYTHONUTF8"] = "1"
            completed = subprocess.run(
                command,
                cwd=str(project_dir),
                env=install_env,
                capture_output=True,
                text=True,
                timeout=settings.package_install_timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise WorkspaceError(
                    "Dependency installation failed.\n"
                    + (completed.stderr or completed.stdout)[-5000:]
                )
        freeze = subprocess.run(
            [str(python_path), "-m", "pip", "freeze"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=60, check=False
        )
        lock_text = freeze.stdout if freeze.returncode == 0 else "\n".join(validated)
        (project_dir / "requirements.lock.txt").write_text(lock_text, encoding="utf-8")
        return {
            "workspace_id": workspace_id,
            "installed_dependencies": validated,
            "requirements_lock": "requirements.lock.txt",
            "install_log_tail": (completed.stdout[-1500:] if validated else "No extra dependencies requested."),
            "message": "Dependencies validated against the allowlist and installed in the project virtual environment.",
        }

    def details(self, workspace_id: str) -> dict:
        project_dir = self._project_dir(workspace_id)
        python_path = self._python(workspace_id)
        return {
            "workspace_id": workspace_id,
            "workspace_exists": project_dir.exists(),
            "venv_python_exists": python_path.exists(),
            "relative_workspace": workspace_id,
        }

    def project_path(self, workspace_id: str) -> Path:
        return self._project_dir(workspace_id)

    def python_path(self, workspace_id: str) -> Path:
        return self._python(workspace_id)
