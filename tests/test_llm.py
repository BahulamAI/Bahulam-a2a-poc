from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bahulam_poc import llm
from bahulam_poc.settings import Settings


def test_parse_json_content_strips_markdown_fences():
    parsed = llm.parse_json_content('```json\n{"summary": "ok", "files": {"main.py": "print(1)"}}\n```')
    assert parsed["summary"] == "ok"


def test_parse_json_content_rejects_invalid_json():
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("not json")


def test_parse_json_content_rejects_non_object():
    with pytest.raises(llm.LLMError):
        llm.parse_json_content("[1, 2, 3]")


def test_generate_project_spec_gemini_requires_key(monkeypatch):
    monkeypatch.setattr(
        llm,
        "settings",
        Settings(llm_mode="gemini", gemini_api_key="", gemini_model="gemini-2.5-flash"),
    )
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        asyncio.run(llm.generate_project_spec("Build a CLI tool"))


def test_generate_project_spec_gemini_uses_genai_client(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return SimpleNamespace(
                text='{"summary":"calc","dependencies":["pytest"],"entrypoint":"main.py","http_smoke":null,"files":{"main.py":"print(1)"}}'
            )

    class FakeClient:
        def __init__(self, *, api_key, http_options):
            captured["api_key"] = api_key
            captured["api_version"] = http_options.api_version
            captured["timeout_ms"] = http_options.timeout
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(
        llm,
        "settings",
        Settings(
            llm_mode="gemini",
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-flash",
            llm_timeout_seconds=45,
        ),
    )

    spec = asyncio.run(llm.generate_project_spec("Build a calculator CLI"))
    assert spec["summary"] == "calc"
    assert captured["api_key"] == "test-key"
    assert captured["api_version"] == "v1beta"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["timeout_ms"] == 45_000
    assert "Build a calculator CLI" in captured["contents"]
    assert captured["config"].response_mime_type == "application/json"


def test_generate_project_spec_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(llm, "settings", Settings(llm_mode="unknown"))
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.generate_project_spec("Build anything"))
