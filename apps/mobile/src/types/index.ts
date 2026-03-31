export type UserInfo = {
  id: string;
  username?: string;
  full_name: string;
  role_code: string;
  account?: string;
  phone?: string | null;
  email?: string | null;
  department?: string | null;
  title?: string | null;
  status?: string;
};

export type DepartmentOption = {
  id: string;
  code?: string;
  name: string;
  ward_type?: string;
  location?: string;
};

export type BedOverview = {
  id: string;
  department_id: string;
  bed_no: string;
  room_no?: string;
  status: string;
  current_patient_id?: string;
  patient_name?: string;
  risk_tags: string[];
  pending_tasks: string[];
  latest_document_sync?: string;
};

export type Patient = {
  id: string;
  mrn: string;
  inpatient_no?: string;
  full_name: string;
  gender?: string;
  age?: number;
  blood_type?: string;
  allergy_info?: string;
  current_status: string;
};

export type PatientContext = {
  patient_id: string;
  patient_name?: string;
  bed_no?: string;
  encounter_id?: string;
  diagnoses: string[];
  risk_tags: string[];
  pending_tasks: string[];
  latest_observations: Array<{ name: string; value: string; abnormal_flag?: string }>;
  latest_document_sync?: string;
  latest_document_status?: string;
  latest_document_type?: string;
  latest_document_excerpt?: string;
  latest_document_updated_at?: string;
  updated_at?: string;
};

export type CaseObservationInput = {
  name: string;
  value: string;
  abnormal_flag?: string;
};

export type PatientCaseUpsertPayload = {
  patient_id?: string;
  bed_no: string;
  room_no?: string;
  full_name: string;
  mrn?: string;
  inpatient_no?: string;
  gender?: string;
  age?: number;
  blood_type?: string;
  allergy_info?: string;
  current_status?: string;
  encounter_id?: string;
  diagnoses: string[];
  risk_tags: string[];
  pending_tasks: string[];
  latest_observations: CaseObservationInput[];
};

export type PatientCaseBundle = {
  created: boolean;
  patient: Patient;
  context: PatientContext;
  bed: BedOverview;
};

export type OrderExecutionTrail = {
  action: string;
  actor: string;
  note?: string | null;
  created_at: string;
};

export type ClinicalOrder = {
  id: string;
  patient_id: string;
  encounter_id?: string | null;
  order_no: string;
  order_type: string;
  title: string;
  instruction: string;
  route?: string | null;
  dosage?: string | null;
  frequency?: string | null;
  priority: string;
  status: string;
  ordered_by?: string | null;
  ordered_at?: string | null;
  due_at?: string | null;
  requires_double_check: boolean;
  check_by?: string | null;
  check_at?: string | null;
  executed_by?: string | null;
  executed_at?: string | null;
  execution_note?: string | null;
  exception_reason?: string | null;
  risk_hints: string[];
  audit_trail: OrderExecutionTrail[];
};

export type OrderStats = {
  pending: number;
  due_30m: number;
  overdue: number;
  high_alert: number;
};

export type OrderListOut = {
  patient_id: string;
  stats: OrderStats;
  orders: ClinicalOrder[];
};

export type RecommendationResult = {
  id: string;
  patient_id: string;
  summary: string;
  findings: string[];
  recommendations: Array<{ title: string; priority: number; rationale?: string }>;
  confidence: number;
  review_required: boolean;
  metadata?: {
    original_question?: string;
    effective_question?: string;
    agent_trace?: Array<{ agent: string; status: string; note?: string }>;
    [key: string]: unknown;
  };
};

export type HandoverResult = {
  id: string;
  patient_id: string;
  shift_date: string;
  shift_type: string;
  summary: string;
  next_shift_priorities: string[];
};

export type DocumentDraft = {
  id: string;
  patient_id: string;
  document_type: string;
  draft_text: string;
  status: string;
  structured_fields?: Record<string, unknown>;
  updated_at: string;
};

export type DocumentTemplate = {
  id: string;
  name: string;
  source_type: string;
  template_text: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
};

export type MultimodalAnalysisResult = {
  patient_id: string;
  summary: string;
  findings: string[];
  recommendations: Array<{ title: string; priority: number }>;
  confidence: number;
  review_required: boolean;
  created_at: string;
};

export type ConversationHistoryItem = {
  id: string;
  source: string;
  workflow_type: string;
  patient_id?: string;
  conversation_id?: string;
  user_input?: string;
  summary: string;
  created_at: string;
  confidence?: number;
  review_required?: boolean;
  run_id?: string;
  runtime_engine?: string;
  findings?: string[];
  recommendations?: Array<{ title: string; priority: number; rationale?: string }>;
  steps?: AgentStep[];
  agent_goal?: string;
  agent_mode?: string;
  execution_profile?: string;
  mission_title?: string;
  success_criteria?: string[];
  plan?: AgentPlanItem[];
  memory?: AgentMemorySnapshot;
  artifacts?: AgentArtifact[];
  specialist_profiles?: RoleLane[];
  hybrid_care_path?: ServiceRelayStage[];
  data_capsule?: PatientStateCapsule;
  health_graph?: CareGraphSnapshot;
  reasoning_cards?: ReasoningCheckpoint[];
  pending_approvals?: AgentApprovalRequest[];
  next_actions?: string[];
};

export type CollaborationThread = {
  id: string;
  patient_id?: string;
  encounter_id?: string;
  thread_type: string;
  title: string;
  created_by?: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type CollaborationMessage = {
  id: string;
  thread_id: string;
  sender_id?: string;
  message_type: string;
  content: string;
  attachment_refs: string[];
  ai_generated: boolean;
  created_at: string;
};

export type CollaborationThreadDetail = {
  thread: CollaborationThread;
  messages: CollaborationMessage[];
  metadata?: Record<string, unknown>;
};

export type CollaborationThreadHistoryItem = {
  thread: CollaborationThread;
  latest_message?: CollaborationMessage | null;
  message_count: number;
};

export type CollabAccount = {
  id: string;
  username?: string;
  account: string;
  full_name: string;
  role_code: string;
  phone?: string | null;
  email?: string | null;
  department?: string | null;
  title?: string | null;
  status?: string;
};

export type CollabContactList = {
  user_id: string;
  contacts: CollabAccount[];
};

export type DirectSession = {
  id: string;
  user_id: string;
  contact_user_id: string;
  patient_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  latest_message?: CollaborationMessage | null;
  unread_count: number;
  contact?: CollabAccount | null;
};

export type DirectSessionDetail = {
  session: DirectSession;
  messages: CollaborationMessage[];
};

export type AssistantDigest = {
  summary: string;
  tasks: string[];
  suggestions: string[];
  generated_message: string;
};

export type GenerateProgressStep = {
  key: string;
  label: string;
  done: boolean;
  active: boolean;
};

export type AgentStep = {
  agent: string;
  status: string;
  note?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
};

export type AgentPlanItem = {
  id: string;
  title: string;
  tool?: string;
  reason?: string;
  status: string;
  auto_runnable?: boolean;
};

export type AgentArtifact = {
  kind: string;
  title: string;
  status: string;
  reference_id?: string;
  summary?: string;
  metadata?: Record<string, unknown>;
};

export type AgentToolExecution = {
  item_id: string;
  title: string;
  tool?: string;
  agent: string;
  status: string;
  attempts: number;
  retryable: boolean;
  started_at: string;
  finished_at: string;
  output?: Record<string, unknown>;
  error?: string;
};

export type AgentApprovalRequest = {
  id: string;
  item_id: string;
  tool_id?: string;
  title: string;
  reason?: string;
  status: string;
  created_at: string;
  decided_at?: string;
  decided_by?: string;
  comment?: string;
  metadata?: Record<string, unknown>;
};

export type AgentMemorySnapshot = {
  conversation_summary: string;
  patient_facts: string[];
  unresolved_tasks: string[];
  last_actions: string[];
  user_preferences: string[];
};

export type RoleLane = {
  id: string;
  title: string;
  role: string;
  focus: string;
  status: string;
  reason?: string;
  next_action?: string;
};

export type ServiceRelayStage = {
  id: string;
  title: string;
  status: string;
  owner: string;
  summary?: string;
};

export type PatientStateCapsule = {
  patient_id?: string;
  version?: string;
  event_summary: string[];
  time_axis: string[];
  data_layers: string[];
  risk_factors: string[];
};

export type CareGraphSnapshot = {
  nodes: string[];
  edges: string[];
  dynamic_updates: string[];
};

export type ReasoningCheckpoint = {
  mode: string;
  title: string;
  summary: string;
  confidence?: number;
};

export type AIChatMode = "single_model" | "agent_cluster";
export type AIExecutionProfile = "observe" | "escalate" | "document" | "full_loop";

export type AIModelTask = {
  model_id: string;
  model_name: string;
  role: string;
  task: string;
  enabled: boolean;
};

export type AIModelOption = {
  id: string;
  name: string;
  provider: string;
  description: string;
};

export type AIClusterProfile = {
  id: string;
  name: string;
  main_model: string;
  description: string;
  tasks: AIModelTask[];
};

export type AIModelsCatalog = {
  single_models: AIModelOption[];
  cluster_profiles: AIClusterProfile[];
};

export type LocalModelAliases = {
  primary?: string;
  fallback?: string;
  planner?: string;
  reasoning?: string;
  custom?: string;
  multimodal?: string;
};

export type TaskQueueStatus = {
  worker_enabled: boolean;
  worker_running: boolean;
  recovered_tasks: number;
  queued: number;
  running: number;
  waiting_approval: number;
  completed: number;
  failed: number;
  cancelled: number;
  total: number;
};

export type AIRuntimeStatus = {
  configured_engine: string;
  active_engine: string;
  langgraph_available: boolean;
  override_enabled: boolean;
  fallback_reason: string;
  planner_llm_enabled: boolean;
  planner_timeout_sec: number;
  planner_max_steps: number;
  local_model_service_reachable: boolean;
  available_local_models: string[];
  local_model_aliases?: LocalModelAliases;
  approval_required_tools?: string[];
  task_queue?: TaskQueueStatus;
};

export type AgentWorkflowOutput = {
  workflow_type: string;
  summary: string;
  findings: string[];
  recommendations: Array<{ title: string; priority: number; rationale?: string }>;
  confidence: number;
  review_required: boolean;
  patient_id?: string;
  patient_name?: string;
  bed_no?: string;
  steps: AgentStep[];
  run_id?: string;
  runtime_engine?: string;
  agent_goal?: string;
  agent_mode: string;
  execution_profile?: string;
  mission_title?: string;
  success_criteria?: string[];
  plan: AgentPlanItem[];
  memory?: AgentMemorySnapshot;
  artifacts: AgentArtifact[];
  specialist_profiles: RoleLane[];
  hybrid_care_path: ServiceRelayStage[];
  data_capsule?: PatientStateCapsule;
  health_graph?: CareGraphSnapshot;
  reasoning_cards: ReasoningCheckpoint[];
  tool_executions?: AgentToolExecution[];
  pending_approvals: AgentApprovalRequest[];
  next_actions: string[];
  created_at: string;
};

export type AgentRunRequestSnapshot = {
  workflow_type: string;
  patient_id?: string;
  conversation_id?: string;
  department_id?: string;
  bed_no?: string;
  user_input?: string;
  mission_title?: string;
  success_criteria: string[];
  operator_notes?: string;
  requested_by?: string;
  agent_mode?: string;
  execution_profile?: string;
  attachments_count: number;
  approved_actions: string[];
  rejected_actions: string[];
};

export type AgentRunRecord = {
  id: string;
  status: string;
  workflow_type: string;
  runtime_engine: string;
  request: AgentRunRequestSnapshot;
  patient_id?: string;
  patient_name?: string;
  bed_no?: string;
  conversation_id?: string;
  agent_goal?: string;
  agent_mode: string;
  summary?: string;
  plan: AgentPlanItem[];
  memory?: AgentMemorySnapshot;
  artifacts: AgentArtifact[];
  specialist_profiles: RoleLane[];
  hybrid_care_path: ServiceRelayStage[];
  data_capsule?: PatientStateCapsule;
  health_graph?: CareGraphSnapshot;
  reasoning_cards: ReasoningCheckpoint[];
  next_actions: string[];
  steps: AgentStep[];
  tool_executions: AgentToolExecution[];
  pending_approvals: AgentApprovalRequest[];
  retry_available: boolean;
  error?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
};

export type WorkflowRequestPayload = {
  workflow_type: string;
  patient_id?: string;
  conversation_id?: string;
  department_id?: string;
  bed_no?: string;
  user_input?: string;
  mission_title?: string;
  success_criteria?: string[];
  operator_notes?: string;
  attachments: string[];
  requested_by?: string;
  agent_mode?: string;
  execution_profile?: string;
  approved_actions: string[];
  rejected_actions: string[];
};

export type AgentQueueTask = {
  id: string;
  status: string;
  payload: WorkflowRequestPayload;
  workflow_type: string;
  requested_engine?: string;
  runtime_engine?: string;
  priority: number;
  run_id?: string;
  summary?: string;
  approvals: AgentApprovalRequest[];
  last_output?: AgentWorkflowOutput;
  error?: string;
  attempt_count: number;
  resume_count: number;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
};

export type AIChatResponse = {
  mode: AIChatMode;
  selected_model?: string;
  cluster_profile?: string;
  conversation_id?: string;
  run_id?: string;
  runtime_engine?: string;
  workflow_type: string;
  summary: string;
  findings: string[];
  recommendations: Array<{ title: string; priority: number; rationale?: string }>;
  confidence: number;
  review_required: boolean;
  steps: AgentStep[];
  model_plan: AIModelTask[];
  agent_goal?: string;
  agent_mode: string;
  execution_profile?: string;
  mission_title?: string;
  success_criteria?: string[];
  plan: AgentPlanItem[];
  memory?: AgentMemorySnapshot;
  artifacts: AgentArtifact[];
  specialist_profiles: RoleLane[];
  hybrid_care_path: ServiceRelayStage[];
  data_capsule?: PatientStateCapsule;
  health_graph?: CareGraphSnapshot;
  reasoning_cards: ReasoningCheckpoint[];
  pending_approvals: AgentApprovalRequest[];
  next_actions: string[];
  created_at: string;
};

export type AIChatMessage = {
  id: string;
  role: "user" | "assistant";
  mode: AIChatMode;
  text: string;
  timestamp: string;
  response?: AIChatResponse;
};
