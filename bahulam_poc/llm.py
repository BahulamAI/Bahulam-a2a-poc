from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from bahulam_poc.settings import settings
from bahulam_poc.workspaces import ALLOWED_PACKAGES


class LLMError(RuntimeError):
    pass


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("Model response must be a JSON object.")
    return value


def _build_system_prompt() -> str:
    allowed_packages = ", ".join(sorted(ALLOWED_PACKAGES))
    return f"""You are the code-generation component in a controlled coding-agent POC.
Return ONLY one valid JSON object with these fields:
{{
  "summary": "short summary",
  "dependencies": ["allowlisted third-party package names only"],
  "files": {{"relative/path": "complete file contents"}},
  "entrypoint": "relative/path/to/short_smoke_script.py",
  "http_smoke": null
}}
Optional: for an ASGI app, set http_smoke to {{"app_target":"module:app","health_path":"/health"}}.
Rules:
- Create a small, complete project that directly addresses the user's goal.
- Include thorough pytest tests under tests/ (e.g. tests/test_app.py) that exercise the implemented behavior.
- Include README.md and a finite, short-running Python smoke entrypoint (e.g. main.py) that prints meaningful output and exits cleanly within a few seconds.
- Do not create scripts that delete files, modify the host, access credentials, or perform external network calls.
- Do not include shell scripts, executable binaries, .env files, or arbitrary command strings.
- Dependencies must be chosen ONLY from this allowlist: {allowed_packages}.
- Do NOT include Python standard library modules (such as sqlite3, json, argparse, pathlib, unittest, math, csv, re) in dependencies.
- If using FastAPI TestClient in tests, include "httpx" in dependencies.
- Include "pytest" in dependencies whenever you generate pytest tests.
- Use only relative file paths. Do not include .., absolute paths, or hidden files (names starting with '.').
- Allowed file extensions: .py, .md, .txt, .json, .toml, .yaml, .yml, .html, .css, .js, .ts, .sql.
- The smoke entrypoint must exit within a few seconds; do not start a persistent server or wait for stdin from it.
- For a FastAPI/Starlette app, set http_smoke with app_target and health_path and include both "fastapi" and "uvicorn" in dependencies. The runner starts it only on 127.0.0.1 for a short health check and then stops it.
- Provide code files as strings in the JSON 'files' object. No Markdown fences around the JSON.
"""


def _generate_with_gemini_sync(goal: str, system_prompt: str) -> str:
    from google import genai
    from google.genai import types

    try:
        with genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                api_version="v1beta",
                timeout=settings.llm_timeout_seconds * 1000,
            ),
        ) as client:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=f"Build this project: {goal}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
    except Exception as exc:
        raise LLMError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Gemini response did not contain any text content.")
    return text


async def _generate_with_openai_compatible(goal: str, system_prompt: str) -> str:
    body = {
        "model": settings.openai_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Build this project: {goal}"},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions", json=body, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM response did not contain choices[0].message.content.") from exc


async def generate_project_spec(goal: str) -> dict[str, Any]:
    """Generate a bounded project spec using Gemini, an OpenAI-compatible API, or demo mode."""
    if settings.llm_mode == "demo":
        from bahulam_poc.specs import demo_project_spec
        return demo_project_spec(goal)

    system_prompt = _build_system_prompt()
    if settings.llm_mode == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("Set GEMINI_API_KEY (or GOOGLE_API_KEY) when LLM_MODE=gemini.")
        content = await asyncio.to_thread(_generate_with_gemini_sync, goal, system_prompt)
        return parse_json_content(content)

    if settings.llm_mode == "openai_compatible":
        if not settings.openai_api_key or not settings.openai_model:
            raise LLMError("Set OPENAI_API_KEY and OPENAI_MODEL when LLM_MODE=openai_compatible.")
        content = await _generate_with_openai_compatible(goal, system_prompt)
        return parse_json_content(content)

    raise LLMError("LLM_MODE must be 'gemini', 'openai_compatible', or 'demo'.")
