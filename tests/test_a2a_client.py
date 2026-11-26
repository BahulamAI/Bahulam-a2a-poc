from __future__ import annotations

from types import SimpleNamespace

from a2a.types import Artifact, Part, StreamResponse, Task, TaskState, TaskStatus

from bahulam_poc.a2a_client import _artifact_text, _normalize_card_urls, _state_name, _unwrap_response
from bahulam_poc.a2a_server import JsonAgentExecutor, build_a2a_app


def test_unwrap_stream_response_task_and_extract_artifact():
    stream_resp = StreamResponse(
        task=Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            artifacts=[
                Artifact(
                    artifact_id="art-1",
                    parts=[Part(text='{"ok":true}', media_type="application/json")],
                )
            ],
        )
    )
    unwrapped = _unwrap_response(stream_resp)
    assert unwrapped.id == "task-1"
    assert _state_name(stream_resp) == "TASK_STATE_COMPLETED"
    assert _artifact_text(stream_resp) == '{"ok":true}'


def test_build_a2a_app_uses_public_url_in_agent_card():
    async def noop(payload):
        return payload

    app = build_a2a_app(
        name="Test Agent",
        description="desc",
        version="0.1.0",
        host="0.0.0.0",
        port=9101,
        public_url="http://setup-agent:9101",
        skill_id="s1",
        skill_name="Skill",
        skill_description="Skill desc",
        examples=[],
        executor=JsonAgentExecutor(noop, "Test Agent"),
    )
    from starlette.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["supportedInterfaces"][0]["url"] == "http://setup-agent:9101"


def test_normalize_card_urls_falls_back_on_unresolvable_host(monkeypatch):
    def fake_getaddrinfo(host, port):
        raise OSError("dns failed")

    monkeypatch.setattr("bahulam_poc.a2a_client.socket.getaddrinfo", fake_getaddrinfo)
    card = SimpleNamespace(supported_interfaces=[SimpleNamespace(url="http://builder-agent:9102")])
    _normalize_card_urls(card, "http://127.0.0.1:9102")
    assert card.supported_interfaces[0].url == "http://127.0.0.1:9102"
