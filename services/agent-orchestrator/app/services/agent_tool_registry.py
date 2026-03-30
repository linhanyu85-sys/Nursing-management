from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.workflow import AgentToolSpec

ToolHandler = Callable[..., Awaitable[tuple[str, dict[str, Any]]]]


@dataclass(slots=True)
class RegisteredAgentTool:
    spec: AgentToolSpec
    handler: ToolHandler


class AgentToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredAgentTool] = {}

    def register(self, spec: AgentToolSpec, handler: ToolHandler) -> None:
        self._tools[spec.id] = RegisteredAgentTool(spec=spec, handler=handler)

    def get(self, item_id: str) -> RegisteredAgentTool | None:
        return self._tools.get(item_id)

    def specs(self) -> list[AgentToolSpec]:
        return [tool.spec.model_copy() for tool in self._tools.values()]

    async def execute(self, item_id: str, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        tool = self.get(item_id)
        if tool is None:
            return "skipped", {"error": "tool_not_registered", "tool": item_id}
        return await tool.handler(**kwargs)
