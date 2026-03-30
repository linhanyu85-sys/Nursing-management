from __future__ import annotations

from app.core.config import settings
from app.schemas.workflow import WorkflowOutput, WorkflowRequest, WorkflowType
from app.services.history_store import workflow_history_store
from app.services.langgraph_runner import LangGraphRunner
from app.services.state_machine import machine


class AgentRuntime:
    """Runtime selector for orchestration engine.

    Default keeps stable state-machine behavior. LangGraph stays optional.
    """

    def __init__(self) -> None:
        self._langgraph = LangGraphRunner()
        self._engine_override: str | None = None

    def _normalize_engine(self, engine: str | None) -> str:
        value = (engine or "").strip().lower()
        if value in {"graph", "langgraph"}:
            return "langgraph"
        return "state_machine"

    def _configured_engine(self, engine_override: str | None = None) -> str:
        if engine_override:
            return self._normalize_engine(engine_override)
        if self._engine_override:
            return self._normalize_engine(self._engine_override)
        engine = (settings.agent_runtime_engine or "state_machine").strip().lower()
        return self._normalize_engine(engine)

    def _resolved_engine(self, engine_override: str | None = None) -> tuple[str, str, str]:
        configured = self._configured_engine(engine_override)
        if configured == "langgraph":
            if self._langgraph.available:
                return configured, "langgraph", ""
            return configured, "state_machine", "langgraph_unavailable_fallback"
        return configured, "state_machine", ""

    def status(self) -> dict[str, str | bool]:
        configured, active, reason = self._resolved_engine()
        return {
            "configured_engine": configured,
            "active_engine": active,
            "langgraph_available": self._langgraph.available,
            "override_enabled": bool(self._engine_override),
            "fallback_reason": reason,
        }

    def set_engine(self, engine: str) -> dict[str, str | bool]:
        normalized = self._normalize_engine(engine)
        self._engine_override = normalized
        return self.status()

    def clear_override(self) -> dict[str, str | bool]:
        self._engine_override = None
        return self.status()

    def _engine(self, engine_override: str | None = None) -> str:
        _configured, active, _reason = self._resolved_engine(engine_override)
        return active

    def configured_engine(self) -> str:
        configured, _active, _reason = self._resolved_engine()
        return configured

    def fallback_reason(self) -> str:
        _configured, _active, reason = self._resolved_engine()
        return reason

    def langgraph_available(self) -> bool:
        return self._langgraph.available

    def has_override(self) -> bool:
        return bool(self._engine_override)

    def override_value(self) -> str:
        return self._engine_override or ""

    async def route_intent(self, text: str, *, engine_override: str | None = None) -> WorkflowType:
        if self._engine(engine_override) == "langgraph" and self._langgraph.available:
            return await self._langgraph.route_intent(text)
        return await machine.route_intent(text)

    async def run(self, payload: WorkflowRequest, *, engine_override: str | None = None) -> WorkflowOutput:
        if self._engine(engine_override) == "langgraph" and self._langgraph.available:
            output = await self._langgraph.run(payload.model_copy(deep=True))
            workflow_history_store.append(payload, output)
            return output
        return await machine.run(payload)


runtime = AgentRuntime()
