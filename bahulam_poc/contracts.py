from __future__ import annotations

import json
from typing import Any


class ContractError(ValueError):
    """Raised when an agent request or artifact violates the POC contract."""


def parse_json_payload(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"A2A payload must be a JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("A2A payload must be a JSON object.")
    return value


def json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
