from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowType(str, Enum):
    VOICE_INQUIRY = "voice_inquiry"
    HANDOVER = "handover_generate"
    RECOMMENDATION = "recommendation_request"
    DOCUMENT = "document_generation"
    AUTONOMOUS_CARE = "autonomous_care"
    SINGLE_MODEL_CHAT = "single_model_chat"


class ChatMode(str, Enum):
    SINGLE_MODEL = "single_model"
    AGENT_CLUSTER = "agent_cluster"


class WorkflowRequest(BaseModel):
    workflow_type: WorkflowType
    patient_id: str | None = None
    conversation_id: str | None = None
    department_id: str | None = None
    bed_no: str | None = None
    user_input: str | None = None
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    operator_notes: str | None = None
    attachments: list[str] = Field(default_factory=list)
    requested_by: str | None = None
    agent_mode: str | None = None
    execution_profile: str | None = None
    approved_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    agent: str
    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class AgentPlanItem(BaseModel):
    id: str
    title: str
    tool: str | None = None
    reason: str | None = None
    status: str = "pending"
    auto_runnable: bool = True


class AgentArtifact(BaseModel):
    kind: str
    title: str
    status: str = "created"
    reference_id: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentToolSpec(BaseModel):
    id: str
    title: str
    agent: str
    description: str
    retryable: bool = False
    max_retries: int = 0
    produces_artifact: bool = False
    category: str = "workflow"


class AgentToolExecution(BaseModel):
    item_id: str
    title: str
    tool: str | None = None
    agent: str
    status: str
    attempts: int = 1
    retryable: bool = False
    started_at: datetime
    finished_at: datetime
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentApprovalRequest(BaseModel):
    id: str
    item_id: str
    tool_id: str | None = None
    title: str
    reason: str | None = None
    status: str = "pending"
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    comment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMemorySnapshot(BaseModel):
    conversation_summary: str = ""
    patient_facts: list[str] = Field(default_factory=list)
    unresolved_tasks: list[str] = Field(default_factory=list)
    last_actions: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)


class SpecialistDigitalTwin(BaseModel):
    id: str
    title: str
    role: str
    focus: str
    status: str = "recommended"
    reason: str | None = None
    next_action: str | None = None


class HybridCareStage(BaseModel):
    id: str
    title: str
    status: str
    owner: str
    summary: str | None = None


class HealthDataCapsule(BaseModel):
    patient_id: str | None = None
    version: str | None = None
    event_summary: list[str] = Field(default_factory=list)
    time_axis: list[str] = Field(default_factory=list)
    data_layers: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)


class HealthGraphSnapshot(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[str] = Field(default_factory=list)
    dynamic_updates: list[str] = Field(default_factory=list)


class ReasoningCard(BaseModel):
    mode: str
    title: str
    summary: str
    confidence: float | None = None


class AgentRunRequestSnapshot(BaseModel):
    workflow_type: WorkflowType
    patient_id: str | None = None
    conversation_id: str | None = None
    department_id: str | None = None
    bed_no: str | None = None
    user_input: str | None = None
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    operator_notes: str | None = None
    requested_by: str | None = None
    agent_mode: str | None = None
    execution_profile: str | None = None
    attachments_count: int = 0
    approved_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[str] = Field(default_factory=list)


class AgentRunRecord(BaseModel):
    id: str
    status: str
    workflow_type: WorkflowType
    runtime_engine: str = "state_machine"
    request: AgentRunRequestSnapshot
    patient_id: str | None = None
    patient_name: str | None = None
    bed_no: str | None = None
    conversation_id: str | None = None
    agent_goal: str | None = None
    agent_mode: str = "workflow"
    summary: str | None = None
    plan: list[AgentPlanItem] = Field(default_factory=list)
    memory: AgentMemorySnapshot | None = None
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    specialist_profiles: list[SpecialistDigitalTwin] = Field(default_factory=list)
    hybrid_care_path: list[HybridCareStage] = Field(default_factory=list)
    data_capsule: HealthDataCapsule | None = None
    health_graph: HealthGraphSnapshot | None = None
    reasoning_cards: list[ReasoningCard] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    tool_executions: list[AgentToolExecution] = Field(default_factory=list)
    pending_approvals: list[AgentApprovalRequest] = Field(default_factory=list)
    retry_available: bool = False
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AgentQueueTask(BaseModel):
    id: str
    status: str
    payload: WorkflowRequest
    workflow_type: WorkflowType
    requested_engine: str | None = None
    runtime_engine: str | None = None
    priority: int = 100
    run_id: str | None = None
    summary: str | None = None
    approvals: list[AgentApprovalRequest] = Field(default_factory=list)
    last_output: WorkflowOutput | None = None
    error: str | None = None
    attempt_count: int = 0
    resume_count: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowOutput(BaseModel):
    workflow_type: WorkflowType
    summary: str
    findings: list[str]
    recommendations: list[dict[str, Any]]
    confidence: float
    review_required: bool
    context_hit: bool = False
    patient_id: str | None = None
    patient_name: str | None = None
    bed_no: str | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    run_id: str | None = None
    runtime_engine: str | None = None
    agent_goal: str | None = None
    agent_mode: str = "workflow"
    execution_profile: str | None = None
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    plan: list[AgentPlanItem] = Field(default_factory=list)
    memory: AgentMemorySnapshot | None = None
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    specialist_profiles: list[SpecialistDigitalTwin] = Field(default_factory=list)
    hybrid_care_path: list[HybridCareStage] = Field(default_factory=list)
    data_capsule: HealthDataCapsule | None = None
    health_graph: HealthGraphSnapshot | None = None
    reasoning_cards: list[ReasoningCard] = Field(default_factory=list)
    tool_executions: list[AgentToolExecution] = Field(default_factory=list)
    pending_approvals: list[AgentApprovalRequest] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    created_at: datetime


class WorkflowHistoryItem(BaseModel):
    id: str
    workflow_type: WorkflowType
    patient_id: str | None = None
    conversation_id: str | None = None
    department_id: str | None = None
    bed_no: str | None = None
    requested_by: str | None = None
    user_input: str | None = None
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float
    review_required: bool
    steps: list[AgentStep] = Field(default_factory=list)
    run_id: str | None = None
    runtime_engine: str | None = None
    agent_goal: str | None = None
    agent_mode: str = "workflow"
    execution_profile: str | None = None
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    plan: list[AgentPlanItem] = Field(default_factory=list)
    memory: AgentMemorySnapshot | None = None
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    specialist_profiles: list[SpecialistDigitalTwin] = Field(default_factory=list)
    hybrid_care_path: list[HybridCareStage] = Field(default_factory=list)
    data_capsule: HealthDataCapsule | None = None
    health_graph: HealthGraphSnapshot | None = None
    reasoning_cards: list[ReasoningCard] = Field(default_factory=list)
    tool_executions: list[AgentToolExecution] = Field(default_factory=list)
    pending_approvals: list[AgentApprovalRequest] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    created_at: datetime


class AIModelTask(BaseModel):
    model_id: str
    model_name: str
    role: str
    task: str
    enabled: bool = True


class AIModelOption(BaseModel):
    id: str
    name: str
    provider: str
    description: str


class AIClusterProfile(BaseModel):
    id: str
    name: str
    main_model: str
    description: str
    tasks: list[AIModelTask] = Field(default_factory=list)


class AIModelsResponse(BaseModel):
    single_models: list[AIModelOption] = Field(default_factory=list)
    cluster_profiles: list[AIClusterProfile] = Field(default_factory=list)


class AIChatRequest(BaseModel):
    mode: ChatMode = ChatMode.AGENT_CLUSTER
    selected_model: str | None = None
    cluster_profile: str = "nursing_default_cluster"
    patient_id: str | None = None
    conversation_id: str | None = None
    department_id: str | None = None
    bed_no: str | None = None
    user_input: str
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    operator_notes: str | None = None
    attachments: list[str] = Field(default_factory=list)
    requested_by: str | None = None
    agent_mode: str | None = None
    execution_profile: str | None = None


class AIChatResponse(BaseModel):
    mode: ChatMode
    selected_model: str | None = None
    cluster_profile: str | None = None
    conversation_id: str | None = None
    workflow_type: WorkflowType
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float
    review_required: bool
    steps: list[AgentStep] = Field(default_factory=list)
    model_plan: list[AIModelTask] = Field(default_factory=list)
    run_id: str | None = None
    runtime_engine: str | None = None
    agent_goal: str | None = None
    agent_mode: str = "workflow"
    execution_profile: str | None = None
    mission_title: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    plan: list[AgentPlanItem] = Field(default_factory=list)
    memory: AgentMemorySnapshot | None = None
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    specialist_profiles: list[SpecialistDigitalTwin] = Field(default_factory=list)
    hybrid_care_path: list[HybridCareStage] = Field(default_factory=list)
    data_capsule: HealthDataCapsule | None = None
    health_graph: HealthGraphSnapshot | None = None
    reasoning_cards: list[ReasoningCard] = Field(default_factory=list)
    pending_approvals: list[AgentApprovalRequest] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    created_at: datetime


class AgentQueueEnqueueRequest(BaseModel):
    payload: WorkflowRequest
    requested_engine: str | None = None
    priority: int = Field(default=100, ge=1, le=1000)


class AgentQueueDecisionRequest(BaseModel):
    approval_ids: list[str] = Field(default_factory=list)
    decided_by: str | None = None
    comment: str | None = None


AgentQueueTask.model_rebuild()
