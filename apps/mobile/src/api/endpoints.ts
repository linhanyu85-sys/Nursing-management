import { asrBaseURL, httpClient, isMockMode } from "./client";
import { mockApi } from "./mock";
import type {
  AssistantDigest,
  AIChatMode,
  AIExecutionProfile,
  AIChatResponse,
  AIModelsCatalog,
  AIRuntimeStatus,
  AgentRunRecord,
  AgentQueueTask,
  PatientCaseBundle,
  PatientCaseUpsertPayload,
  ClinicalOrder,
  CollabAccount,
  CollabContactList,
  CollaborationThreadDetail,
  CollaborationThreadHistoryItem,
  ConversationHistoryItem,
  DepartmentOption,
  DirectSession,
  DirectSessionDetail,
  DocumentDraft,
  DocumentTemplate,
  HandoverResult,
  MultimodalAnalysisResult,
  OrderListOut,
  Patient,
  PatientContext,
  RecommendationResult,
  UserInfo,
} from "../types";

function extractDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const nested = (detail as any).detail;
    if (typeof nested === "string") {
      return nested;
    }
  }
  return "";
}

export function getApiErrorMessage(error: unknown, fallback = "服务暂时不可用，请稍后重试"): string {
  const status = Number((error as any)?.response?.status || 0);
  const detail = extractDetail((error as any)?.response?.data);

  if (status === 401 || detail === "invalid_credentials") {
    return "账号或密码不正确，请重新输入。";
  }
  if (status === 409 || detail === "username_exists") {
    return "该用户名已存在，请更换后再试。";
  }
  if (status === 502 || detail === "upstream_unavailable") {
    return "后台服务还没准备好，请先启动后端核心服务。";
  }
  if (status === 504 || detail === "upstream_timeout") {
    return "系统响应超时，请稍后再试。";
  }
  if (detail && detail !== "upstream_error") {
    return detail;
  }

  const message = String((error as any)?.message || "");
  if (message === "Network Error") {
    return "网络连接失败，请确认手机和电脑在同一局域网，或直接改用本机地址。";
  }
  if (message) {
    return message;
  }
  return fallback;
}

function toStringArray(items: unknown): string[] {
  return Array.isArray(items) ? items.map((item) => String(item)) : [];
}

function toRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

const mapRecommendation = (data: any): RecommendationResult => ({
  id: String(data?.id || ""),
  patient_id: String(data?.patient_id || ""),
  summary: String(data?.summary || ""),
  findings: Array.isArray(data?.findings) ? data.findings.map((item: any) => String(item)) : [],
  recommendations: Array.isArray(data?.recommendations) ? data.recommendations : [],
  confidence: Number(data?.confidence ?? 0),
  review_required: Boolean(data?.review_required ?? true),
  metadata: data?.metadata || {},
});

const mapAgentStep = (data: any) => ({
  agent: String(data?.agent || ""),
  status: String(data?.status || ""),
  note: data?.note ? String(data.note) : undefined,
  input: toRecord(data?.input),
  output: toRecord(data?.output),
});

const mapAgentPlanItem = (data: any) => ({
  id: String(data?.id || ""),
  title: String(data?.title || ""),
  tool: data?.tool ? String(data.tool) : undefined,
  reason: data?.reason ? String(data.reason) : undefined,
  status: String(data?.status || "pending"),
  auto_runnable: data?.auto_runnable !== undefined ? Boolean(data.auto_runnable) : undefined,
});

const mapAgentArtifact = (data: any) => ({
  kind: String(data?.kind || ""),
  title: String(data?.title || ""),
  status: String(data?.status || "created"),
  reference_id: data?.reference_id ? String(data.reference_id) : undefined,
  summary: data?.summary ? String(data.summary) : undefined,
  metadata: toRecord(data?.metadata),
});

const mapAgentToolExecution = (data: any) => ({
  item_id: String(data?.item_id || ""),
  title: String(data?.title || ""),
  tool: data?.tool ? String(data.tool) : undefined,
  agent: String(data?.agent || ""),
  status: String(data?.status || ""),
  attempts: Number(data?.attempts ?? 1),
  retryable: Boolean(data?.retryable),
  started_at: String(data?.started_at || new Date().toISOString()),
  finished_at: String(data?.finished_at || new Date().toISOString()),
  output: toRecord(data?.output),
  error: data?.error ? String(data.error) : undefined,
});

const mapAgentApproval = (data: any) => ({
  id: String(data?.id || ""),
  item_id: String(data?.item_id || ""),
  tool_id: data?.tool_id ? String(data.tool_id) : undefined,
  title: String(data?.title || ""),
  reason: data?.reason ? String(data.reason) : undefined,
  status: String(data?.status || "pending"),
  created_at: String(data?.created_at || ""),
  decided_at: data?.decided_at ? String(data.decided_at) : undefined,
  decided_by: data?.decided_by ? String(data.decided_by) : undefined,
  comment: data?.comment ? String(data.comment) : undefined,
  metadata: toRecord(data?.metadata),
});

const mapAgentMemory = (data: any) => {
  const source = toRecord(data);
  if (!source) {
    return undefined;
  }
  return {
    conversation_summary: String(source.conversation_summary || ""),
    patient_facts: toStringArray(source.patient_facts),
    unresolved_tasks: toStringArray(source.unresolved_tasks),
    last_actions: toStringArray(source.last_actions),
    user_preferences: toStringArray(source.user_preferences),
  };
};

const mapRoleLane = (data: any) => ({
  id: String(data?.id || ""),
  title: String(data?.title || ""),
  role: String(data?.role || ""),
  focus: String(data?.focus || ""),
  status: String(data?.status || "recommended"),
  reason: data?.reason ? String(data.reason) : undefined,
  next_action: data?.next_action ? String(data.next_action) : undefined,
});

const mapServiceRelayStage = (data: any) => ({
  id: String(data?.id || ""),
  title: String(data?.title || ""),
  status: String(data?.status || "pending"),
  owner: String(data?.owner || ""),
  summary: data?.summary ? String(data.summary) : undefined,
});

const mapPatientStateCapsule = (data: any) => {
  const source = toRecord(data);
  if (!source) {
    return undefined;
  }
  return {
    patient_id: source.patient_id ? String(source.patient_id) : undefined,
    version: source.version ? String(source.version) : undefined,
    event_summary: toStringArray(source.event_summary),
    time_axis: toStringArray(source.time_axis),
    data_layers: toStringArray(source.data_layers),
    risk_factors: toStringArray(source.risk_factors),
  };
};

const mapCareGraph = (data: any) => {
  const source = toRecord(data);
  if (!source) {
    return undefined;
  }
  return {
    nodes: toStringArray(source.nodes),
    edges: toStringArray(source.edges),
    dynamic_updates: toStringArray(source.dynamic_updates),
  };
};

const mapReasoningCheckpoint = (data: any) => ({
  mode: String(data?.mode || ""),
  title: String(data?.title || ""),
  summary: String(data?.summary || ""),
  confidence: data?.confidence !== undefined ? Number(data.confidence) : undefined,
});

const mapWorkflowOutput = (data: any) => ({
  workflow_type: String(data?.workflow_type || ""),
  summary: String(data?.summary || ""),
  findings: toStringArray(data?.findings),
  recommendations: Array.isArray(data?.recommendations) ? data.recommendations : [],
  confidence: Number(data?.confidence ?? 0),
  review_required: Boolean(data?.review_required ?? true),
  patient_id: data?.patient_id ? String(data.patient_id) : undefined,
  patient_name: data?.patient_name ? String(data.patient_name) : undefined,
  bed_no: data?.bed_no ? String(data.bed_no) : undefined,
  steps: Array.isArray(data?.steps) ? data.steps.map(mapAgentStep) : [],
  run_id: data?.run_id ? String(data.run_id) : undefined,
  runtime_engine: data?.runtime_engine ? String(data.runtime_engine) : undefined,
  agent_goal: data?.agent_goal ? String(data.agent_goal) : undefined,
  agent_mode: String(data?.agent_mode || "workflow"),
  execution_profile: data?.execution_profile ? String(data.execution_profile) : undefined,
  mission_title: data?.mission_title ? String(data.mission_title) : undefined,
  success_criteria: toStringArray(data?.success_criteria),
  plan: Array.isArray(data?.plan) ? data.plan.map(mapAgentPlanItem) : [],
  memory: mapAgentMemory(data?.memory),
  artifacts: Array.isArray(data?.artifacts) ? data.artifacts.map(mapAgentArtifact) : [],
  specialist_profiles: Array.isArray(data?.specialist_profiles) ? data.specialist_profiles.map(mapRoleLane) : [],
  hybrid_care_path: Array.isArray(data?.hybrid_care_path) ? data.hybrid_care_path.map(mapServiceRelayStage) : [],
  data_capsule: mapPatientStateCapsule(data?.data_capsule),
  health_graph: mapCareGraph(data?.health_graph),
  reasoning_cards: Array.isArray(data?.reasoning_cards) ? data.reasoning_cards.map(mapReasoningCheckpoint) : [],
  tool_executions: Array.isArray(data?.tool_executions) ? data.tool_executions.map(mapAgentToolExecution) : [],
  pending_approvals: Array.isArray(data?.pending_approvals) ? data.pending_approvals.map(mapAgentApproval) : [],
  next_actions: toStringArray(data?.next_actions),
  created_at: String(data?.created_at || new Date().toISOString()),
});

const mapAgentRunRecord = (data: any): AgentRunRecord => ({
  id: String(data?.id || ""),
  status: String(data?.status || "running"),
  workflow_type: String(data?.workflow_type || data?.request?.workflow_type || ""),
  runtime_engine: String(data?.runtime_engine || "state_machine"),
  request: {
    workflow_type: String(data?.request?.workflow_type || data?.workflow_type || ""),
    patient_id: data?.request?.patient_id ? String(data.request.patient_id) : undefined,
    conversation_id: data?.request?.conversation_id ? String(data.request.conversation_id) : undefined,
    department_id: data?.request?.department_id ? String(data.request.department_id) : undefined,
    bed_no: data?.request?.bed_no ? String(data.request.bed_no) : undefined,
    user_input: data?.request?.user_input ? String(data.request.user_input) : undefined,
    mission_title: data?.request?.mission_title ? String(data.request.mission_title) : undefined,
    success_criteria: toStringArray(data?.request?.success_criteria),
    operator_notes: data?.request?.operator_notes ? String(data.request.operator_notes) : undefined,
    requested_by: data?.request?.requested_by ? String(data.request.requested_by) : undefined,
    agent_mode: data?.request?.agent_mode ? String(data.request.agent_mode) : undefined,
    execution_profile: data?.request?.execution_profile ? String(data.request.execution_profile) : undefined,
    attachments_count: Number(data?.request?.attachments_count ?? 0),
    approved_actions: toStringArray(data?.request?.approved_actions),
    rejected_actions: toStringArray(data?.request?.rejected_actions),
  },
  patient_id: data?.patient_id ? String(data.patient_id) : undefined,
  patient_name: data?.patient_name ? String(data.patient_name) : undefined,
  bed_no: data?.bed_no ? String(data.bed_no) : undefined,
  conversation_id: data?.conversation_id ? String(data.conversation_id) : undefined,
  agent_goal: data?.agent_goal ? String(data.agent_goal) : undefined,
  agent_mode: String(data?.agent_mode || "workflow"),
  summary: data?.summary ? String(data.summary) : undefined,
  plan: Array.isArray(data?.plan) ? data.plan.map(mapAgentPlanItem) : [],
  memory: mapAgentMemory(data?.memory),
  artifacts: Array.isArray(data?.artifacts) ? data.artifacts.map(mapAgentArtifact) : [],
  specialist_profiles: Array.isArray(data?.specialist_profiles) ? data.specialist_profiles.map(mapRoleLane) : [],
  hybrid_care_path: Array.isArray(data?.hybrid_care_path) ? data.hybrid_care_path.map(mapServiceRelayStage) : [],
  data_capsule: mapPatientStateCapsule(data?.data_capsule),
  health_graph: mapCareGraph(data?.health_graph),
  reasoning_cards: Array.isArray(data?.reasoning_cards) ? data.reasoning_cards.map(mapReasoningCheckpoint) : [],
  next_actions: toStringArray(data?.next_actions),
  steps: Array.isArray(data?.steps) ? data.steps.map(mapAgentStep) : [],
  tool_executions: Array.isArray(data?.tool_executions) ? data.tool_executions.map(mapAgentToolExecution) : [],
  pending_approvals: Array.isArray(data?.pending_approvals) ? data.pending_approvals.map(mapAgentApproval) : [],
  retry_available: Boolean(data?.retry_available),
  error: data?.error ? String(data.error) : undefined,
  created_at: String(data?.created_at || new Date().toISOString()),
  updated_at: String(data?.updated_at || new Date().toISOString()),
  completed_at: data?.completed_at ? String(data.completed_at) : undefined,
});

const mapAiRuntimeStatus = (data: any): AIRuntimeStatus => ({
  configured_engine: String(data?.configured_engine || "state_machine"),
  active_engine: String(data?.active_engine || "state_machine"),
  langgraph_available: Boolean(data?.langgraph_available),
  override_enabled: Boolean(data?.override_enabled),
  fallback_reason: String(data?.fallback_reason || ""),
  planner_llm_enabled: Boolean(data?.planner_llm_enabled),
  planner_timeout_sec: Number(data?.planner_timeout_sec ?? 0),
  planner_max_steps: Number(data?.planner_max_steps ?? 0),
  local_model_service_reachable: Boolean(data?.local_model_service_reachable),
  available_local_models: toStringArray(data?.available_local_models),
  local_model_aliases: toRecord(data?.local_model_aliases) as AIRuntimeStatus["local_model_aliases"],
  approval_required_tools: toStringArray(data?.approval_required_tools),
  task_queue: toRecord(data?.task_queue) as AIRuntimeStatus["task_queue"],
});

const mapQueueTask = (data: any): AgentQueueTask => ({
  id: String(data?.id || ""),
  status: String(data?.status || "queued"),
  payload: {
    workflow_type: String(data?.payload?.workflow_type || data?.workflow_type || ""),
    patient_id: data?.payload?.patient_id ? String(data.payload.patient_id) : undefined,
    conversation_id: data?.payload?.conversation_id ? String(data.payload.conversation_id) : undefined,
    department_id: data?.payload?.department_id ? String(data.payload.department_id) : undefined,
    bed_no: data?.payload?.bed_no ? String(data.payload.bed_no) : undefined,
    user_input: data?.payload?.user_input ? String(data.payload.user_input) : undefined,
    mission_title: data?.payload?.mission_title ? String(data.payload.mission_title) : undefined,
    success_criteria: toStringArray(data?.payload?.success_criteria),
    operator_notes: data?.payload?.operator_notes ? String(data.payload.operator_notes) : undefined,
    attachments: toStringArray(data?.payload?.attachments),
    requested_by: data?.payload?.requested_by ? String(data.payload.requested_by) : undefined,
    agent_mode: data?.payload?.agent_mode ? String(data.payload.agent_mode) : undefined,
    execution_profile: data?.payload?.execution_profile ? String(data.payload.execution_profile) : undefined,
    approved_actions: toStringArray(data?.payload?.approved_actions),
    rejected_actions: toStringArray(data?.payload?.rejected_actions),
  },
  workflow_type: String(data?.workflow_type || data?.payload?.workflow_type || ""),
  requested_engine: data?.requested_engine ? String(data.requested_engine) : undefined,
  runtime_engine: data?.runtime_engine ? String(data.runtime_engine) : undefined,
  priority: Number(data?.priority ?? 100),
  run_id: data?.run_id ? String(data.run_id) : undefined,
  summary: data?.summary ? String(data.summary) : undefined,
  approvals: Array.isArray(data?.approvals) ? data.approvals.map(mapAgentApproval) : [],
  last_output: data?.last_output ? mapWorkflowOutput(data.last_output) : undefined,
  error: data?.error ? String(data.error) : undefined,
  attempt_count: Number(data?.attempt_count ?? 0),
  resume_count: Number(data?.resume_count ?? 0),
  created_at: String(data?.created_at || new Date().toISOString()),
  updated_at: String(data?.updated_at || new Date().toISOString()),
  started_at: data?.started_at ? String(data.started_at) : undefined,
  completed_at: data?.completed_at ? String(data.completed_at) : undefined,
});

const mapConversationHistory = (items: any[]): ConversationHistoryItem[] =>
  (Array.isArray(items) ? items : []).map((item) => ({
    id: String(item?.id || ""),
    source: String(item?.source || ""),
    workflow_type: String(item?.workflow_type || ""),
    patient_id: item?.patient_id ? String(item.patient_id) : undefined,
    conversation_id: item?.conversation_id ? String(item.conversation_id) : undefined,
    user_input: item?.user_input ? String(item.user_input) : undefined,
    summary: String(item?.summary || ""),
    created_at: String(item?.created_at || ""),
    confidence: item?.confidence !== undefined ? Number(item.confidence) : undefined,
    review_required: item?.review_required !== undefined ? Boolean(item.review_required) : undefined,
    run_id: item?.run_id ? String(item.run_id) : undefined,
    runtime_engine: item?.runtime_engine ? String(item.runtime_engine) : undefined,
    findings: toStringArray(item?.findings),
    recommendations: Array.isArray(item?.recommendations) ? item.recommendations : [],
    steps: Array.isArray(item?.steps) ? item.steps.map(mapAgentStep) : [],
    agent_goal: item?.agent_goal ? String(item.agent_goal) : undefined,
    agent_mode: item?.agent_mode ? String(item.agent_mode) : undefined,
    execution_profile: item?.execution_profile ? String(item.execution_profile) : undefined,
    mission_title: item?.mission_title ? String(item.mission_title) : undefined,
    success_criteria: toStringArray(item?.success_criteria),
    plan: Array.isArray(item?.plan) ? item.plan.map(mapAgentPlanItem) : [],
    memory: mapAgentMemory(item?.memory),
    artifacts: Array.isArray(item?.artifacts) ? item.artifacts.map(mapAgentArtifact) : [],
    specialist_profiles: Array.isArray(item?.specialist_profiles) ? item.specialist_profiles.map(mapRoleLane) : [],
    hybrid_care_path: Array.isArray(item?.hybrid_care_path) ? item.hybrid_care_path.map(mapServiceRelayStage) : [],
    data_capsule: mapPatientStateCapsule(item?.data_capsule),
    health_graph: mapCareGraph(item?.health_graph),
    reasoning_cards: Array.isArray(item?.reasoning_cards) ? item.reasoning_cards.map(mapReasoningCheckpoint) : [],
    pending_approvals: Array.isArray(item?.pending_approvals) ? item.pending_approvals.map(mapAgentApproval) : [],
    next_actions: toStringArray(item?.next_actions),
  }));

const mapThreadHistory = (items: any[]): CollaborationThreadHistoryItem[] =>
  (Array.isArray(items) ? items : []).map((item) => ({
    thread: {
      id: String(item?.thread?.id || ""),
      patient_id: item?.thread?.patient_id ? String(item.thread.patient_id) : undefined,
      encounter_id: item?.thread?.encounter_id ? String(item.thread.encounter_id) : undefined,
      thread_type: String(item?.thread?.thread_type || "discussion"),
      title: String(item?.thread?.title || ""),
      created_by: item?.thread?.created_by ? String(item.thread.created_by) : undefined,
      status: String(item?.thread?.status || "open"),
      created_at: String(item?.thread?.created_at || ""),
      updated_at: String(item?.thread?.updated_at || ""),
    },
    latest_message: item?.latest_message
      ? {
          id: String(item.latest_message.id || ""),
          thread_id: String(item.latest_message.thread_id || ""),
          sender_id: item.latest_message.sender_id ? String(item.latest_message.sender_id) : undefined,
          message_type: String(item.latest_message.message_type || "text"),
          content: String(item.latest_message.content || ""),
          attachment_refs: Array.isArray(item.latest_message.attachment_refs)
            ? item.latest_message.attachment_refs.map((x: any) => String(x))
            : [],
          ai_generated: Boolean(item.latest_message.ai_generated),
          created_at: String(item.latest_message.created_at || ""),
        }
      : null,
    message_count: Number(item?.message_count ?? 0),
  }));

const mapAccount = (item: any): CollabAccount => ({
  id: String(item?.id || ""),
  username: item?.username ? String(item.username) : undefined,
  account: String(item?.account || item?.username || ""),
  full_name: String(item?.full_name || ""),
  role_code: String(item?.role_code || ""),
  phone: item?.phone ? String(item.phone) : undefined,
  email: item?.email ? String(item.email) : undefined,
  department: item?.department ? String(item.department) : undefined,
  title: item?.title ? String(item.title) : undefined,
  status: item?.status ? String(item.status) : undefined,
});

const mapDepartment = (item: any): DepartmentOption => ({
  id: String(item?.id || ""),
  code: item?.code ? String(item.code) : undefined,
  name: String(item?.name || ""),
  ward_type: item?.ward_type ? String(item.ward_type) : undefined,
  location: item?.location ? String(item.location) : undefined,
});

const mapDirectSession = (item: any): DirectSession => ({
  id: String(item?.id || ""),
  user_id: String(item?.user_id || ""),
  contact_user_id: String(item?.contact_user_id || ""),
  patient_id: item?.patient_id ? String(item.patient_id) : undefined,
  status: String(item?.status || "open"),
  created_at: String(item?.created_at || ""),
  updated_at: String(item?.updated_at || ""),
  latest_message: item?.latest_message
    ? {
        id: String(item.latest_message.id || ""),
        thread_id: String(item.latest_message.thread_id || ""),
        sender_id: item.latest_message.sender_id ? String(item.latest_message.sender_id) : undefined,
        message_type: String(item.latest_message.message_type || "text"),
        content: String(item.latest_message.content || ""),
        attachment_refs: Array.isArray(item.latest_message.attachment_refs)
          ? item.latest_message.attachment_refs.map((x: any) => String(x))
          : [],
        ai_generated: Boolean(item.latest_message.ai_generated),
        created_at: String(item.latest_message.created_at || ""),
      }
    : null,
  unread_count: Number(item?.unread_count ?? 0),
  contact: item?.contact ? mapAccount(item.contact) : undefined,
});

const mapAiChatResponse = (data: any): AIChatResponse => ({
  mode: data?.mode === "single_model" ? "single_model" : "agent_cluster",
  selected_model: data?.selected_model ? String(data.selected_model) : undefined,
  cluster_profile: data?.cluster_profile ? String(data.cluster_profile) : undefined,
  conversation_id: data?.conversation_id ? String(data.conversation_id) : undefined,
  run_id: data?.run_id ? String(data.run_id) : undefined,
  runtime_engine: data?.runtime_engine ? String(data.runtime_engine) : undefined,
  workflow_type: String(data?.workflow_type || ""),
  summary: String(data?.summary || ""),
  findings: toStringArray(data?.findings),
  recommendations: Array.isArray(data?.recommendations) ? data.recommendations : [],
  confidence: Number(data?.confidence ?? 0),
  review_required: Boolean(data?.review_required ?? true),
  steps: Array.isArray(data?.steps) ? data.steps.map(mapAgentStep) : [],
  model_plan: Array.isArray(data?.model_plan)
    ? data.model_plan.map((x: any) => ({
        model_id: String(x?.model_id || ""),
        model_name: String(x?.model_name || ""),
        role: String(x?.role || ""),
        task: String(x?.task || ""),
        enabled: Boolean(x?.enabled ?? true),
      }))
    : [],
  agent_goal: data?.agent_goal ? String(data.agent_goal) : undefined,
  agent_mode: String(data?.agent_mode || "workflow"),
  mission_title: data?.mission_title ? String(data.mission_title) : undefined,
  success_criteria: toStringArray(data?.success_criteria),
  plan: Array.isArray(data?.plan) ? data.plan.map(mapAgentPlanItem) : [],
  memory: mapAgentMemory(data?.memory),
  artifacts: Array.isArray(data?.artifacts) ? data.artifacts.map(mapAgentArtifact) : [],
  specialist_profiles: Array.isArray(data?.specialist_profiles) ? data.specialist_profiles.map(mapRoleLane) : [],
  hybrid_care_path: Array.isArray(data?.hybrid_care_path) ? data.hybrid_care_path.map(mapServiceRelayStage) : [],
  data_capsule: mapPatientStateCapsule(data?.data_capsule),
  health_graph: mapCareGraph(data?.health_graph),
  reasoning_cards: Array.isArray(data?.reasoning_cards) ? data.reasoning_cards.map(mapReasoningCheckpoint) : [],
  pending_approvals: Array.isArray(data?.pending_approvals) ? data.pending_approvals.map(mapAgentApproval) : [],
  next_actions: toStringArray(data?.next_actions),
  created_at: String(data?.created_at || new Date().toISOString()),
  execution_profile: data?.execution_profile ? String(data.execution_profile) : undefined,
});

const mapOrder = (row: any): ClinicalOrder => ({
  id: String(row?.id || ""),
  patient_id: String(row?.patient_id || ""),
  encounter_id: row?.encounter_id ? String(row.encounter_id) : undefined,
  order_no: String(row?.order_no || ""),
  order_type: String(row?.order_type || ""),
  title: String(row?.title || ""),
  instruction: String(row?.instruction || ""),
  route: row?.route ? String(row.route) : undefined,
  dosage: row?.dosage ? String(row.dosage) : undefined,
  frequency: row?.frequency ? String(row.frequency) : undefined,
  priority: String(row?.priority || "P2"),
  status: String(row?.status || "pending"),
  ordered_by: row?.ordered_by ? String(row.ordered_by) : undefined,
  ordered_at: row?.ordered_at ? String(row.ordered_at) : undefined,
  due_at: row?.due_at ? String(row.due_at) : undefined,
  requires_double_check: Boolean(row?.requires_double_check),
  check_by: row?.check_by ? String(row.check_by) : undefined,
  check_at: row?.check_at ? String(row.check_at) : undefined,
  executed_by: row?.executed_by ? String(row.executed_by) : undefined,
  executed_at: row?.executed_at ? String(row.executed_at) : undefined,
  execution_note: row?.execution_note ? String(row.execution_note) : undefined,
  exception_reason: row?.exception_reason ? String(row.exception_reason) : undefined,
  risk_hints: Array.isArray(row?.risk_hints) ? row.risk_hints.map((x: any) => String(x)) : [],
  audit_trail: Array.isArray(row?.audit_trail)
    ? row.audit_trail.map((x: any) => ({
        action: String(x?.action || ""),
        actor: String(x?.actor || ""),
        note: x?.note ? String(x.note) : undefined,
        created_at: String(x?.created_at || ""),
      }))
    : [],
});

const mapOrderList = (data: any): OrderListOut => ({
  patient_id: String(data?.patient_id || ""),
  stats: {
    pending: Number(data?.stats?.pending ?? 0),
    due_30m: Number(data?.stats?.due_30m ?? 0),
    overdue: Number(data?.stats?.overdue ?? 0),
    high_alert: Number(data?.stats?.high_alert ?? 0),
  },
  orders: Array.isArray(data?.orders) ? data.orders.map(mapOrder) : [],
});

const PRIMARY_DEPARTMENT_CODE = "dep-card-01";
const PRIMARY_DEPARTMENT_ID = "11111111-1111-1111-1111-111111111001";
const WARD_FALLBACK_IDS = [PRIMARY_DEPARTMENT_CODE, PRIMARY_DEPARTMENT_ID] as const;

function uniqKeepOrder(items: string[]): string[] {
  const hit = new Set<string>();
  const output: string[] = [];
  items.forEach((raw) => {
    const value = String(raw || "").trim();
    if (!value || hit.has(value)) {
      return;
    }
    hit.add(value);
    output.push(value);
  });
  return output;
}

function normalizeMatchText(value: unknown): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[-_.·/]/g, "");
}

function uniqueDepartments(items: DepartmentOption[]): DepartmentOption[] {
  const seen = new Set<string>();
  const output: DepartmentOption[] = [];
  items.forEach((item) => {
    const key = String(item?.id || "").trim();
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    output.push(item);
  });
  return output;
}

function departmentPriority(item: DepartmentOption): number {
  let score = 0;
  if (item.id === PRIMARY_DEPARTMENT_ID) {
    score += 10;
  }
  if (item.code === PRIMARY_DEPARTMENT_CODE) {
    score += 9;
  }
  if (String(item.name || "").includes("护理单元")) {
    score += 3;
  }
  if (String(item.name || "").includes("心内")) {
    score += 2;
  }
  return score;
}

function mergeUserInfo(baseUser: UserInfo, liveAccount?: CollabAccount | null): UserInfo {
  if (!liveAccount) {
    return {
      ...baseUser,
      username: baseUser.username || baseUser.account,
      account: baseUser.account || baseUser.username,
    };
  }

  return {
    ...baseUser,
    username: liveAccount.username || baseUser.username || liveAccount.account || baseUser.account,
    account: liveAccount.account || liveAccount.username || baseUser.account || baseUser.username,
    full_name: liveAccount.full_name || baseUser.full_name,
    role_code: liveAccount.role_code || baseUser.role_code,
    phone: liveAccount.phone ?? baseUser.phone,
    email: liveAccount.email ?? baseUser.email,
    department: liveAccount.department ?? baseUser.department,
    title: liveAccount.title ?? baseUser.title,
    status: liveAccount.status || baseUser.status,
  };
}

async function fetchWardBedCount(departmentId: string): Promise<number> {
  const { data } = await httpClient.get(`/api/wards/${encodeURIComponent(departmentId)}/beds`);
  return Array.isArray(data) ? data.length : 0;
}

async function resolvePreferredDepartmentId(
  departments: DepartmentOption[],
  departmentHint?: string | null,
): Promise<string> {
  const normalizedHint = normalizeMatchText(departmentHint);
  const exactMatches = departments.filter((item) => {
    const id = normalizeMatchText(item.id);
    const code = normalizeMatchText(item.code);
    const name = normalizeMatchText(item.name);
    return Boolean(normalizedHint) && (normalizedHint === id || normalizedHint === code || normalizedHint === name);
  });

  const fuzzyMatches = departments.filter((item) => {
    const code = normalizeMatchText(item.code);
    const name = normalizeMatchText(item.name);
    const location = normalizeMatchText(item.location);
    return (
      Boolean(normalizedHint) &&
      [code, name, location].some((value) => value && (value.includes(normalizedHint) || normalizedHint.includes(value)))
    );
  });

  const primary = departments.find(
    (item) => item.id === PRIMARY_DEPARTMENT_ID || item.code === PRIMARY_DEPARTMENT_CODE,
  );
  const candidates = uniqueDepartments([
    ...exactMatches,
    ...fuzzyMatches,
    ...(primary ? [primary] : []),
    ...departments.slice(0, 1),
  ]);

  if (!candidates.length) {
    return PRIMARY_DEPARTMENT_CODE;
  }
  if (candidates.length === 1) {
    return candidates[0].id;
  }

  try {
    const withCounts = await Promise.all(
      candidates.slice(0, 4).map(async (item) => {
        try {
          return { item, count: await fetchWardBedCount(item.id) };
        } catch {
          return { item, count: -1 };
        }
      }),
    );

    withCounts.sort((a, b) => {
      if (b.count !== a.count) {
        return b.count - a.count;
      }
      return departmentPriority(b.item) - departmentPriority(a.item);
    });

    return withCounts[0]?.item.id || candidates[0].id;
  } catch {
    return candidates.sort((a, b) => departmentPriority(b) - departmentPriority(a))[0].id;
  }
}

export const api = {
  async login(username: string, password: string) {
    if (isMockMode) {
      return mockApi.login(username, password);
    }
    const { data } = await httpClient.post("/api/auth/login", { username, password });
    return data;
  },

  async getDepartments(): Promise<DepartmentOption[]> {
    if (isMockMode) {
      return [
        {
          id: PRIMARY_DEPARTMENT_ID,
          code: PRIMARY_DEPARTMENT_CODE,
          name: "心内护理单元A",
          ward_type: "inpatient",
          location: "住院楼6层",
        },
      ];
    }
    const { data } = await httpClient.get("/api/admin/departments");
    return Array.isArray(data) ? data.map(mapDepartment) : [];
  },

  async getAdminAccounts(query = "", statusFilter?: string): Promise<CollabAccount[]> {
    if (isMockMode) {
      if ((mockApi as any).searchCollabAccounts) {
        return (mockApi as any).searchCollabAccounts(query);
      }
      return [];
    }
    const { data } = await httpClient.get("/api/admin/accounts", {
      params: {
        query,
        status_filter: statusFilter || "",
      },
    });
    return Array.isArray(data) ? data.map(mapAccount) : [];
  },

  async bootstrapSession(user: UserInfo): Promise<{ user: UserInfo; departmentId: string }> {
    if (isMockMode) {
      return {
        user: {
          ...user,
          username: user.username || user.account,
          account: user.account || user.username,
        },
        departmentId: PRIMARY_DEPARTMENT_CODE,
      };
    }

    let nextUser: UserInfo = {
      ...user,
      username: user.username || user.account,
      account: user.account || user.username,
    };

    try {
      const query = String(nextUser.username || nextUser.account || nextUser.id || "").trim();
      if (query) {
        const accounts = await api.getAdminAccounts(query);
        const liveAccount =
          accounts.find((item) => item.username === query || item.account === query || item.id === query) || null;
        nextUser = mergeUserInfo(nextUser, liveAccount);
      }
    } catch {
      // keep auth-service payload when account enrichment fails
    }

    try {
      const departments = await api.getDepartments();
      const departmentId = await resolvePreferredDepartmentId(departments, nextUser.department);
      return { user: nextUser, departmentId: departmentId || PRIMARY_DEPARTMENT_CODE };
    } catch {
      return { user: nextUser, departmentId: PRIMARY_DEPARTMENT_CODE };
    }
  },

  async register(payload: {
    username: string;
    password: string;
    full_name: string;
    role_code?: string;
    phone?: string;
  }) {
    if (isMockMode) {
      return mockApi.register(payload);
    }
    const { data } = await httpClient.post("/api/auth/register", payload);
    return data;
  },

  async getWardBeds(departmentId: string) {
    if (isMockMode) {
      return mockApi.getWardBeds();
    }
    const requested = String(departmentId || "").trim() || PRIMARY_DEPARTMENT_CODE;
    const candidateIds = uniqKeepOrder([requested, ...WARD_FALLBACK_IDS]);
    let lastError: unknown = null;

    for (const depId of candidateIds) {
      try {
        const { data } = await httpClient.get(`/api/wards/${depId}/beds`);
        if (Array.isArray(data) && data.length > 0) {
          return data;
        }
      } catch (err) {
        lastError = err;
      }
    }

    if (lastError) {
      throw lastError;
    }
    return [];
  },

  async getPatient(patientId: string): Promise<Patient> {
    if (isMockMode) {
      return mockApi.getPatient(patientId);
    }
    const { data } = await httpClient.get(`/api/patients/${patientId}`);
    return data;
  },

  async getPatientContext(patientId: string): Promise<PatientContext> {
    if (isMockMode) {
      return mockApi.getPatientContext(patientId);
    }
    const { data } = await httpClient.get(`/api/patients/${patientId}/context`);
    return data;
  },

  async getPatientCase(patientId: string): Promise<PatientCaseBundle> {
    if (isMockMode) {
      const [patient, context, beds] = await Promise.all([
        mockApi.getPatient(patientId),
        mockApi.getPatientContext(patientId),
        mockApi.getWardBeds("dep-card-01"),
      ]);
      const bed =
        beds.find((item) => item.current_patient_id === patientId) ||
        beds.find((item) => item.bed_no === context.bed_no) ||
        beds[0] || {
          id: `bed-${context.bed_no || patient.id}`,
          department_id: "dep-card-01",
          bed_no: context.bed_no || "",
          room_no: undefined,
          status: "occupied",
          current_patient_id: patient.id,
          patient_name: context.patient_name || patient.full_name,
          risk_tags: context.risk_tags,
          pending_tasks: context.pending_tasks,
        };
      return {
        created: false,
        patient,
        context,
        bed,
      };
    }
    const { data } = await httpClient.get(`/api/patients/${patientId}/case`);
    return data;
  },

  async upsertPatientCase(payload: PatientCaseUpsertPayload): Promise<PatientCaseBundle> {
    const { data } = await httpClient.post("/api/admin/patient-cases", payload);
    return data;
  },

  async getPatientOrders(patientId: string): Promise<OrderListOut> {
    if (isMockMode) {
      return mockApi.getPatientOrders(patientId);
    }
    const { data } = await httpClient.get(`/api/orders/patients/${patientId}`);
    return mapOrderList(data);
  },

  async getPatientOrderHistory(patientId: string, limit = 80): Promise<ClinicalOrder[]> {
    if (isMockMode) {
      return mockApi.getPatientOrderHistory(patientId, limit);
    }
    const { data } = await httpClient.get(`/api/orders/patients/${patientId}/history`, {
      params: { limit },
    });
    return Array.isArray(data) ? data.map(mapOrder) : [];
  },

  async doubleCheckOrder(orderId: string, checkedBy: string, note?: string): Promise<ClinicalOrder> {
    if (isMockMode) {
      return mockApi.doubleCheckOrder(orderId, checkedBy, note);
    }
    const { data } = await httpClient.post(`/api/orders/${orderId}/double-check`, {
      checked_by: checkedBy,
      note,
    });
    return mapOrder(data);
  },

  async executeOrder(orderId: string, executedBy: string, note?: string): Promise<ClinicalOrder> {
    if (isMockMode) {
      return mockApi.executeOrder(orderId, executedBy, note);
    }
    const { data } = await httpClient.post(`/api/orders/${orderId}/execute`, {
      executed_by: executedBy,
      note,
    });
    return mapOrder(data);
  },

  async reportOrderException(orderId: string, reportedBy: string, reason: string): Promise<ClinicalOrder> {
    if (isMockMode) {
      return mockApi.reportOrderException(orderId, reportedBy, reason);
    }
    const { data } = await httpClient.post(`/api/orders/${orderId}/exception`, {
      reported_by: reportedBy,
      reason,
    });
    return mapOrder(data);
  },

  async createOrderRequest(payload: {
    patientId: string;
    requestedBy: string;
    title: string;
    details: string;
    priority?: string;
  }): Promise<ClinicalOrder> {
    if (isMockMode) {
      if ((mockApi as any).createOrderRequest) {
        return (mockApi as any).createOrderRequest(payload);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.post("/api/orders/request", {
      patient_id: payload.patientId,
      requested_by: payload.requestedBy,
      title: payload.title,
      details: payload.details,
      priority: payload.priority || "P2",
    });
    return mapOrder(data);
  },

  async getAiModels(): Promise<AIModelsCatalog> {
    if (isMockMode) {
      return mockApi.getAiModels();
    }
    try {
      const { data } = await httpClient.get("/api/ai/models");
      return data;
    } catch {
      return mockApi.getAiModels();
    }
  },

  async getAiRuntimeStatus(): Promise<AIRuntimeStatus> {
    if (isMockMode) {
      return (mockApi as any).getAiRuntimeStatus();
    }
    try {
      const { data } = await httpClient.get("/api/ai/runtime");
      return mapAiRuntimeStatus(data);
    } catch {
      return (mockApi as any).getAiRuntimeStatus();
    }
  },

  async setAiRuntimeEngine(engine: "state_machine" | "langgraph"): Promise<AIRuntimeStatus> {
    if (isMockMode) {
      return (mockApi as any).setAiRuntimeEngine(engine);
    }
    try {
      const { data } = await httpClient.post("/api/ai/runtime", { engine });
      return mapAiRuntimeStatus(data);
    } catch {
      return (mockApi as any).setAiRuntimeEngine(engine);
    }
  },

  async clearAiRuntimeEngine(): Promise<AIRuntimeStatus> {
    if (isMockMode) {
      return (mockApi as any).clearAiRuntimeEngine();
    }
    try {
      const { data } = await httpClient.delete("/api/ai/runtime");
      return mapAiRuntimeStatus(data);
    } catch {
      return (mockApi as any).clearAiRuntimeEngine();
    }
  },

  async listAgentQueueTasks(options?: {
    patientId?: string;
    conversationId?: string;
    status?: string;
    limit?: number;
  }): Promise<AgentQueueTask[]> {
    if (isMockMode) {
      return (mockApi as any).listAgentQueueTasks(options);
    }
    const { data } = await httpClient.get("/api/ai/queue/tasks", {
      params: {
        patient_id: options?.patientId,
        conversation_id: options?.conversationId,
        status: options?.status,
        limit: options?.limit || 30,
      },
    });
    const rows = Array.isArray(data) ? data : Array.isArray((data as any)?.value) ? (data as any).value : [];
    return rows.map(mapQueueTask);
  },

  async listAgentRuns(options?: {
    patientId?: string;
    conversationId?: string;
    status?: string;
    workflowType?: string;
    limit?: number;
  }): Promise<AgentRunRecord[]> {
    if (isMockMode) {
      return (mockApi as any).listAgentRuns(options);
    }
    try {
      const { data } = await httpClient.get("/api/ai/runs", {
        params: {
          patient_id: options?.patientId,
          conversation_id: options?.conversationId,
          status: options?.status,
          workflow_type: options?.workflowType,
          limit: options?.limit || 20,
        },
      });
      const rows = Array.isArray(data) ? data : Array.isArray((data as any)?.value) ? (data as any).value : [];
      return rows.map(mapAgentRunRecord);
    } catch (error) {
      throw error;
    }
  },

  async getAgentRun(runId: string): Promise<AgentRunRecord> {
    if (isMockMode) {
      return (mockApi as any).getAgentRun(runId);
    }
    try {
      const { data } = await httpClient.get(`/api/ai/runs/${runId}`);
      return mapAgentRunRecord(data);
    } catch (error) {
      throw error;
    }
  },

  async retryAgentRun(runId: string) {
    if (isMockMode) {
      return (mockApi as any).retryAgentRun(runId);
    }
    try {
      const { data } = await httpClient.post(`/api/ai/runs/${runId}/retry`);
      return mapWorkflowOutput(data);
    } catch (error) {
      throw error;
    }
  },

  async enqueueAgentTask(payload: {
    workflowType: string;
    patientId?: string;
    bedNo?: string;
    conversationId?: string;
    departmentId?: string;
    userInput: string;
    missionTitle?: string;
    successCriteria?: string[];
    operatorNotes?: string;
    attachments?: string[];
    requestedBy?: string;
    agentMode?: string;
    executionProfile?: AIExecutionProfile;
    requestedEngine?: string;
    priority?: number;
  }): Promise<AgentQueueTask> {
    if (isMockMode) {
      return (mockApi as any).enqueueAgentTask(payload);
    }
    try {
      const { data } = await httpClient.post("/api/ai/queue/tasks", {
        requested_engine: payload.requestedEngine,
        priority: payload.priority || 100,
        payload: {
          workflow_type: payload.workflowType,
          patient_id: payload.patientId,
          bed_no: payload.bedNo,
          conversation_id: payload.conversationId,
          department_id: payload.departmentId,
          user_input: payload.userInput,
          mission_title: payload.missionTitle,
          success_criteria: payload.successCriteria || [],
          operator_notes: payload.operatorNotes,
          attachments: payload.attachments || [],
          requested_by: payload.requestedBy,
          agent_mode: payload.agentMode,
          execution_profile: payload.executionProfile,
        },
      });
      return mapQueueTask(data);
    } catch (error) {
      throw error;
    }
  },

  async approveAgentQueueTask(payload: {
    taskId: string;
    approvalIds?: string[];
    decidedBy?: string;
    comment?: string;
  }): Promise<AgentQueueTask> {
    if (isMockMode) {
      return (mockApi as any).approveAgentQueueTask(payload);
    }
    try {
      const { data } = await httpClient.post(`/api/ai/queue/tasks/${payload.taskId}/approve`, {
        approval_ids: payload.approvalIds || [],
        decided_by: payload.decidedBy,
        comment: payload.comment,
      });
      return mapQueueTask(data);
    } catch (error) {
      throw error;
    }
  },

  async rejectAgentQueueTask(payload: {
    taskId: string;
    approvalIds?: string[];
    decidedBy?: string;
    comment?: string;
  }): Promise<AgentQueueTask> {
    if (isMockMode) {
      return (mockApi as any).rejectAgentQueueTask(payload);
    }
    try {
      const { data } = await httpClient.post(`/api/ai/queue/tasks/${payload.taskId}/reject`, {
        approval_ids: payload.approvalIds || [],
        decided_by: payload.decidedBy,
        comment: payload.comment,
      });
      return mapQueueTask(data);
    } catch (error) {
      throw error;
    }
  },

  async runAiChat(payload: {
    mode: AIChatMode;
    selectedModel?: string;
    clusterProfile?: string;
    patientId?: string;
    bedNo?: string;
    conversationId?: string;
    departmentId?: string;
    userInput: string;
    missionTitle?: string;
    successCriteria?: string[];
    operatorNotes?: string;
    attachments?: string[];
    requestedBy?: string;
    agentMode?: string;
    executionProfile?: AIExecutionProfile;
  }): Promise<AIChatResponse> {
    if (isMockMode) {
      return mockApi.runAiChat(payload);
    }
    try {
      const { data } = await httpClient.post("/api/ai/chat", {
        mode: payload.mode,
        selected_model: payload.selectedModel,
        cluster_profile: payload.clusterProfile || "nursing_default_cluster",
        patient_id: payload.patientId,
        bed_no: payload.bedNo,
        conversation_id: payload.conversationId,
        department_id: payload.departmentId,
        user_input: payload.userInput,
        mission_title: payload.missionTitle,
        success_criteria: payload.successCriteria || [],
        operator_notes: payload.operatorNotes,
        attachments: payload.attachments || [],
        requested_by: payload.requestedBy,
        agent_mode: payload.agentMode,
        execution_profile: payload.executionProfile,
      });
      return mapAiChatResponse(data);
    } catch (error) {
      throw error;
    }
  },

  async transcribe(payload: { audioBase64?: string; textHint?: string }) {
    if (isMockMode) {
      return mockApi.transcribe(payload.textHint);
    }
    try {
      const { data } = await httpClient.post(
        `${asrBaseURL}/asr/transcribe`,
        {
          text_hint: payload.textHint,
          audio_base64: payload.audioBase64,
        },
        { timeout: 120000 }
      );
      return data;
    } catch {
      return mockApi.transcribe(payload.textHint);
    }
  },

  async generateHandover(patientId: string): Promise<HandoverResult> {
    if (isMockMode) {
      return mockApi.generateHandover(patientId);
    }
    const { data } = await httpClient.post("/api/handover/generate", {
      patient_id: patientId,
      shift_type: "day",
    });
    return data;
  },

  async getLatestHandover(patientId: string): Promise<HandoverResult> {
    if (isMockMode) {
      return mockApi.generateHandover(patientId);
    }
    const { data } = await httpClient.get(`/api/handover/${patientId}/latest`);
    return data;
  },

  async runRecommendation(
    patientId: string,
    question: string,
    attachments: string[] = [],
    options?: { bedNo?: string; departmentId?: string }
  ): Promise<RecommendationResult> {
    if (isMockMode) {
      return mockApi.runRecommendation(patientId, question);
    }
    const { data } = await httpClient.post("/api/recommendation/run", {
      patient_id: patientId,
      question,
      bed_no: options?.bedNo,
      department_id: options?.departmentId,
      attachments,
    });
    return mapRecommendation(data);
  },

  async getConversationHistory(
    patientId: string,
    limit = 30,
    conversationId?: string
  ): Promise<ConversationHistoryItem[]> {
    if (isMockMode) {
      return mockApi.getConversationHistory(patientId, limit, conversationId);
    }
    const { data } = await httpClient.get("/api/conversation/history", {
      params: { patient_id: patientId, limit, conversation_id: conversationId },
    });
    const rows = Array.isArray(data) ? data : Array.isArray((data as any)?.value) ? (data as any).value : [];
    return mapConversationHistory(rows);
  },

  async getAllHistory(
    patientId: string,
    limit = 80,
    conversationId?: string
  ): Promise<ConversationHistoryItem[]> {
    if (isMockMode) {
      return mockApi.getConversationHistory(patientId, limit, conversationId);
    }
    const { data } = await httpClient.get("/api/history/all", {
      params: { patient_id: patientId, limit, conversation_id: conversationId },
    });
    const rows = Array.isArray(data) ? data : Array.isArray((data as any)?.value) ? (data as any).value : [];
    return mapConversationHistory(rows);
  },

  async analyzeMultimodal(
    patientId: string,
    inputRefs: string[],
    question?: string
  ): Promise<MultimodalAnalysisResult> {
    if (isMockMode) {
      return mockApi.analyzeMultimodal(patientId, inputRefs, question);
    }
    const { data } = await httpClient.post("/api/multimodal/analyze", {
      patient_id: patientId,
      input_refs: inputRefs,
      question,
    });
    return data;
  },

  async createDocumentDraft(
    patientId: string,
    spokenText: string,
    options?: { templateId?: string; templateText?: string; templateName?: string }
  ): Promise<DocumentDraft> {
    if (isMockMode) {
      return mockApi.createDocumentDraft(patientId, spokenText, options);
    }
    const { data } = await httpClient.post("/api/document/draft", {
      patient_id: patientId,
      document_type: "nursing_note",
      spoken_text: spokenText,
      template_id: options?.templateId,
      template_text: options?.templateText,
      template_name: options?.templateName,
    });
    return data;
  },

  async importDocumentTemplate(payload: {
    name?: string;
    templateText?: string;
    templateBase64?: string;
    fileName?: string;
    mimeType?: string;
  }): Promise<DocumentTemplate> {
    if (isMockMode) {
      return mockApi.importDocumentTemplate(payload);
    }
    const { data } = await httpClient.post("/api/document/template/import", {
      name: payload.name,
      template_text: payload.templateText,
      template_base64: payload.templateBase64,
      file_name: payload.fileName,
      mime_type: payload.mimeType,
    });
    return data;
  },

  async listDocumentTemplates(): Promise<DocumentTemplate[]> {
    if (isMockMode) {
      return mockApi.listDocumentTemplates();
    }
    const { data } = await httpClient.get("/api/document/templates");
    return data;
  },

  async listDrafts(patientId: string): Promise<DocumentDraft[]> {
    if (isMockMode) {
      return mockApi.listDrafts(patientId);
    }
    const { data } = await httpClient.get(`/api/document/drafts/${patientId}`);
    return data;
  },

  async listDocumentHistory(patientId: string, limit = 50): Promise<DocumentDraft[]> {
    if (isMockMode) {
      return mockApi.listDrafts(patientId);
    }
    const { data } = await httpClient.get("/api/document/history", {
      params: { patient_id: patientId, limit },
    });
    return data;
  },

  async reviewDraft(draftId: string, reviewedBy: string): Promise<DocumentDraft> {
    if (isMockMode) {
      return mockApi.reviewDraft(draftId);
    }
    const { data } = await httpClient.post(`/api/document/${draftId}/review`, { reviewed_by: reviewedBy });
    return data;
  },

  async submitDraft(draftId: string, submittedBy: string): Promise<DocumentDraft> {
    if (isMockMode) {
      return mockApi.submitDraft(draftId);
    }
    const { data } = await httpClient.post(`/api/document/${draftId}/submit`, { submitted_by: submittedBy });
    return data;
  },

  async updateDraft(draftId: string, draftText: string, editedBy?: string): Promise<DocumentDraft> {
    if (isMockMode) {
      if ((mockApi as any).updateDraft) {
        return (mockApi as any).updateDraft(draftId, draftText, editedBy);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.post(`/api/document/${draftId}/edit`, {
      draft_text: draftText,
      edited_by: editedBy,
    });
    return data;
  },

  async editDraft(draftId: string, draftText: string, editedBy?: string): Promise<DocumentDraft> {
    if (isMockMode) {
      if ((mockApi as any).editDraft) {
        return (mockApi as any).editDraft(draftId, draftText, editedBy);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.post(`/api/document/${draftId}/edit`, {
      draft_text: draftText,
      edited_by: editedBy,
    });
    return data;
  },

  async createThread(patientId: string, title: string, createdBy: string) {
    if (isMockMode) {
      return mockApi.createThread(patientId, title, createdBy);
    }
    const { data } = await httpClient.post("/api/collab/thread", {
      patient_id: patientId,
      title,
      thread_type: "discussion",
      created_by: createdBy,
    });
    return data;
  },

  async sendMessage(threadId: string, content: string, senderId: string) {
    if (isMockMode) {
      return mockApi.sendMessage(threadId, content, senderId);
    }
    const { data } = await httpClient.post("/api/collab/message", {
      thread_id: threadId,
      content,
      sender_id: senderId,
    });
    return data;
  },

  async getThread(threadId: string): Promise<CollaborationThreadDetail> {
    if (isMockMode) {
      return mockApi.getThread(threadId);
    }
    const { data } = await httpClient.get(`/api/collab/thread/${threadId}`);
    return data;
  },

  async getCollabHistory(patientId: string, limit = 50): Promise<CollaborationThreadHistoryItem[]> {
    if (isMockMode) {
      return mockApi.getCollabHistory(patientId, limit);
    }
    const { data } = await httpClient.get("/api/collab/history", {
      params: { patient_id: patientId, limit },
    });
    return mapThreadHistory(data);
  },

  async searchCollabAccounts(query: string, excludeUserId?: string): Promise<CollabAccount[]> {
    if (isMockMode) {
      if ((mockApi as any).searchCollabAccounts) {
        return (mockApi as any).searchCollabAccounts(query, excludeUserId);
      }
      return [];
    }
    const { data } = await httpClient.get("/api/collab/accounts", {
      params: { query, exclude_user_id: excludeUserId },
    });
    return Array.isArray(data) ? data.map(mapAccount) : [];
  },

  async getCollabContacts(userId: string): Promise<CollabContactList> {
    if (isMockMode) {
      if ((mockApi as any).getCollabContacts) {
        return (mockApi as any).getCollabContacts(userId);
      }
      return { user_id: userId, contacts: [] };
    }
    const { data } = await httpClient.get(`/api/collab/contacts/${userId}`);
    return {
      user_id: String(data?.user_id || userId),
      contacts: Array.isArray(data?.contacts) ? data.contacts.map(mapAccount) : [],
    };
  },

  async addCollabContact(userId: string, account: string): Promise<CollabAccount> {
    if (isMockMode) {
      if ((mockApi as any).addCollabContact) {
        return (mockApi as any).addCollabContact(userId, account);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.post("/api/collab/contacts/add", {
      user_id: userId,
      account,
    });
    return mapAccount(data);
  },

  async listDirectSessions(userId: string, limit = 100): Promise<DirectSession[]> {
    if (isMockMode) {
      if ((mockApi as any).listDirectSessions) {
        return (mockApi as any).listDirectSessions(userId, limit);
      }
      return [];
    }
    const { data } = await httpClient.get(`/api/collab/direct/sessions/${userId}`, {
      params: { limit },
    });
    return Array.isArray(data) ? data.map(mapDirectSession) : [];
  },

  async openDirectSession(payload: {
    userId: string;
    contactUserId: string;
    patientId?: string;
  }): Promise<DirectSession> {
    if (isMockMode) {
      if ((mockApi as any).openDirectSession) {
        return (mockApi as any).openDirectSession(payload);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.post("/api/collab/direct/open", {
      user_id: payload.userId,
      contact_user_id: payload.contactUserId,
      patient_id: payload.patientId,
    });
    return mapDirectSession(data);
  },

  async sendDirectMessage(payload: {
    sessionId: string;
    senderId: string;
    content: string;
    messageType?: string;
    attachmentRefs?: string[];
  }): Promise<void> {
    if (isMockMode) {
      if ((mockApi as any).sendDirectMessage) {
        await (mockApi as any).sendDirectMessage(payload);
      }
      return;
    }
    await httpClient.post("/api/collab/direct/message", {
      session_id: payload.sessionId,
      sender_id: payload.senderId,
      content: payload.content,
      message_type: payload.messageType || "text",
      attachment_refs: payload.attachmentRefs || [],
    });
  },

  async getDirectSessionDetail(sessionId: string, userId: string): Promise<DirectSessionDetail> {
    if (isMockMode) {
      if ((mockApi as any).getDirectSessionDetail) {
        return (mockApi as any).getDirectSessionDetail(sessionId, userId);
      }
      throw new Error("mock_not_implemented");
    }
    const { data } = await httpClient.get(`/api/collab/direct/session/${sessionId}`, {
      params: { user_id: userId },
    });
    return {
      session: mapDirectSession(data?.session),
      messages: Array.isArray(data?.messages)
        ? data.messages.map((item: any) => ({
            id: String(item?.id || ""),
            thread_id: String(item?.thread_id || ""),
            sender_id: item?.sender_id ? String(item.sender_id) : undefined,
            message_type: String(item?.message_type || "text"),
            content: String(item?.content || ""),
            attachment_refs: Array.isArray(item?.attachment_refs)
              ? item.attachment_refs.map((x: any) => String(x))
              : [],
            ai_generated: Boolean(item?.ai_generated),
            created_at: String(item?.created_at || ""),
          }))
        : [],
    };
  },

  async runAssistantDigest(payload: {
    userId: string;
    patientId: string;
    note?: string;
  }): Promise<AssistantDigest> {
    if (isMockMode) {
      if ((mockApi as any).runAssistantDigest) {
        return (mockApi as any).runAssistantDigest(payload);
      }
      return {
        summary: "未启用真实服务，暂无整理结果。",
        tasks: [],
        suggestions: [],
        generated_message: "",
      };
    }
    const { data } = await httpClient.post("/api/collab/assistant/digest", {
      user_id: payload.userId,
      patient_id: payload.patientId,
      note: payload.note,
    });
    return {
      summary: String(data?.summary || ""),
      tasks: Array.isArray(data?.tasks) ? data.tasks.map((x: any) => String(x)) : [],
      suggestions: Array.isArray(data?.suggestions) ? data.suggestions.map((x: any) => String(x)) : [],
      generated_message: String(data?.generated_message || ""),
    };
  },

  async runVoiceWorkflow(userInput: string, patientId?: string) {
    if (isMockMode) {
      return mockApi.runVoiceWorkflow(userInput);
    }
    const body: any = {
      workflow_type: "voice_inquiry",
      user_input: userInput,
    };
    if (patientId) {
      body.patient_id = patientId;
    }
    const { data } = await httpClient.post("/api/workflow/run", body);
    return data;
  },

  async ttsSpeak(text: string) {
    if (isMockMode) {
      return { audio_base64: "TU9DS19BVURJT19EQVRB", provider: "mock" };
    }
    const { data } = await httpClient.post("/api/tts/speak", { text, voice: "default" });
    return data;
  },
};
