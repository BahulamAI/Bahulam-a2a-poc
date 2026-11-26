from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import uvicorn
from a2a.helpers import get_message_text, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState
from starlette.applications import Starlette

from bahulam_poc.contracts import json_text, parse_json_payload

logger = logging.getLogger("bahulam_poc.a2a")


class JsonAgentExecutor(AgentExecutor):
    """Adapts a normal Python handler to the official A2A AgentExecutor contract."""

    def __init__(self, handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]], agent_name: str):
        self.handler = handler
        self.agent_name = agent_name

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message(f"{self.agent_name} accepted the task."),
        )
        try:
            incoming_text = get_message_text(context.message)
            payload = parse_json_payload(incoming_text or "{}")
            result = await self.handler(payload)
            await updater.add_artifact(
                parts=[new_text_part(text=json_text(result), media_type="application/json")]
            )
            await updater.update_status(
                state=TaskState.TASK_STATE_COMPLETED,
                message=new_text_message(f"{self.agent_name} completed the task."),
            )
        except Exception as exc:
            logger.exception("%s task failed", self.agent_name)
            error_payload = {"ok": False, "agent": self.agent_name, "error": f"{type(exc).__name__}: {exc}"}
            try:
                await updater.add_artifact(
                    parts=[new_text_part(text=json_text(error_payload), media_type="application/json")]
                )
            except Exception:
                logger.exception("Could not publish error artifact")
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"{self.agent_name} failed: {type(exc).__name__}: {exc}"),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # The POC uses bounded local operations; hard cancellation is not yet implemented.
        raise NotImplementedError("Cancellation is not implemented in this POC. Use execution timeouts.")


def build_a2a_app(
    *,
    name: str,
    description: str,
    version: str,
    host: str,
    port: int,
    public_url: str | None = None,
    skill_id: str,
    skill_name: str,
    skill_description: str,
    examples: list[str],
    executor: AgentExecutor,
) -> Starlette:
    base_url = (public_url or f"http://{host}:{port}").rstrip("/")
    skill = AgentSkill(
        id=skill_id,
        name=skill_name,
        description=skill_description,
        tags=["bahulam", "coding-poc"],
        examples=examples,
        input_modes=["application/json", "text/plain"],
        output_modes=["application/json", "text/plain"],
    )
    card = AgentCard(
        name=name,
        description=description,
        version=version,
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=base_url, protocol_version="1.0")
        ],
        skills=[skill],
    )
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = []
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)


def serve(app: Starlette, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")
