from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    setup_agent_url: str = os.getenv("SETUP_AGENT_URL", "http://127.0.0.1:9101")
    builder_agent_url: str = os.getenv("BUILDER_AGENT_URL", "http://127.0.0.1:9102")
    setup_agent_host: str = os.getenv("SETUP_AGENT_HOST", "127.0.0.1")
    setup_agent_port: int = _int_env("SETUP_AGENT_PORT", 9101)
    builder_agent_host: str = os.getenv("BUILDER_AGENT_HOST", "127.0.0.1")
    builder_agent_port: int = _int_env("BUILDER_AGENT_PORT", 9102)
    workspace_root: Path = Path(os.getenv("WORKSPACE_ROOT", "./workspaces")).expanduser().resolve()
    control_plane_db: Path = Path(os.getenv("CONTROL_PLANE_DB", "./state/control_plane.sqlite3")).expanduser().resolve()
    llm_mode: str = os.getenv("LLM_MODE", "gemini").strip().lower()
    gemini_api_key: str = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "").strip()
    llm_timeout_seconds: int = _int_env("LLM_TIMEOUT_SECONDS", 90)
    package_install_timeout_seconds: int = _int_env("PACKAGE_INSTALL_TIMEOUT_SECONDS", 300)
    code_execution_timeout_seconds: int = _int_env("CODE_EXECUTION_TIMEOUT_SECONDS", 30)
    max_generated_files: int = _int_env("MAX_GENERATED_FILES", 35)
    max_generated_bytes: int = _int_env("MAX_GENERATED_BYTES", 500_000)


settings = Settings()
