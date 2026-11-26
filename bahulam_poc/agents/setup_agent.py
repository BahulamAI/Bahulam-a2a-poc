from __future__ import annotations

import asyncio
from typing import Any

from bahulam_poc.workspaces import WorkspaceManager


class WorkspaceSetupAgent:
    """Owns workspace creation, virtualenv creation, and allowlisted package installation."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None):
        self.workspaces = workspace_manager or WorkspaceManager()

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        workspace_id = payload.get("workspace_id")
        if not isinstance(workspace_id, str):
            raise ValueError("workspace_id is required.")
        if action == "prepare_workspace":
            return await asyncio.to_thread(self.workspaces.prepare, workspace_id)
        if action == "install_dependencies":
            dependencies = payload.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list.")
            return await asyncio.to_thread(self.workspaces.install, workspace_id, dependencies)
        if action == "workspace_status":
            return await asyncio.to_thread(self.workspaces.details, workspace_id)
        raise ValueError(f"Unsupported setup action: {action!r}")
