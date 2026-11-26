from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest, TaskState


@dataclass
class A2AResult:
    task_id: str | None
    context_id: str | None
    state: str | None
    artifact_text: str
    raw_response: Any


def _read_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_dict(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        return obj
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:
            result = model_dump()
        if isinstance(result, dict):
            return result
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    return None


def _part_text(part: Any) -> str | None:
    direct = _read_attr(part, "text")
    if isinstance(direct, str):
        return direct
    root = _read_attr(part, "root")
    nested = _read_attr(root, "text") if root is not None else None
    if isinstance(nested, str):
        return nested
    mapping = _as_dict(part)
    if mapping:
        if isinstance(mapping.get("text"), str):
            return mapping["text"]
        root_map = mapping.get("root")
        if isinstance(root_map, dict) and isinstance(root_map.get("text"), str):
            return root_map["text"]
    return None


def _unwrap_response(response: Any) -> Any:
    """Unwrap a2a-sdk StreamResponse (protobuf oneof) into Task or Message."""
    has_field = getattr(response, "HasField", None)
    if callable(has_field):
        for field in ("task", "message", "artifact_update", "status_update"):
            try:
                if has_field(field):
                    return getattr(response, field)
            except ValueError:
                continue
    if isinstance(response, dict):
        for field in ("task", "message"):
            if field in response and response[field] is not None:
                return response[field]
    return response


def _artifact_text(response: Any) -> str:
    """Extract text from A2A task artifacts (or a direct Message response)."""
    response = _unwrap_response(response)
    mapping = _as_dict(response)
    artifacts = _read_attr(response, "artifacts")
    if artifacts is None and mapping:
        artifacts = mapping.get("artifacts")
    if not artifacts:
        single_artifact = _read_attr(response, "artifact")
        if single_artifact is not None:
            artifacts = [single_artifact]

    chunks: list[str] = []
    if artifacts:
        for artifact in artifacts:
            parts = _read_attr(artifact, "parts")
            artifact_map = _as_dict(artifact)
            if parts is None and artifact_map:
                parts = artifact_map.get("parts", [])
            for part in parts or []:
                value = _part_text(part)
                if value:
                    chunks.append(value)
    if chunks:
        return "\n".join(chunks)

    # Some agents can return an immediate Message rather than a Task.
    parts = _read_attr(response, "parts")
    if parts is None and mapping:
        parts = mapping.get("parts", [])
    for part in parts or []:
        value = _part_text(part)
        if value:
            chunks.append(value)
    if chunks:
        return "\n".join(chunks)

    raise RuntimeError("A2A agent returned no text artifact. Inspect the task history/server logs.")


def _state_name(response: Any) -> str | None:
    response = _unwrap_response(response)
    status = _read_attr(response, "status")
    state = _read_attr(status, "state") if status is not None else None
    if state is None:
        mapping = _as_dict(response) or {}
        status_map = mapping.get("status", {})
        if isinstance(status_map, dict):
            state = status_map.get("state")
    if state is None:
        return None
    if isinstance(state, int):
        try:
            return TaskState.Name(state)
        except ValueError:
            return str(state)
    return getattr(state, "name", str(state))


def _normalize_card_urls(card: Any, base_url: str) -> Any:
    """Fall back to base_url when an AgentCard advertises an unresolvable host (e.g. Docker service name)."""
    interfaces = getattr(card, "supported_interfaces", None) or []
    clean_base = base_url.rstrip("/")
    for iface in interfaces:
        url = getattr(iface, "url", "")
        host = urlparse(url).hostname if url else None
        if not host:
            continue
        try:
            socket.getaddrinfo(host, None)
        except OSError:
            iface.url = clean_base
    return card


async def invoke_a2a_agent(base_url: str, payload: dict[str, Any], timeout: float = 600.0) -> A2AResult:
    """Discover a remote A2A agent and send it a JSON task in a text Part.

    The task payload is JSON text so the same contract works across A2A SDKs.
    Agent outputs are returned as JSON text artifacts.
    """
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        resolver = A2ACardResolver(httpx_client=http_client, base_url=base_url.rstrip("/"))
        card = _normalize_card_urls(await resolver.get_agent_card(), base_url)
        client = await create_client(
            agent=card,
            client_config=ClientConfig(streaming=False, httpx_client=http_client),
        )
        try:
            message = new_text_message(
                json.dumps(payload, ensure_ascii=False),
                role=Role.ROLE_USER,
            )
            request = SendMessageRequest(message=message)
            responses = []
            async for response in client.send_message(request):
                responses.append(response)
            if not responses:
                raise RuntimeError(f"A2A agent at {base_url} returned an empty response stream.")
            raw_response = responses[-1]
            unwrapped = _unwrap_response(raw_response)
            return A2AResult(
                task_id=_read_attr(unwrapped, "id") or _read_attr(unwrapped, "task_id"),
                context_id=_read_attr(unwrapped, "context_id") or _read_attr(unwrapped, "contextId"),
                state=_state_name(unwrapped),
                artifact_text=_artifact_text(unwrapped),
                raw_response=raw_response,
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                maybe = close()
                if hasattr(maybe, "__await__"):
                    await maybe
