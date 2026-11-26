from __future__ import annotations

import asyncio

import httpx

from bahulam_poc.settings import settings


async def check(name: str, base_url: str) -> bool:
    url = base_url.rstrip("/") + "/.well-known/agent-card.json"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            response.raise_for_status()
            card = response.json()
        print(f"[OK] {name}: {card.get('name')} ({url})")
        return True
    except Exception as exc:
        print(f"[DOWN] {name}: {url} -> {exc}")
        return False


async def main() -> int:
    results = await asyncio.gather(
        check("Workspace Setup Agent", settings.setup_agent_url),
        check("Code Builder Agent", settings.builder_agent_url),
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
