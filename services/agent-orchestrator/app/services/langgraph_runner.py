from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from app.core.config import settings
from app.schemas.workflow import (
    AgentMemorySnapshot,
    AgentPlanItem,
    AgentStep,
    WorkflowOutput,
    WorkflowRequest,
    WorkflowType,
)
from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.state_machine import machine

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional dependency
    END = None
    StateGraph = None


class _GraphState(TypedDict, total=False):
    payload: WorkflowRequest
    workflow_type: WorkflowType
    memory: AgentMemorySnapshot
    plan: list[AgentPlanItem]
    output: WorkflowOutput
    critique: dict[str, Any]
    iteration: int
    trace: list[str]


class LangGraphRunner:
    def __init__(self) -> None:
        self._avail = bool(StateGraph and END)
        self._g = self._build() if self._avail else None
        self._lk = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._avail and (self._g is not None)

    def _build(self):
        assert StateGraph is not None
        assert END is not None

        g = StateGraph(_GraphState)
        g.add_node("route", self._node_route)
        g.add_node("memory", self._node_memory)
        g.add_node("plan", self._node_plan)
        g.add_node("exec", self._node_exec)
        g.add_node("reflect", self._node_reflect)
        g.add_node("final", self._node_final)

        g.set_entry_point("route")
        g.add_edge("route", "memory")
        g.add_edge("memory", "plan")
        g.add_edge("plan", "exec")
        g.add_edge("exec", "reflect")
        g.add_conditional_edges("reflect", self._after_reflect, {"replan": "plan", "final": "final"})
        g.add_edge("final", END)
        return g.compile()

    async def _node_route(self, st: _GraphState) -> _GraphState:
        p = st["payload"].model_copy(deep=True)
        wt = await agentic_orchestrator.route_workflow(p, machine.route_intent)
        return {
            "workflow_type": wt,
            "trace": [f"route:{wt.value}"],
            "iteration": int(st.get("iteration", 0)),
        }

    async def _node_memory(self, st: _GraphState) -> _GraphState:
        m = agentic_orchestrator.retrieve_memory(st["payload"])
        tr = list(st.get("trace") or [])
        tr.append("memory")
        return {"memory": m, "trace": tr}

    async def _node_plan(self, st: _GraphState) -> _GraphState:
        p = st["payload"]
        wt = st.get("workflow_type") or p.workflow_type
        m = st.get("memory") or agentic_orchestrator.retrieve_memory(p)
        plan = await agentic_orchestrator.build_plan(
            p, wt, m, critique=st.get("critique"), existing_plan=st.get("plan")
        )
        tr = list(st.get("trace") or [])
        tr.append("plan")
        return {"plan": plan, "trace": tr}

    async def _node_exec(self, st: _GraphState) -> _GraphState:
        p = st["payload"].model_copy(deep=True)
        wt = st.get("workflow_type") or p.workflow_type
        p.workflow_type = wt

        out = await agentic_orchestrator.run(
            p,
            helper=machine,
            workflow_type=wt,
            memory=st.get("memory") or agentic_orchestrator.retrieve_memory(p),
            plan=st.get("plan") or [],
            prior_output=st.get("output"),
            runtime_engine="langgraph",
        )
        tr = list(st.get("trace") or [])
        tr.append("exec")
        return {"output": out, "trace": tr}

    async def _node_reflect(self, st: _GraphState) -> _GraphState:
        p = st["payload"]
        out = st["output"]
        crit = agentic_orchestrator.reflect(p, out)
        fus = crit.get("followup_actions") if isinstance(crit.get("followup_actions"), list) else []
        tr = list(st.get("trace") or [])
        tr.append("reflect")

        steps = list(out.steps)
        reason = str(crit.get("reason") or "")
        dup = False
        for s in steps:
            if s.agent == "Critic Agent" and str(s.output.get("reason") or "") == reason:
                dup = True
                break
        if not dup:
            steps.append(
                AgentStep(
                    agent="Critic Agent",
                    status="done",
                    output={"followup_actions": len(fus), "reason": reason, "iteration": int(st.get("iteration", 0))},
                )
            )
        out = out.model_copy(update={"steps": steps})
        nxt = int(st.get("iteration", 0)) + (1 if fus else 0)
        return {"critique": crit, "output": out, "iteration": nxt, "trace": tr}

    async def _node_final(self, st: _GraphState) -> _GraphState:
        p = st["payload"]
        out = agentic_orchestrator.finalize(p, st["output"])
        steps = list(out.steps)
        steps.insert(
            0,
            AgentStep(
                agent="LangGraph Runtime",
                status="done",
                input={"workflow_type": out.workflow_type.value},
                output={"engine": "langgraph", "trace": list(st.get("trace") or [])},
            ),
        )
        out = out.model_copy(update={"steps": steps})
        if out.run_id:
            agentic_orchestrator.persist_finalized_run(out)
        return {"output": out}

    def _after_reflect(self, st: _GraphState) -> str:
        crit = st.get("critique") or {}
        fus = crit.get("followup_actions") if isinstance(crit.get("followup_actions"), list) else []
        if fus and int(st.get("iteration", 0)) <= settings.agent_max_reflection_loops:
            return "replan"
        return "final"

    async def route_intent(self, txt: str) -> WorkflowType:
        p = WorkflowRequest(workflow_type=WorkflowType.VOICE_INQUIRY, user_input=txt)
        return await agentic_orchestrator.route_workflow(p, machine.route_intent)

    async def run(self, p: WorkflowRequest) -> WorkflowOutput:
        if not self.available:
            return await machine.run(p)
        assert self._g is not None
        async with self._lk:
            r = await self._g.ainvoke({"payload": p.model_copy(deep=True), "iteration": 0})
        out = r.get("output")
        if isinstance(out, WorkflowOutput):
            return out
        return await machine.run(p)
