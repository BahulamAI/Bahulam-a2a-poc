from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from bahulam_poc.settings import settings
from bahulam_poc.workspaces import ALLOWED_PACKAGES, WorkspaceError


class ProjectSpecError(ValueError):
    pass


def demo_project_spec(goal: str) -> dict[str, Any]:
    """A deterministic demo project so the complete A2A flow works without an LLM key."""
    safe_goal = json.dumps(goal[:500], ensure_ascii=True)
    return {
        "summary": "Generated a small FastAPI starter with health and task endpoints, tests, and a smoke script.",
        "dependencies": ["fastapi", "uvicorn", "httpx", "pytest"],
        "entrypoint": "main.py",
        "http_smoke": {"app_target": "app:app", "health_path": "/health"},
        "files": {
            "app.py": '''from fastapi import FastAPI\nfrom pydantic import BaseModel\n\napp = FastAPI(title="Bahulam Generated App", version="0.1.0")\n\nclass TaskRequest(BaseModel):\n    task: str\n\n@app.get("/health")\ndef health():\n    return {"status": "ok", "service": "bahulam-generated-app"}\n\n@app.post("/tasks")\ndef create_task(payload: TaskRequest):\n    return {"accepted": True, "task": payload.task}\n''',
            "main.py": f'''from app import app\n\nREQUESTED_GOAL = {safe_goal}\n\ndef main() -> None:\n    print("Bahulam generated project is ready.")\n    print("Requested goal:", REQUESTED_GOAL)\n    print("API title:", app.title)\n\nif __name__ == "__main__":\n    main()\n''',
            "tests/test_app.py": '''from fastapi.testclient import TestClient\nfrom app import app\n\nclient = TestClient(app)\n\ndef test_health_endpoint():\n    response = client.get("/health")\n    assert response.status_code == 200\n    assert response.json()["status"] == "ok"\n\n\ndef test_create_task_endpoint():\n    response = client.post("/tasks", json={"task": "build a demo"})\n    assert response.status_code == 200\n    assert response.json() == {"accepted": True, "task": "build a demo"}\n''',
            "README.md": f'''# Bahulam Generated Project\n\n## Request\n\n{safe_goal}\n\n## Run tests\n\n```bash\npython -m pytest -q\n```\n\n## Run the finite smoke script\n\n```bash\npython main.py\n```\n\n## API\n\n- `GET /health`\n- `POST /tasks` with JSON `{{"task":"..."}}`\n\nThe server can be started manually with `uvicorn app:app --reload`. The POC runner starts the server briefly for a localhost health check and then stops it.\n''',
        },
    }


def validate_project_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ProjectSpecError("Generated project specification must be a JSON object.")
    files = spec.get("files")
    dependencies = spec.get("dependencies", [])
    entrypoint = spec.get("entrypoint", "main.py")
    if not isinstance(files, dict) or not files:
        raise ProjectSpecError("Project spec must contain a non-empty 'files' object.")
    if len(files) > settings.max_generated_files:
        raise ProjectSpecError(f"Project contains more than {settings.max_generated_files} files.")
    total_bytes = 0
    clean_files: dict[str, str] = {}
    allowed_suffixes = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".sql"}
    for raw_path, content in files.items():
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise ProjectSpecError("File paths and file contents must be strings.")
        path = PurePosixPath(raw_path.replace("\\", "/"))
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ProjectSpecError(f"Unsafe generated file path: {raw_path!r}")
        if any(part.startswith(".") for part in path.parts):
            raise ProjectSpecError(f"Hidden files are not allowed in this POC: {raw_path!r}")
        if path.suffix.lower() not in allowed_suffixes:
            raise ProjectSpecError(f"File type is not allowed in this POC: {raw_path!r}")
        if path.name.lower() in {".env", "secrets.json", "id_rsa", "authorized_keys"}:
            raise ProjectSpecError(f"Sensitive file name is not allowed: {raw_path!r}")
        total_bytes += len(content.encode("utf-8"))
        clean_files[str(path)] = content
    if total_bytes > settings.max_generated_bytes:
        raise ProjectSpecError(f"Generated files exceed {settings.max_generated_bytes} bytes.")
    if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
        raise ProjectSpecError("Dependencies must be a list of package-name strings.")
    normalized_dependencies = []
    for dependency in dependencies:
        name = dependency.strip().lower().replace("_", "-")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or name not in ALLOWED_PACKAGES:
            raise ProjectSpecError(f"Dependency is not on the POC allowlist: {dependency!r}")
        if name not in normalized_dependencies:
            normalized_dependencies.append(name)
    if not isinstance(entrypoint, str):
        raise ProjectSpecError("entrypoint must be a relative Python file path.")
    entry_path = PurePosixPath(entrypoint.replace("\\", "/"))
    if entry_path.is_absolute() or ".." in entry_path.parts or entry_path.suffix.lower() != ".py":
        raise ProjectSpecError("entrypoint must be a safe relative .py file path.")
    if str(entry_path) not in clean_files:
        raise ProjectSpecError("The declared entrypoint must exist in the generated files.")
    if "README.md" not in clean_files:
        clean_files["README.md"] = "# Generated project\n\nSee the source files and tests in this project.\n"
    http_smoke = spec.get("http_smoke")
    normalized_http_smoke = None
    if http_smoke is not None:
        if not isinstance(http_smoke, dict):
            raise ProjectSpecError("http_smoke must be an object when supplied.")
        app_target = http_smoke.get("app_target")
        health_path = http_smoke.get("health_path", "/health")
        if not isinstance(app_target, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*", app_target
        ):
            raise ProjectSpecError("http_smoke.app_target must look like 'module:app'.")
        module_name = app_target.split(":", 1)[0]
        module_file = module_name.replace(".", "/") + ".py"
        if module_file not in clean_files:
            raise ProjectSpecError(f"http_smoke module is not present in generated files: {module_file}")
        if not isinstance(health_path, str) or not health_path.startswith("/") or ".." in health_path:
            raise ProjectSpecError("http_smoke.health_path must be a safe absolute URL path such as /health.")
        if "uvicorn" not in normalized_dependencies:
            raise ProjectSpecError("http_smoke requires 'uvicorn' in dependencies.")
        normalized_http_smoke = {"app_target": app_target, "health_path": health_path[:128]}

    return {
        "summary": str(spec.get("summary", "Generated project"))[:2000],
        "dependencies": normalized_dependencies,
        "entrypoint": str(entry_path),
        "http_smoke": normalized_http_smoke,
        "files": clean_files,
    }
