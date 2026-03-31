import type {
  AIChatResponse,
  AIModelsCatalog,
  AIRuntimeStatus,
  AgentQueueTask,
  BedOverview,
  ClinicalOrder,
  ConversationHistoryItem,
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
import type { CollaborationThreadHistoryItem } from "../types";
import type { AIExecutionProfile, AgentRunRecord } from "../types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const EXECUTION_PROFILE_LABELS: Record<AIExecutionProfile, string> = {
  observe: "观察面板",
  escalate: "升级协作",
  document: "文书沉淀",
  full_loop: "自治闭环",
};

function normalizeExecutionProfile(executionProfile?: string | null): AIExecutionProfile {
  const profile = String(executionProfile || "").trim().toLowerCase();
  if (profile === "escalate" || profile === "document" || profile === "full_loop") {
    return profile;
  }
  return "observe";
}

function buildMissionAwareText(
  userInput?: string,
  missionTitle?: string,
  successCriteria?: string[],
  operatorNotes?: string
) {
  const parts = [String(userInput || "").trim()];
  if (missionTitle) {
    parts.push(`任务标题：${missionTitle}`);
  }
  const criteria = Array.isArray(successCriteria) ? successCriteria.filter((item) => String(item || "").trim()) : [];
  if (criteria.length) {
    parts.push(`成功标准：${criteria.join("；")}`);
  }
  if (operatorNotes) {
    parts.push(`操作备注：${operatorNotes}`);
  }
  return parts.filter(Boolean).join("\n").trim();
}

function withMissionSummary(summary: string, missionTitle?: string) {
  if (!missionTitle) {
    return summary;
  }
  return summary.includes(missionTitle) ? summary : `任务「${missionTitle}」：${summary}`;
}

const mockUsers: Record<string, UserInfo & { password: string }> = {
  nurse01: {
    id: "u_nurse_01",
    full_name: "张护士",
    role_code: "nurse",
    password: "123456",
  },
  doctor01: {
    id: "u_doctor_01",
    full_name: "李医生",
    role_code: "attending_doctor",
    password: "123456",
  },
};

const mockBeds: BedOverview[] = [
  {
    id: "bed-12",
    department_id: "dep-card-01",
    bed_no: "12",
    room_no: "612",
    status: "occupied",
    current_patient_id: "pat-001",
    patient_name: "张晓明",
    risk_tags: ["低血压风险", "液体管理风险"],
    pending_tasks: ["复测血压", "记录尿量"],
  },
  {
    id: "bed-15",
    department_id: "dep-card-01",
    bed_no: "15",
    room_no: "615",
    status: "occupied",
    current_patient_id: "pat-002",
    patient_name: "王丽",
    risk_tags: ["呼吸波动风险"],
    pending_tasks: ["监测血氧"],
  },
];

const mockPatients: Record<string, Patient> = {
  "pat-001": {
    id: "pat-001",
    mrn: "MRN-0001",
    inpatient_no: "IP-2026-0001",
    full_name: "张晓明",
    gender: "男",
    age: 45,
    blood_type: "A+",
    allergy_info: "青霉素过敏",
    current_status: "admitted",
  },
  "pat-002": {
    id: "pat-002",
    mrn: "MRN-0002",
    inpatient_no: "IP-2026-0002",
    full_name: "王丽",
    gender: "女",
    age: 48,
    blood_type: "B+",
    current_status: "admitted",
  },
};

const mockContexts: Record<string, PatientContext> = {
  "pat-001": {
    patient_id: "pat-001",
    bed_no: "12",
    encounter_id: "enc-001",
    diagnoses: ["慢性心衰急性加重"],
    risk_tags: ["低血压风险", "液体管理风险"],
    pending_tasks: ["复测血压", "记录尿量"],
    latest_observations: [
      { name: "收缩压", value: "88 mmHg", abnormal_flag: "low" },
      { name: "4小时尿量", value: "85 ml", abnormal_flag: "low" },
    ],
  },
  "pat-002": {
    patient_id: "pat-002",
    bed_no: "15",
    encounter_id: "enc-002",
    diagnoses: ["肺部感染恢复期"],
    risk_tags: ["呼吸波动风险"],
    pending_tasks: ["监测血氧"],
    latest_observations: [{ name: "SpO2", value: "93%", abnormal_flag: "low" }],
  },
};

function updateDocumentSync(patientId: string, status: string, updatedAt: string, excerpt: string) {
  const statusMap: Record<string, string> = {
    draft: "草稿",
    reviewed: "已审核",
    submitted: "已提交",
  };
  const label = statusMap[status] || status;
  const sync = `文书状态：${label}`;
  const ctx = mockContexts[patientId];
  if (ctx) {
    ctx.latest_document_sync = sync;
    ctx.latest_document_status = status;
    ctx.latest_document_type = "nursing_note";
    ctx.latest_document_updated_at = updatedAt;
    ctx.latest_document_excerpt = excerpt;
    if (!ctx.pending_tasks.includes(sync)) {
      ctx.pending_tasks = [...ctx.pending_tasks, sync];
    }
  }
  const bed = mockBeds.find((item) => item.current_patient_id === patientId);
  if (bed) {
    bed.latest_document_sync = sync;
    if (!bed.pending_tasks.includes(sync)) {
      bed.pending_tasks = [...bed.pending_tasks, sync];
    }
  }
}

const mockDrafts: DocumentDraft[] = [];
const mockTemplates: DocumentTemplate[] = [
  {
    id: "tpl-default-nursing-note",
    name: "默认护理记录模板",
    source_type: "system",
    template_text:
      "【护理记录】\n患者ID：{{patient_id}} 床号：{{bed_no}}\n主要诊断：{{diagnoses}}\n当前风险：{{risk_tags}}\n待处理事项：{{pending_tasks}}\n记录内容：{{spoken_text}}\n护士评估：\n处理措施：\n复评与计划：",
    created_by: "system",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

let mockThread: any = null;
const mockMessages: any[] = [];
const mockConversationHistory: ConversationHistoryItem[] = [];
const mockAccounts = [
  { id: "u_nurse_01", account: "nurse01", full_name: "张护士", role_code: "nurse", department: "心内科病区", title: "责任护士" },
  { id: "u_doctor_01", account: "doctor01", full_name: "李医生", role_code: "attending_doctor", department: "心内科", title: "主治医师" },
  { id: "u_resident_01", account: "resident01", full_name: "王住院", role_code: "resident_doctor", department: "心内科", title: "住院医师" },
  { id: "u_charge_01", account: "charge01", full_name: "赵护士长", role_code: "charge_nurse", department: "心内科病区", title: "护士长" },
];
const mockContacts: Record<string, string[]> = {
  u_nurse_01: ["u_doctor_01", "u_resident_01", "u_charge_01"],
};
const mockDirectSessions: any[] = [];
const mockDirectMessages: any[] = [];
const mockQueueTasks: AgentQueueTask[] = [];
const mockLocalModelAliases = {
  primary: "minicpm3-4b",
  fallback: "qwen2.5-3b",
  planner: "qwen3-8b",
  reasoning: "deepseek-r1-distill-qwen-7b",
  custom: "custom-openai-local",
  multimodal: "medgemma-4b",
};
const mockAvailableLocalModels = [
  "minicpm3-4b",
];
let mockRuntimeOverride: "" | "state_machine" | "langgraph" = "";
const mockLangGraphAvailable = true;

const nowIso = () => new Date().toISOString();
const minutesFromNow = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();

function buildQueueStats() {
  const counts = {
    queued: 0,
    running: 0,
    waiting_approval: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
  };
  mockQueueTasks.forEach((item) => {
    const key = item.status as keyof typeof counts;
    if (counts[key] !== undefined) {
      counts[key] += 1;
    }
  });
  return {
    worker_enabled: true,
    worker_running: true,
    recovered_tasks: 0,
    ...counts,
    total: mockQueueTasks.length,
  };
}

function queueNeedsApproval(text: string, executionProfile?: string) {
  const profile = normalizeExecutionProfile(executionProfile);
  if (profile === "escalate" || profile === "document" || profile === "full_loop") {
    return true;
  }
  return /通知|上报|联系医生|值班医生|交班|文书|护理记录|记录单|医嘱|补开|申请|notify|doctor|handover|document|order/i.test(text);
}

function buildRuntimeStatus(): AIRuntimeStatus {
  const configured = mockRuntimeOverride || "state_machine";
  const active = configured === "langgraph" && mockLangGraphAvailable ? "langgraph" : "state_machine";
  return {
    configured_engine: configured,
    active_engine: active,
    langgraph_available: mockLangGraphAvailable,
    override_enabled: Boolean(mockRuntimeOverride),
    fallback_reason: configured === "langgraph" && !mockLangGraphAvailable ? "langgraph_unavailable_fallback" : "",
    planner_llm_enabled: mockAvailableLocalModels.includes(mockLocalModelAliases.planner),
    planner_timeout_sec: 25,
    planner_max_steps: 6,
    local_model_service_reachable: true,
    available_local_models: [...mockAvailableLocalModels],
    local_model_aliases: { ...mockLocalModelAliases },
    approval_required_tools: ["send_collaboration", "create_handover", "create_document", "request_order"],
    task_queue: buildQueueStats(),
  };
}

const mockOrdersByPatient: Record<string, ClinicalOrder[]> = {
  "pat-001": [
    {
      id: "ord-pat-001-01",
      patient_id: "pat-001",
      encounter_id: "enc-001",
      order_no: "YZZL-2201",
      order_type: "medication",
      title: "去甲肾上腺素微量泵入",
      instruction: "维持MAP>65 mmHg，按血压滴定速度并记录泵速变化。",
      route: "静脉泵入",
      dosage: "4mg/50ml",
      frequency: "持续",
      priority: "P1",
      status: "pending",
      ordered_by: "dr_wang",
      ordered_at: minutesFromNow(-110),
      due_at: minutesFromNow(15),
      requires_double_check: true,
      risk_hints: ["血管活性药", "需双人核对", "警惕外渗"],
      audit_trail: [{ action: "created", actor: "dr_wang", note: "医嘱下达", created_at: minutesFromNow(-110) }],
    },
    {
      id: "ord-pat-001-02",
      patient_id: "pat-001",
      encounter_id: "enc-001",
      order_no: "YZZL-2202",
      order_type: "lab",
      title: "复查电解质 + 血气分析",
      instruction: "采血后30分钟内送检，重点关注K+、乳酸和碱剩余。",
      route: "静脉采血",
      dosage: undefined,
      frequency: "q6h",
      priority: "P1",
      status: "checked",
      ordered_by: "dr_wang",
      ordered_at: minutesFromNow(-90),
      due_at: minutesFromNow(40),
      requires_double_check: false,
      check_by: "u_nurse_01",
      check_at: minutesFromNow(-30),
      risk_hints: ["检验时效要求高"],
      audit_trail: [
        { action: "created", actor: "dr_wang", note: "医嘱下达", created_at: minutesFromNow(-90) },
        { action: "double_checked", actor: "u_nurse_01", note: "采血准备完成", created_at: minutesFromNow(-30) },
      ],
    },
  ],
};

const mockOrderHistoryByPatient: Record<string, ClinicalOrder[]> = {
  "pat-001": [],
};

function getOrderStats(orders: ClinicalOrder[]) {
  const now = Date.now();
  let pending = 0;
  let due_30m = 0;
  let overdue = 0;
  let high_alert = 0;

  orders.forEach((item) => {
    if (item.status === "pending" || item.status === "checked") {
      pending += 1;
    }
    if (item.priority === "P1" || item.requires_double_check) {
      high_alert += 1;
    }
    if (item.due_at) {
      const due = new Date(item.due_at).getTime();
      if (due < now) {
        overdue += 1;
      } else if (due - now <= 30 * 60_000) {
        due_30m += 1;
      }
    }
  });

  return { pending, due_30m, overdue, high_alert };
}

function cloneOrder<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function pushConversationHistory(item: ConversationHistoryItem) {
  mockConversationHistory.unshift(item);
  if (mockConversationHistory.length > 200) {
    mockConversationHistory.splice(200);
  }
}

function dynamicSummary(question: string, executionProfile?: string) {
  const q = question || "";
  const profile = normalizeExecutionProfile(executionProfile);
  const base =
    q.includes("尿") || q.includes("少尿") || q.includes("排尿")
      ? {
          summary: "当前重点是少尿与低灌注风险，建议先排查导尿通畅并同步复测血压。",
          findings: ["4小时尿量偏低", "收缩压偏低", "液体管理风险"],
          recommendations: [
            { title: "P1 每小时记录尿量并检查导尿通畅", priority: 1 },
            { title: "P1 复测血压并评估循环灌注", priority: 1 },
            { title: "P2 通知医生评估补液/升压策略", priority: 2 },
          ],
        }
      : q.includes("发热") || q.includes("体温") || q.includes("感染")
      ? {
          summary: "当前重点是感染风险评估，建议完善体温趋势和感染指标。",
          findings: ["存在感染恢复期", "需复核体温趋势"],
          recommendations: [
            { title: "P1 复测体温并完善感染评估", priority: 1 },
            { title: "P1 按医嘱采样送检", priority: 1 },
            { title: "P2 出现循环恶化时立即上报", priority: 2 },
          ],
        }
      : {
          summary: `已收到问题：${question}。当前优先关注低灌注风险并执行人工复核。`,
          findings: ["收缩压偏低", "尿量减少", "问题已成功传输到推荐服务"],
          recommendations: [
            { title: "P1 立即复测血压并复核趋势", priority: 1 },
            { title: "P1 记录尿量并评估液体管理", priority: 1 },
            { title: "P2 触发医生复核并准备升级评估", priority: 2 },
          ],
        };

  if (profile === "escalate") {
    return {
      summary: `${base.summary} 当前执行姿态偏向升级协作，重点准备上报摘要与医生沟通依据。`,
      findings: [...base.findings, "已切换到升级协作执行姿态"],
      recommendations: [
        { title: "P1 汇总异常体征并生成上报摘要", priority: 1 },
        { title: "P1 通知值班医生并同步关键观察结果", priority: 1 },
        ...base.recommendations.slice(0, 2),
      ],
    };
  }

  if (profile === "document") {
    return {
      summary: `${base.summary} 当前执行姿态偏向文书沉淀，会优先输出护理记录与交班要点。`,
      findings: [...base.findings, "已切换到文书沉淀执行姿态"],
      recommendations: [
        { title: "P1 生成护理记录草稿并标注待复核项", priority: 1 },
        { title: "P1 生成交班摘要并列出下一班重点", priority: 1 },
        ...base.recommendations.slice(0, 2),
      ],
    };
  }

  if (profile === "full_loop") {
    return {
      summary: `${base.summary} 当前执行姿态为自治闭环，会持续推进观察、协作和留痕，敏感动作进入审批闸门。`,
      findings: [...base.findings, "已切换到自治闭环执行姿态"],
      recommendations: [
        { title: "P1 先校验风险与医嘱执行状态", priority: 1 },
        { title: "P1 满足阈值时自动准备协作与文书草稿", priority: 1 },
        { title: "P2 对敏感动作进入审批后继续执行", priority: 2 },
      ],
    };
  }

  return base;
}

function buildAgentMemory(patientId: string, question: string, executionProfile?: string) {
  const ctx = mockContexts[patientId];
  const userPreferences = ["偏好先看风险排序", "需要保留文书留痕"];
  const profile = normalizeExecutionProfile(executionProfile);
  if ((question || "").includes("自动") || profile === "full_loop") {
    userPreferences.push("允许自动闭环到协作与文书草稿");
  }
  if (profile === "escalate") {
    userPreferences.push("优先生成上报摘要与协作动作");
  }
  if (profile === "document") {
    userPreferences.push("优先沉淀护理记录与交班草稿");
  }
  return {
    conversation_summary: `已关联${ctx?.bed_no || "-"}床历史观察与最近护理动作。`,
    patient_facts: [
      ...(ctx?.diagnoses || []).slice(0, 2),
      ...(ctx?.risk_tags || []).slice(0, 3),
      ...(ctx?.latest_observations || []).slice(0, 2).map((item) => `${item.name}：${item.value}`),
    ],
    unresolved_tasks: [...(ctx?.pending_tasks || [])],
    last_actions: ctx?.latest_document_sync ? [ctx.latest_document_sync, "已完成患者上下文检索"] : ["已完成患者上下文检索"],
    user_preferences: userPreferences,
  };
}

function buildAgentPlan(payload: {
  mode: "single_model" | "agent_cluster";
  userInput: string;
  attachments?: string[];
  executionProfile?: string;
}) {
  const text = payload.userInput || "";
  const profile = normalizeExecutionProfile(payload.executionProfile);
  const wantsOrders = /医嘱|补开|申请|滴定|送检|用药/.test(text);
  const wantsCollaboration = /通知|上报|联系|医生|会诊/.test(text) || profile === "escalate" || profile === "full_loop";
  const wantsDocs = /交班|文书|护理记录|记录单|草稿|document|draft|note/i.test(text) || profile === "document" || profile === "full_loop";
  const wantsAutonomy = /自动|闭环|持续跟进|自治/.test(text) || profile === "full_loop";

  if (payload.mode === "single_model") {
    return [
      {
        id: "single_model_answer",
        title: "单模型直接回答",
        tool: "llm",
        reason: "当前以单模型模式返回总结与建议。",
        status: "done",
        auto_runnable: true,
      },
    ];
  }

  return [
    {
      id: "review_memory",
      title: "回看会话与患者记忆",
      tool: "memory",
      reason: "结合历史交互避免重复追问。",
      status: "done",
      auto_runnable: true,
    },
    {
      id: "fetch_context",
      title: "定位患者上下文",
      tool: "patient_context",
      reason: "锁定床位、诊断、风险与当前观察值。",
      status: "done",
      auto_runnable: true,
    },
    {
      id: "fetch_orders",
      title: "补充医嘱执行状态",
      tool: "patient_orders",
      reason: "高风险患者需联动到时与待执行医嘱。",
      status: wantsOrders || wantsAutonomy || profile !== "observe" ? "done" : "skipped",
      auto_runnable: true,
    },
    {
      id: "recommend",
      title: "生成临床处置建议",
      tool: "recommendation",
      reason: "先形成结构化判断，再决定后续动作。",
      status: "done",
      auto_runnable: true,
    },
    {
      id: "send_collaboration",
      title: "向值班医生发起协作",
      tool: "collaboration",
      reason: "高风险或明确通知诉求形成闭环。",
      status: wantsCollaboration || wantsAutonomy ? "done" : "skipped",
      auto_runnable: true,
    },
    {
      id: "create_handover",
      title: "生成交班草稿",
      tool: "handover",
      reason: "沉淀风险与下一班待办。",
      status: wantsDocs || wantsAutonomy ? "done" : "skipped",
      auto_runnable: true,
    },
    {
      id: "create_document",
      title: "生成护理文书草稿",
      tool: "document",
      reason: "保留可审核留痕。",
      status: wantsDocs || wantsAutonomy ? "done" : "skipped",
      auto_runnable: true,
    },
    {
      id: "request_order",
      title: "创建医嘱请求",
      tool: "order_request",
      reason: "仅创建请求，不直接替代医生下单。",
      status: wantsOrders ? "done" : "skipped",
      auto_runnable: true,
    },
    {
      id: "multimodal_review",
      title: "分析附件与图片",
      tool: "multimodal",
      reason: "对图片/PDF做补充判读。",
      status: payload.attachments?.length ? "done" : "skipped",
      auto_runnable: true,
    },
  ];
}

function buildAgentArtifacts(patientId: string, question: string, plan: Array<{ id: string; status: string }>) {
  const artifacts: AIChatResponse["artifacts"] = [];
  const text = question || "";
  const patient = mockPatients[patientId];
  const bedNo = mockContexts[patientId]?.bed_no || "-";

  if (plan.some((item) => item.id === "send_collaboration" && item.status === "done")) {
    artifacts.push({
      kind: "collaboration_message",
      title: `已通知值班医生关注${bedNo}床`,
      status: "created",
      reference_id: `collab-${Date.now()}`,
      summary: `${patient?.full_name || patientId}当前存在高风险信号，已形成协作消息。`,
      metadata: { channel: "doctor_on_call", patient_id: patientId },
    });
  }
  if (plan.some((item) => item.id === "create_handover" && item.status === "done")) {
    artifacts.push({
      kind: "handover",
      title: `${bedNo}床交班草稿`,
      status: "created",
      reference_id: `handover-${Date.now()}`,
      summary: "已生成风险摘要与下一班重点观察事项。",
      metadata: { shift: "day", patient_id: patientId },
    });
  }
  if (plan.some((item) => item.id === "create_document" && item.status === "done")) {
    artifacts.push({
      kind: "document_draft",
      title: `${bedNo}床护理记录草稿`,
      status: "created",
      reference_id: `draft-${Date.now()}`,
      summary: "已根据当前建议生成护理文书草稿。",
      metadata: { document_type: "nursing_note", patient_id: patientId },
    });
  }
  if (plan.some((item) => item.id === "request_order" && item.status === "done")) {
    artifacts.push({
      kind: "order_request",
      title: `${bedNo}床医嘱请求`,
      status: "created",
      reference_id: `order-${Date.now()}`,
      summary: "已创建待医生确认的医嘱请求。",
      metadata: { priority: "P2", patient_id: patientId },
    });
  }
  if (!artifacts.length && /自动|闭环/.test(text)) {
    artifacts.push({
      kind: "agent_log",
      title: "已完成自动闭环预演",
      status: "created",
      reference_id: `trace-${Date.now()}`,
      summary: "当前示例未直接触发外部动作，但已保留执行轨迹。",
      metadata: { patient_id: patientId },
    });
  }

  return artifacts;
}

function buildStructuredAgentView(params: {
  patientId: string;
  bedNo?: string;
  missionTitle?: string;
  summary: string;
  findings: string[];
  recommendations: Array<{ title: string; priority: number; rationale?: string }>;
  memory: ReturnType<typeof buildAgentMemory>;
  artifacts: AIChatResponse["artifacts"];
  pendingApprovals?: AIChatResponse["pending_approvals"];
  nextActions: string[];
  executionProfile?: string;
}) {
  const profile = normalizeExecutionProfile(params.executionProfile);
  const bedNo = params.bedNo || mockContexts[params.patientId]?.bed_no || "-";
  const patientLabel = mockPatients[params.patientId]?.full_name || params.patientId;
  const fullText = [params.summary, ...params.findings, ...params.nextActions].join(" ");
  const specialistProfiles: NonNullable<ConversationHistoryItem["specialist_profiles"]> = [
    {
      id: "care_orchestrator",
      title: "护理总控代理",
      role: "总控编排",
      focus: "汇总床旁信号、审批状态与执行顺序。",
      status: "active",
      reason: `当前任务围绕${bedNo}床展开，需要稳定的主控视角。`,
      next_action: params.nextActions[0],
    },
  ];

  if (profile === "escalate" || profile === "full_loop" || /通知|上报|医生|协作|doctor|notify/i.test(fullText)) {
    specialistProfiles.push({
      id: "risk_bridge",
      title: "风险升级代理",
      role: "协作桥接",
      focus: "把异常体征整理成可沟通的升级摘要。",
      status: (params.pendingApprovals || []).some((item) => item.status === "pending") ? "active" : "recommended",
      reason: "当前任务带有升级协作信号，适合提前准备人工介入依据。",
      next_action: "确认是否触发医生协作与人工复核",
    });
  }

  if (profile === "document" || profile === "full_loop" || /交班|文书|记录|draft|document/i.test(fullText)) {
    specialistProfiles.push({
      id: "record_keeper",
      title: "记录沉淀代理",
      role: "文书留痕",
      focus: "把建议沉淀成护理记录、交接草稿和审批留痕。",
      status: "recommended",
      reason: "当前任务需要把执行结果转成可审阅材料。",
      next_action: "同步生成交接摘要与记录草稿",
    });
  }

  if (/饮食|营养|血糖|膳食|food|nutrition/i.test(fullText)) {
    specialistProfiles.push({
      id: "nutrition_support",
      title: "营养支持代理",
      role: "照护支持",
      focus: "关注饮食限制、摄入风险和代谢信号。",
      status: "recommended",
      reason: "任务文本中包含营养或代谢相关线索。",
      next_action: "核对饮食禁忌与代谢风险提示",
    });
  }

  if (/运动|活动|跌倒|康复|mobility|rehab|exercise/i.test(fullText)) {
    specialistProfiles.push({
      id: "mobility_support",
      title: "活动恢复代理",
      role: "恢复支持",
      focus: "关注活动耐量、跌倒风险和恢复节奏。",
      status: "recommended",
      reason: "当前任务涉及活动恢复或床旁安全管理。",
      next_action: "补充活动耐量和安全提醒",
    });
  }

  if (profile === "full_loop" || /随访|宣教|复测|出院|慢病|follow/i.test(fullText)) {
    specialistProfiles.push({
      id: "followup_link",
      title: "随访连接代理",
      role: "延续照护",
      focus: "承接复测、宣教和后续跟进事项。",
      status: "recommended",
      reason: "当前任务需要把当次处置延伸到后续追踪。",
      next_action: "把下一步动作收敛成随访任务单",
    });
  }

  const pendingApproval = (params.pendingApprovals || []).some((item) => item.status === "pending");
  const hybridCarePath: NonNullable<ConversationHistoryItem["hybrid_care_path"]> = [
    {
      id: "task_intake",
      title: "任务接收",
      status: "done",
      owner: "护理总控代理",
      summary: params.missionTitle || "已接收当前问题与任务约束。",
    },
    {
      id: "bedside_assessment",
      title: "床旁研判",
      status: params.findings.length || params.recommendations.length ? "done" : "active",
      owner: "风险扫描",
      summary: params.findings[0] || params.summary,
    },
    {
      id: "human_gate",
      title: "人工闸门",
      status: pendingApproval ? "active" : "done",
      owner: "责任护士 / 医生",
      summary: pendingApproval ? "敏感动作等待人工审批。" : "当前结果已准备好进入人工复核或协作。",
    },
    {
      id: "execution_recycle",
      title: "执行回收",
      status: params.artifacts.length || params.nextActions.length ? "active" : "pending",
      owner: "执行队列",
      summary: "将建议、文书与后续任务重新汇总回本次 run。",
    },
  ];

  const signalPool = [...params.findings, ...params.memory.patient_facts, ...params.nextActions];
  const riskFactors = signalPool
    .filter((item, index, array) => array.indexOf(item) === index)
    .filter((item) => /风险|异常|低|高|尿量|血压|review|升级|协作|发热/i.test(item))
    .slice(0, 6);
  const recommendationTitles = params.recommendations.map((item) => item.title).filter(Boolean);
  const dataCapsule: ConversationHistoryItem["data_capsule"] = {
    patient_id: params.patientId,
    version: `capsule-${Date.now()}`,
    event_summary: [params.missionTitle, params.summary, ...params.findings.slice(0, 2), ...recommendationTitles.slice(0, 2)].filter(
      Boolean
    ),
    time_axis: [`current_run:${new Date().toISOString()}`, ...params.memory.last_actions.slice(0, 2), ...params.nextActions.slice(0, 2)],
    data_layers: [
      "任务意图层：记录本次目标、成功标准与操作备注。",
      "风险信号层：沉淀异常观察、重点 findings 与需关注阈值。",
      "执行记录层：保留计划、工具调用与产出物。",
      "人工闸门层：追踪审批、复核与后续动作。",
    ],
    risk_factors: riskFactors.length ? riskFactors : ["当前结果仍需人工复核后再闭环执行。"],
  };

  const riskNodes = dataCapsule.risk_factors.slice(0, 3).map((item) => `risk:${item}`);
  const actionNodes = recommendationTitles.slice(0, 3).map((item) => `action:${item}`);
  const artifactNodes = params.artifacts.slice(0, 2).map((item) => `artifact:${item.title}`);
  const healthGraph: ConversationHistoryItem["health_graph"] = {
    nodes: [`patient:${patientLabel}@${bedNo}床`, ...riskNodes, ...actionNodes, ...artifactNodes].slice(0, 8),
    edges: [
      ...riskNodes.map((item) => `patient:${patientLabel}@${bedNo}床 -> ${item}`),
      ...actionNodes.map((item, index) => `${riskNodes[index] || `patient:${patientLabel}@${bedNo}床`} -> ${item}`),
      ...(artifactNodes[0] && actionNodes[0] ? [`${actionNodes[0]} -> ${artifactNodes[0]}`] : []),
    ].slice(0, 8),
    dynamic_updates: [...params.nextActions.slice(0, 3), ...(params.pendingApprovals || []).filter((item) => item.status === "pending").map((item) => `approval:${item.title}`)],
  };

  const reasoningCards: NonNullable<ConversationHistoryItem["reasoning_cards"]> = [
    {
      mode: "signal_scan",
      title: "风险扫描",
      summary: params.findings.slice(0, 3).join("；") || params.summary,
      confidence: 0.84,
    },
    {
      mode: "counter_check",
      title: "逆向校核",
      summary: [...params.memory.patient_facts.slice(0, 2), ...params.findings.slice(0, 2)].join("；") || "结合既往事实进行交叉核对。",
      confidence: 0.78,
    },
    {
      mode: "action_alignment",
      title: "行动对齐",
      summary: recommendationTitles.slice(0, 3).join("；") || "建议已对齐到本次目标与执行姿态。",
      confidence: 0.82,
    },
    {
      mode: "human_gate",
      title: "人工介入依据",
      summary:
        (params.pendingApprovals || []).filter((item) => item.status === "pending").map((item) => item.title).join("；") ||
        "当前结果仍需人工复核后再推进敏感动作。",
      confidence: 0.74,
    },
  ];

  return {
    specialist_profiles: specialistProfiles,
    hybrid_care_path: hybridCarePath,
    data_capsule: dataCapsule,
    health_graph: healthGraph,
    reasoning_cards: reasoningCards,
  };
}

function buildAgentSteps(payload: {
  mode: "single_model" | "agent_cluster";
  selectedModel?: string;
  modelPlan: AIChatResponse["model_plan"];
  plan: AIChatResponse["plan"];
  artifacts: AIChatResponse["artifacts"];
}) {
  if (payload.mode === "single_model") {
    return [
      {
        agent: "Single Model Runner",
        status: "done",
        note: `使用${payload.selectedModel || "minicpm3_4b_local"}完成直接回答。`,
        input: { mode: "single_model" },
        output: { model_count: 1 },
      },
    ];
  }

  const steps: AIChatResponse["steps"] = [
    {
      agent: "问题识别",
      status: "done",
      note: "已识别为需要持续处理的护理任务。",
      input: { cluster_models: payload.modelPlan.length },
      output: { next: "care_memory" },
    },
    {
      agent: "历史回看",
      status: "done",
      note: "已补看历史记录和患者重点。",
      output: { completed: "review_memory" },
    },
    {
      agent: "病例信息整理",
      status: "done",
      note: "已补看患者背景和当前风险提醒。",
      output: { completed: "fetch_context" },
    },
  ];

  payload.plan
    .filter((item) => item.status === "done" && !["review_memory", "fetch_context"].includes(item.id))
    .forEach((item) => {
      steps.push({
        agent:
          item.id === "fetch_orders"
            ? "Order Signal Agent"
            : item.id === "recommend"
            ? "Recommendation Agent"
            : item.id === "send_collaboration"
            ? "Collaboration Agent"
            : item.id === "create_handover"
            ? "Handover Agent"
            : item.id === "create_document"
            ? "Document Agent"
            : item.id === "request_order"
            ? "Order Request Agent"
            : "Tool Runner Agent",
        status: "done",
        note: item.title,
        output: { completed: item.id },
      });
    });

  steps.push({
    agent: "留痕记录",
    status: "done",
    note: "已保存本次处理记录。",
    output: { artifacts: payload.artifacts.length },
  });

  return steps;
}

function buildQueueApprovals(task: AgentQueueTask): AgentQueueTask["approvals"] {
  const text = buildMissionAwareText(
    task.payload.user_input,
    task.payload.mission_title,
    task.payload.success_criteria,
    task.payload.operator_notes
  );
  const profile = normalizeExecutionProfile(task.payload.execution_profile);
  const approvals: AgentQueueTask["approvals"] = [];
  const addApproval = (itemId: string, title: string, reason: string) => {
    approvals.push({
      id: `approval-${itemId}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      item_id: itemId,
      tool_id: itemId,
      title,
      reason,
      status: "pending",
      created_at: nowIso(),
      metadata: {
        patient_id: task.payload.patient_id,
        bed_no: task.payload.bed_no,
      },
    });
  };

  if (/通知|上报|医生|notify|doctor/i.test(text) || profile === "escalate" || profile === "full_loop") {
    addApproval("send_collaboration", "通知值班医生", "该动作会发送真实协作消息，需要人工确认。");
  }
  if (/交班|handover/i.test(text) || profile === "document" || profile === "full_loop") {
    addApproval("create_handover", "生成交班草稿", "交班草稿会进入待审核区，需要人工确认。");
  }
  if (/文书|护理记录|记录单|document|draft|note/i.test(text) || profile === "document" || profile === "full_loop") {
    addApproval("create_document", "生成护理文书草稿", "文书草稿会写入可审核记录，需要人工确认。");
  }
  if (/医嘱|补开|申请|order/i.test(text)) {
    addApproval("request_order", "创建医嘱请求", "医嘱请求会进入待确认流程，需要人工审批。");
  }

  return approvals;
}

function buildQueuePlan(task: AgentQueueTask, pendingApprovals: AgentQueueTask["approvals"]) {
  const plannerText = buildMissionAwareText(
    task.payload.user_input,
    task.payload.mission_title,
    task.payload.success_criteria,
    task.payload.operator_notes
  );
  const plan = buildAgentPlan({
    mode: "agent_cluster",
    userInput: plannerText,
    attachments: task.payload.attachments,
    executionProfile: task.payload.execution_profile,
  });
  const pendingIds = new Set(pendingApprovals.filter((item) => item.status === "pending").map((item) => item.item_id));
  return plan.map((item) => {
    if (pendingIds.has(item.id)) {
      return { ...item, status: "approval_required" };
    }
    if (task.payload.approved_actions.includes(item.id)) {
      return { ...item, status: "done" };
    }
    if (task.payload.rejected_actions.includes(item.id)) {
      return { ...item, status: "rejected" };
    }
    return item;
  });
}

function buildQueueOutput(task: AgentQueueTask, pendingApprovals: AgentQueueTask["approvals"]) {
  const patientId = task.payload.patient_id || "pat-001";
  const profile = normalizeExecutionProfile(task.payload.execution_profile);
  const plannerText = buildMissionAwareText(
    task.payload.user_input,
    task.payload.mission_title,
    task.payload.success_criteria,
    task.payload.operator_notes
  );
  const dynamic = dynamicSummary(plannerText || task.payload.user_input || "", profile);
  const plan = buildQueuePlan(task, pendingApprovals);
  const artifacts = pendingApprovals.length > 0 ? [] : buildAgentArtifacts(patientId, plannerText || task.payload.user_input || "", plan);
  const steps =
    pendingApprovals.length > 0
      ? [
          {
            agent: "Queue Worker",
            status: "done",
            note: "后台任务已推进到审批闸门。",
          },
          {
            agent: "Approval Gate",
            status: "approval_required",
            note: "等待人工确认敏感动作后继续执行。",
          },
        ]
      : buildAgentSteps({
          mode: "agent_cluster",
          modelPlan: [],
          plan,
          artifacts,
        });
  const memory = buildAgentMemory(patientId, plannerText || task.payload.user_input || "", profile);
  const nextActions =
    pendingApprovals.length > 0
      ? pendingApprovals.map((item) => `等待人工审批：${item.title}`)
      : dynamic.recommendations.map((item) => item.title).slice(0, 4);
  const structured = buildStructuredAgentView({
    patientId,
    bedNo: task.payload.bed_no,
    missionTitle: task.payload.mission_title,
    summary:
      pendingApprovals.length > 0
        ? withMissionSummary("后台任务已推进到审批闸门，等待护士确认后继续执行。", task.payload.mission_title)
        : withMissionSummary(dynamic.summary, task.payload.mission_title),
    findings: dynamic.findings,
    recommendations: dynamic.recommendations,
    memory,
    artifacts,
    pendingApprovals,
    nextActions,
    executionProfile: profile,
  });

  return {
    workflow_type: task.workflow_type,
    summary:
      pendingApprovals.length > 0
        ? withMissionSummary("后台任务已推进到审批闸门，等待护士确认后继续执行。", task.payload.mission_title)
        : withMissionSummary(dynamic.summary, task.payload.mission_title),
    findings: dynamic.findings,
    recommendations: dynamic.recommendations,
    confidence: pendingApprovals.length > 0 ? 0.78 : 0.86,
    review_required: true,
    patient_id: patientId,
    patient_name: mockPatients[patientId]?.full_name,
    bed_no: task.payload.bed_no,
    steps,
    run_id: task.run_id,
    runtime_engine: task.runtime_engine,
    agent_goal: task.payload.mission_title
      ? `围绕${task.payload.bed_no || "-"}床推进任务「${task.payload.mission_title}」，执行姿态为${EXECUTION_PROFILE_LABELS[profile]}`
      : `围绕${task.payload.bed_no || "-"}床执行${EXECUTION_PROFILE_LABELS[profile]}任务`,
    agent_mode: task.payload.agent_mode || "assisted",
    execution_profile: profile,
    mission_title: task.payload.mission_title,
    success_criteria: task.payload.success_criteria || [],
    plan,
    memory,
    artifacts,
    ...structured,
    pending_approvals: pendingApprovals,
    next_actions: nextActions,
    created_at: nowIso(),
  };
}

function syncQueueTasks() {
  mockQueueTasks.forEach((task) => {
    if (task.status !== "queued") {
      return;
    }

    const now = nowIso();
    task.runtime_engine = buildRuntimeStatus().active_engine;
    task.run_id = task.run_id || `run-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    task.attempt_count += 1;
    task.started_at = task.started_at || now;

    const approvalText = buildMissionAwareText(
      task.payload.user_input,
      task.payload.mission_title,
      task.payload.success_criteria,
      task.payload.operator_notes
    );

    if (!task.approvals.length && queueNeedsApproval(approvalText || task.payload.user_input || "", task.payload.execution_profile)) {
      const approvals = buildQueueApprovals(task);
      task.approvals = approvals;
      task.status = "waiting_approval";
      task.summary = "后台任务已推进到审批闸门。";
      task.last_output = buildQueueOutput(task, approvals);
      task.updated_at = now;
      return;
    }

    if (task.approvals.some((item) => item.status === "pending")) {
      return;
    }

    task.status = "completed";
    task.summary = "后台任务已完成。";
    task.last_output = buildQueueOutput(task, []);
    task.updated_at = now;
    task.completed_at = now;

    pushConversationHistory({
      id: `queue_${task.id}`,
      source: "agent-queue",
      workflow_type: task.workflow_type,
      patient_id: task.payload.patient_id,
      conversation_id: task.payload.conversation_id,
      user_input: task.payload.user_input,
      summary: task.last_output.summary,
      created_at: now,
      confidence: task.last_output.confidence,
      review_required: true,
      run_id: task.run_id,
      runtime_engine: task.runtime_engine,
      findings: task.last_output.findings,
      recommendations: task.last_output.recommendations,
      steps: task.last_output.steps,
      agent_goal: task.last_output.agent_goal,
      agent_mode: task.last_output.agent_mode,
      execution_profile: task.last_output.execution_profile,
      mission_title: task.last_output.mission_title,
      success_criteria: task.last_output.success_criteria,
      plan: task.last_output.plan,
      memory: task.last_output.memory,
      artifacts: task.last_output.artifacts,
      specialist_profiles: task.last_output.specialist_profiles,
      hybrid_care_path: task.last_output.hybrid_care_path,
      data_capsule: task.last_output.data_capsule,
      health_graph: task.last_output.health_graph,
      reasoning_cards: task.last_output.reasoning_cards,
      pending_approvals: task.last_output.pending_approvals,
      next_actions: task.last_output.next_actions,
    });
  });
}

function buildMockToolExecutions(plan: Array<{ id: string; title: string; tool?: string; status: string }>, anchorTime: string) {
  return plan
    .filter((item) => item.status !== "pending" && item.status !== "skipped" && item.status !== "approval_required")
    .map((item, index) => ({
      item_id: item.id,
      title: item.title,
      tool: item.tool,
      agent: item.tool ? `${item.tool}_agent` : "planner_agent",
      status: item.status,
      attempts: item.status === "failed" ? 2 : 1,
      retryable: item.tool === "recommend" || item.tool === "recommendation" || item.tool === "patient_orders",
      started_at: anchorTime,
      finished_at: anchorTime,
      output: {
        plan_index: index + 1,
        status: item.status,
      },
      error: item.status === "failed" ? "mock_execution_failed" : undefined,
    }));
}

function buildRunRecordFromQueueTask(task: AgentQueueTask): AgentRunRecord {
  const output = task.last_output || buildQueueOutput(task, task.approvals.filter((item) => item.status === "pending"));
  return {
    id: task.run_id || task.id,
    status: task.status,
    workflow_type: task.workflow_type,
    runtime_engine: task.runtime_engine || task.requested_engine || buildRuntimeStatus().active_engine,
    request: {
      workflow_type: task.payload.workflow_type,
      patient_id: task.payload.patient_id,
      conversation_id: task.payload.conversation_id,
      department_id: task.payload.department_id,
      bed_no: task.payload.bed_no,
      user_input: task.payload.user_input,
      mission_title: task.payload.mission_title,
      success_criteria: task.payload.success_criteria || [],
      operator_notes: task.payload.operator_notes,
      requested_by: task.payload.requested_by,
      agent_mode: task.payload.agent_mode,
      execution_profile: task.payload.execution_profile,
      attachments_count: task.payload.attachments.length,
      approved_actions: task.payload.approved_actions,
      rejected_actions: task.payload.rejected_actions,
    },
    patient_id: output.patient_id,
    patient_name: output.patient_name,
    bed_no: output.bed_no,
    conversation_id: task.payload.conversation_id,
    agent_goal: output.agent_goal,
    agent_mode: output.agent_mode,
    summary: task.summary || output.summary,
    plan: output.plan,
    memory: output.memory,
    artifacts: output.artifacts,
    specialist_profiles: output.specialist_profiles || [],
    hybrid_care_path: output.hybrid_care_path || [],
    data_capsule: output.data_capsule,
    health_graph: output.health_graph,
    reasoning_cards: output.reasoning_cards || [],
    next_actions: output.next_actions,
    steps: output.steps,
    tool_executions: buildMockToolExecutions(output.plan, task.updated_at),
    pending_approvals: task.approvals,
    retry_available: task.status !== "running",
    error: task.error,
    created_at: task.created_at,
    updated_at: task.updated_at,
    completed_at: task.completed_at,
  };
}

function buildRunRecordFromHistory(item: ConversationHistoryItem): AgentRunRecord | null {
  if (!item.run_id) {
    return null;
  }
  return {
    id: item.run_id,
    status: item.pending_approvals?.some((entry) => entry.status === "pending") ? "waiting_approval" : "completed",
    workflow_type: item.workflow_type,
    runtime_engine: item.runtime_engine || buildRuntimeStatus().active_engine,
    request: {
      workflow_type: item.workflow_type,
      patient_id: item.patient_id,
      conversation_id: item.conversation_id,
      department_id: undefined,
      bed_no: undefined,
      user_input: item.user_input,
      mission_title: item.mission_title,
      success_criteria: item.success_criteria || [],
      operator_notes: undefined,
      requested_by: undefined,
      agent_mode: item.agent_mode,
      execution_profile: item.execution_profile,
      attachments_count: 0,
      approved_actions: [],
      rejected_actions: [],
    },
    patient_id: item.patient_id,
    patient_name: item.patient_id ? mockPatients[item.patient_id]?.full_name : undefined,
    bed_no: item.patient_id ? mockContexts[item.patient_id]?.bed_no : undefined,
    conversation_id: item.conversation_id,
    agent_goal: item.agent_goal,
    agent_mode: item.agent_mode || "workflow",
    summary: item.summary,
    plan: item.plan || [],
    memory: item.memory,
    artifacts: item.artifacts || [],
    specialist_profiles: item.specialist_profiles || [],
    hybrid_care_path: item.hybrid_care_path || [],
    data_capsule: item.data_capsule,
    health_graph: item.health_graph,
    reasoning_cards: item.reasoning_cards || [],
    next_actions: item.next_actions || [],
    steps: item.steps || [],
    tool_executions: buildMockToolExecutions(item.plan || [], item.created_at),
    pending_approvals: item.pending_approvals || [],
    retry_available: true,
    error: undefined,
    created_at: item.created_at,
    updated_at: item.created_at,
    completed_at: item.created_at,
  };
}

function collectMockRuns(options?: {
  patientId?: string;
  conversationId?: string;
  status?: string;
  workflowType?: string;
  limit?: number;
}) {
  syncQueueTasks();
  const records = new Map<string, AgentRunRecord>();

  mockQueueTasks.forEach((task) => {
    if (!task.run_id) {
      return;
    }
    records.set(task.run_id, buildRunRecordFromQueueTask(task));
  });

  mockConversationHistory.forEach((item) => {
    const record = buildRunRecordFromHistory(item);
    if (!record) {
      return;
    }
    if (!records.has(record.id)) {
      records.set(record.id, record);
    }
  });

  return Array.from(records.values())
    .filter((item) => (!options?.patientId ? true : item.patient_id === options.patientId))
    .filter((item) => (!options?.conversationId ? true : item.conversation_id === options.conversationId))
    .filter((item) => (!options?.status ? true : item.status === options.status))
    .filter((item) => (!options?.workflowType ? true : item.workflow_type === options.workflowType))
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, options?.limit || 20);
}

export const mockApi = {
  async login(username: string, password: string) {
    await sleep(300);
    const user = mockUsers[username];
    if (!user || user.password !== password) {
      throw new Error("invalid_credentials");
    }
    return {
      access_token: `mock_access_${username}`,
      refresh_token: `mock_refresh_${username}`,
      user: { id: user.id, full_name: user.full_name, role_code: user.role_code },
    };
  },

  async register(payload: {
    username: string;
    password: string;
    full_name: string;
    role_code?: string;
  }) {
    await sleep(300);
    if (mockUsers[payload.username]) {
      throw new Error("username_exists");
    }
    mockUsers[payload.username] = {
      id: `u_${payload.username}`,
      full_name: payload.full_name,
      role_code: payload.role_code || "nurse",
      password: payload.password,
    };
    return { ok: true };
  },

  async getWardBeds() {
    await sleep(250);
    return mockBeds;
  },

  async getPatient(patientId: string) {
    await sleep(250);
    return mockPatients[patientId];
  },

  async getPatientContext(patientId: string) {
    await sleep(250);
    return mockContexts[patientId];
  },

  async getPatientOrders(patientId: string): Promise<OrderListOut> {
    await sleep(260);
    const orders = cloneOrder(mockOrdersByPatient[patientId] || []);
    return {
      patient_id: patientId,
      stats: getOrderStats(orders),
      orders,
    };
  },

  async getPatientOrderHistory(patientId: string, limit = 80): Promise<ClinicalOrder[]> {
    await sleep(220);
    return cloneOrder((mockOrderHistoryByPatient[patientId] || []).slice(0, limit));
  },

  async doubleCheckOrder(orderId: string, checkedBy: string, note?: string): Promise<ClinicalOrder> {
    await sleep(220);
    const allOrders = Object.values(mockOrdersByPatient).flat();
    const order = allOrders.find((item) => item.id === orderId);
    if (!order) {
      throw new Error("order_not_found");
    }
    order.status = "checked";
    order.check_by = checkedBy;
    order.check_at = nowIso();
    order.audit_trail.push({
      action: "double_checked",
      actor: checkedBy,
      note: note || "双人核对完成",
      created_at: nowIso(),
    });
    return cloneOrder(order);
  },

  async executeOrder(orderId: string, executedBy: string, note?: string): Promise<ClinicalOrder> {
    await sleep(220);
    const patientId = Object.keys(mockOrdersByPatient).find((pid) =>
      (mockOrdersByPatient[pid] || []).some((item) => item.id === orderId)
    );
    if (!patientId) {
      throw new Error("order_not_found");
    }
    const idx = (mockOrdersByPatient[patientId] || []).findIndex((item) => item.id === orderId);
    if (idx < 0) {
      throw new Error("order_not_found");
    }
    const order = mockOrdersByPatient[patientId][idx];
    order.status = "executed";
    order.executed_by = executedBy;
    order.executed_at = nowIso();
    order.execution_note = note || "按医嘱执行";
    order.audit_trail.push({
      action: "executed",
      actor: executedBy,
      note: order.execution_note,
      created_at: nowIso(),
    });
    mockOrdersByPatient[patientId].splice(idx, 1);
    mockOrderHistoryByPatient[patientId] = [cloneOrder(order), ...(mockOrderHistoryByPatient[patientId] || [])];
    return cloneOrder(order);
  },

  async reportOrderException(orderId: string, reportedBy: string, reason: string): Promise<ClinicalOrder> {
    await sleep(220);
    const patientId = Object.keys(mockOrdersByPatient).find((pid) =>
      (mockOrdersByPatient[pid] || []).some((item) => item.id === orderId)
    );
    if (!patientId) {
      throw new Error("order_not_found");
    }
    const idx = (mockOrdersByPatient[patientId] || []).findIndex((item) => item.id === orderId);
    if (idx < 0) {
      throw new Error("order_not_found");
    }
    const order = mockOrdersByPatient[patientId][idx];
    order.status = "exception";
    order.exception_reason = reason;
    order.audit_trail.push({
      action: "exception_reported",
      actor: reportedBy,
      note: reason,
      created_at: nowIso(),
    });
    mockOrdersByPatient[patientId].splice(idx, 1);
    mockOrderHistoryByPatient[patientId] = [cloneOrder(order), ...(mockOrderHistoryByPatient[patientId] || [])];
    return cloneOrder(order);
  },

  async createOrderRequest(payload: {
    patientId: string;
    requestedBy: string;
    title: string;
    details: string;
    priority?: string;
  }): Promise<ClinicalOrder> {
    await sleep(260);
    const now = new Date().toISOString();
    const order: ClinicalOrder = {
      id: `ord-req-${Date.now()}`,
      patient_id: payload.patientId,
      encounter_id: undefined,
      order_no: `REQ-${Date.now().toString().slice(-8)}`,
      order_type: "doctor_review_request",
      title: payload.title,
      instruction: payload.details,
      route: "会诊请求",
      dosage: undefined,
      frequency: "once",
      priority: payload.priority || "P2",
      status: "pending",
      ordered_by: payload.requestedBy,
      ordered_at: now,
      due_at: minutesFromNow(30),
      requires_double_check: false,
      check_by: undefined,
      check_at: undefined,
      executed_by: undefined,
      executed_at: undefined,
      execution_note: undefined,
      exception_reason: undefined,
      risk_hints: ["AI生成请求", "需医生确认后执行"],
      audit_trail: [
        {
          action: "request_created",
          actor: payload.requestedBy,
          note: "AI助手已生成医嘱请求",
          created_at: now,
        },
      ],
    };
    mockOrdersByPatient[payload.patientId] = [order, ...(mockOrdersByPatient[payload.patientId] || [])];
    return cloneOrder(order);
  },

  async getAiModels(): Promise<AIModelsCatalog> {
    await sleep(180);
    return {
      single_models: [
        {
          id: "minicpm3_4b_local",
          name: "MiniCPM3-4B（本地中文优先）",
          provider: "local",
          description: "推荐：中文语境更强，CPU友好（Q4量化）",
        },
        {
          id: "qwen2_5_3b_local",
          name: "Qwen2.5-3B（本地轻量）",
          provider: "local",
          description: "备用：更轻量，低内存设备优先",
        },
        {
          id: "qwen3_8b_local",
          name: "下一步安排（本地）",
          provider: "local",
          description: "负责补齐下一步安排",
        },
        {
          id: "deepseek_r1_qwen_7b_local",
          name: "重点再看一遍（本地）",
          provider: "local",
          description: "负责复杂情况再看一遍",
        },
        {
          id: "bailian_main",
          name: "阿里百炼主模型",
          provider: "bailian",
          description: "综合推理与临床问答",
        },
        {
          id: "medgemma_local",
          name: "MedGemma 4B（本地）",
          provider: "local",
          description: "多模态医学判读",
        },
        {
          id: "qwen_light",
          name: "Qwen轻量模型",
          provider: "bailian",
          description: "快速问答",
        },
      ],
      cluster_profiles: [
        {
          id: "nursing_default_cluster",
          name: "系统协同",
          main_model: "当前回复整理（本地）",
          description: "系统会分工完成当前回复、顺序整理、重点再看一遍、附件读取和语音整理。",
          tasks: [
            {
              model_id: "care-planner",
              model_name: "处理顺序整理",
              role: "顺序整理",
              task: "把当前情况拆成先做、后做和谁来确认",
              enabled: true,
            },
            {
              model_id: "qwen3-8b-local-planner",
              model_name: "下一步安排",
              role: "梳理先后",
              task: "补齐漏掉的步骤，告诉你先做什么后做什么",
              enabled: true,
            },
            {
              model_id: "deepseek-r1-local",
              model_name: "重点再看一遍",
              role: "再核对",
              task: "对复杂情况再看一遍，避免遗漏",
              enabled: true,
            },
            {
              model_id: "minicpm3-4b-local-main",
              model_name: "当前回复整理（本地）",
              role: "整理重点",
              task: "理解提问、整理重点并生成护士能直接看的说明",
              enabled: true,
            },
            {
              model_id: "minicpm3-4b-local",
              model_name: "快速回答（本地）",
              role: "快速回答",
              task: "把问题先整理成护士能直接使用的说明",
              enabled: true,
            },
            {
              model_id: "funasr-local",
              model_name: "语音转文字",
              role: "转成文字",
              task: "把语音内容整理成文字",
              enabled: true,
            },
            {
              model_id: "medgemma-local",
              model_name: "附件读取",
              role: "附件查看",
              task: "查看图片、PDF 和检查报告附件",
              enabled: true,
            },
            {
              model_id: "cosyvoice-local",
              model_name: "结果播报",
              role: "语音播报",
              task: "把结果读出来",
              enabled: true,
            },
          ],
        },
      ],
    };
  },

  async getAiRuntimeStatus(): Promise<AIRuntimeStatus> {
    await sleep(150);
    return buildRuntimeStatus();
  },

  async setAiRuntimeEngine(engine: "state_machine" | "langgraph"): Promise<AIRuntimeStatus> {
    await sleep(160);
    mockRuntimeOverride = engine;
    return buildRuntimeStatus();
  },

  async clearAiRuntimeEngine(): Promise<AIRuntimeStatus> {
    await sleep(140);
    mockRuntimeOverride = "";
    return buildRuntimeStatus();
  },

  async listAgentRuns(options?: {
    patientId?: string;
    conversationId?: string;
    status?: string;
    workflowType?: string;
    limit?: number;
  }) {
    await sleep(140);
    return collectMockRuns(options);
  },

  async getAgentRun(runId: string) {
    await sleep(120);
    const item = collectMockRuns({ limit: 200 }).find((entry) => entry.id === runId);
    if (!item) {
      throw new Error("run_not_found");
    }
    return item;
  },

  async retryAgentRun(runId: string) {
    await sleep(180);
    const original = collectMockRuns({ limit: 200 }).find((entry) => entry.id === runId);
    if (!original || !original.retry_available) {
      throw new Error("retry_unavailable");
    }

    const profile = normalizeExecutionProfile(original.request.execution_profile);
    const plannerText = buildMissionAwareText(
      original.request.user_input,
      original.request.mission_title,
      original.request.success_criteria,
      original.request.operator_notes
    );
    const dynamic = dynamicSummary(plannerText || original.request.user_input || "", profile);
    const plan = (original.plan || []).map((item) => ({
      ...item,
      status: item.status === "failed" || item.status === "approval_required" ? "pending" : item.status,
    }));
    const artifacts = buildAgentArtifacts(original.patient_id || "pat-001", plannerText || original.request.user_input || "", plan);
    const memory = buildAgentMemory(original.patient_id || "pat-001", plannerText || original.request.user_input || "", profile);
    const pendingApprovals =
      original.pending_approvals?.filter((item) => item.status === "pending").map((item) => ({
        ...item,
        id: `approval-${item.item_id}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        created_at: nowIso(),
        decided_at: undefined,
        decided_by: undefined,
        comment: undefined,
      })) || [];
    const nextActions =
      pendingApprovals.length > 0
        ? pendingApprovals.map((item) => `等待人工审批：${item.title}`)
        : dynamic.recommendations.map((item) => item.title).slice(0, 4);
    const structured = buildStructuredAgentView({
      patientId: original.patient_id || "pat-001",
      bedNo: original.bed_no,
      missionTitle: original.request.mission_title,
      summary:
        pendingApprovals.length > 0
          ? withMissionSummary("任务已重新执行，并再次停留在审批闸门等待确认。", original.request.mission_title)
          : withMissionSummary(dynamic.summary, original.request.mission_title),
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      plan,
      memory,
      approvals: pendingApprovals,
      executionProfile: profile,
    });
    const createdAt = nowIso();
    const output = {
      workflow_type: original.workflow_type,
      summary:
        pendingApprovals.length > 0
          ? withMissionSummary("任务已重新执行，并再次停留在审批闸门等待确认。", original.request.mission_title)
          : withMissionSummary(dynamic.summary, original.request.mission_title),
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      confidence: pendingApprovals.length > 0 ? 0.78 : 0.84,
      review_required: true,
      patient_id: original.patient_id,
      patient_name: original.patient_name,
      bed_no: original.bed_no,
      steps:
        pendingApprovals.length > 0
          ? [
              { agent: "Retry Runner", status: "done", note: "已按原始请求重新运行一次。", output: { retry_of: runId } },
              { agent: "Approval Gate", status: "approval_required", note: "敏感动作仍需人工确认。", output: { approvals: pendingApprovals.length } },
            ]
          : buildAgentSteps({
              mode: original.agent_mode === "direct_answer" ? "single_model" : "agent_cluster",
              modelPlan: [],
              plan,
              artifacts,
            }),
      run_id: `run-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      runtime_engine: buildRuntimeStatus().active_engine,
      agent_goal:
        original.request.mission_title && original.bed_no
          ? `围绕${original.bed_no}床重新推进任务「${original.request.mission_title}」`
          : original.agent_goal,
      agent_mode: original.agent_mode,
      execution_profile: profile,
      mission_title: original.request.mission_title,
      success_criteria: original.request.success_criteria || [],
      plan,
      memory,
      artifacts,
      specialist_profiles: structured.specialist_profiles,
      hybrid_care_path: structured.hybrid_care_path,
      data_capsule: structured.data_capsule,
      health_graph: structured.health_graph,
      reasoning_cards: structured.reasoning_cards,
      pending_approvals: pendingApprovals,
      next_actions: nextActions,
      created_at: createdAt,
    };

    pushConversationHistory({
      id: `retry_${output.run_id}`,
      source: "agent-orchestrator",
      workflow_type: output.workflow_type,
      patient_id: output.patient_id,
      conversation_id: original.conversation_id,
      user_input: original.request.user_input,
      summary: output.summary,
      created_at: output.created_at,
      confidence: output.confidence,
      review_required: output.review_required,
      run_id: output.run_id,
      runtime_engine: output.runtime_engine,
      findings: output.findings,
      recommendations: output.recommendations,
      steps: output.steps,
      agent_goal: output.agent_goal,
      agent_mode: output.agent_mode,
      execution_profile: output.execution_profile,
      mission_title: output.mission_title,
      success_criteria: output.success_criteria,
      plan: output.plan,
      memory: output.memory,
      artifacts: output.artifacts,
      specialist_profiles: output.specialist_profiles,
      hybrid_care_path: output.hybrid_care_path,
      data_capsule: output.data_capsule,
      health_graph: output.health_graph,
      reasoning_cards: output.reasoning_cards,
      pending_approvals: output.pending_approvals,
      next_actions: output.next_actions,
    });

    return output;
  },

  async listAgentQueueTasks(options?: {
    patientId?: string;
    conversationId?: string;
    status?: string;
    limit?: number;
  }) {
    await sleep(140);
    syncQueueTasks();
    return mockQueueTasks
      .filter((item) => (!options?.patientId ? true : item.payload.patient_id === options.patientId))
      .filter((item) => (!options?.conversationId ? true : item.payload.conversation_id === options.conversationId))
      .filter((item) => (!options?.status ? true : item.status === options.status))
      .slice()
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, options?.limit || 20);
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
  }) {
    await sleep(180);
    const now = nowIso();
    const profile = normalizeExecutionProfile(payload.executionProfile);
    const task: AgentQueueTask = {
      id: `task-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      status: "queued",
      payload: {
        workflow_type: payload.workflowType,
        patient_id: payload.patientId,
        conversation_id: payload.conversationId,
        department_id: payload.departmentId,
        bed_no: payload.bedNo,
        user_input: payload.userInput,
        mission_title: payload.missionTitle,
        success_criteria: payload.successCriteria || [],
        operator_notes: payload.operatorNotes,
        attachments: payload.attachments || [],
        requested_by: payload.requestedBy,
        agent_mode: payload.agentMode,
        execution_profile: normalizeExecutionProfile(payload.executionProfile),
        approved_actions: [],
        rejected_actions: [],
      },
      workflow_type: payload.workflowType,
      requested_engine: payload.requestedEngine,
      runtime_engine: undefined,
      priority: payload.priority || 80,
      run_id: undefined,
      summary: payload.missionTitle ? `任务「${payload.missionTitle}」已进入后台队列。` : `${EXECUTION_PROFILE_LABELS[profile]}任务已进入后台队列。`,
      approvals: [],
      last_output: undefined,
      error: undefined,
      attempt_count: 0,
      resume_count: 0,
      created_at: now,
      updated_at: now,
      started_at: undefined,
      completed_at: undefined,
    };
    mockQueueTasks.unshift(task);
    return task;
  },

  async approveAgentQueueTask(payload: {
    taskId: string;
    approvalIds?: string[];
    decidedBy?: string;
    comment?: string;
  }) {
    await sleep(160);
    const task = mockQueueTasks.find((item) => item.id === payload.taskId);
    if (!task) {
      throw new Error("queue_task_not_found");
    }
    const targetIds = new Set(payload.approvalIds?.length ? payload.approvalIds : task.approvals.filter((item) => item.status === "pending").map((item) => item.id));
    const now = nowIso();
    task.approvals = task.approvals.map((item) => {
      if (!targetIds.has(item.id) || item.status !== "pending") {
        return item;
      }
      if (!task.payload.approved_actions.includes(item.item_id)) {
        task.payload.approved_actions = [...task.payload.approved_actions, item.item_id];
      }
      task.payload.rejected_actions = task.payload.rejected_actions.filter((entry) => entry !== item.item_id);
      return {
        ...item,
        status: "approved",
        decided_at: now,
        decided_by: payload.decidedBy,
        comment: payload.comment,
      };
    });
    const pendingApprovals = task.approvals.filter((item) => item.status === "pending");
    task.status = pendingApprovals.length ? "waiting_approval" : "queued";
    if (!pendingApprovals.length) {
      task.resume_count += 1;
    }
    task.updated_at = now;
    task.last_output = buildQueueOutput(task, pendingApprovals);
    if (!pendingApprovals.length) {
      syncQueueTasks();
    }
    return task;
  },

  async rejectAgentQueueTask(payload: {
    taskId: string;
    approvalIds?: string[];
    decidedBy?: string;
    comment?: string;
  }) {
    await sleep(160);
    const task = mockQueueTasks.find((item) => item.id === payload.taskId);
    if (!task) {
      throw new Error("queue_task_not_found");
    }
    const targetIds = new Set(payload.approvalIds?.length ? payload.approvalIds : task.approvals.filter((item) => item.status === "pending").map((item) => item.id));
    const now = nowIso();
    task.approvals = task.approvals.map((item) => {
      if (!targetIds.has(item.id) || item.status !== "pending") {
        return item;
      }
      if (!task.payload.rejected_actions.includes(item.item_id)) {
        task.payload.rejected_actions = [...task.payload.rejected_actions, item.item_id];
      }
      task.payload.approved_actions = task.payload.approved_actions.filter((entry) => entry !== item.item_id);
      return {
        ...item,
        status: "rejected",
        decided_at: now,
        decided_by: payload.decidedBy,
        comment: payload.comment,
      };
    });
    const pendingApprovals = task.approvals.filter((item) => item.status === "pending");
    task.status = pendingApprovals.length ? "waiting_approval" : "queued";
    if (!pendingApprovals.length) {
      task.resume_count += 1;
    }
    task.updated_at = now;
    task.last_output = buildQueueOutput(task, pendingApprovals);
    if (!pendingApprovals.length) {
      syncQueueTasks();
    }
    return task;
  },

  async transcribe(textHint?: string) {
    await sleep(500);
    return { text: textHint || "12床今天最需要注意什么？", confidence: 0.94, provider: "mock" };
  },

  async generateHandover(patientId: string): Promise<HandoverResult> {
    await sleep(600);
    return {
      id: `handover_${Date.now()}`,
      patient_id: patientId,
      shift_date: new Date().toISOString().slice(0, 10),
      shift_type: "day",
      summary: "重点关注低血压与尿量变化，建议先复测生命体征并上报医生复核。",
      next_shift_priorities: ["复测血压", "记录尿量", "医生复核"],
    };
  },

  async runRecommendation(patientId: string, question: string): Promise<RecommendationResult> {
    await sleep(700);
    const dynamic = dynamicSummary(question);
    const plan = buildAgentPlan({ mode: "agent_cluster", userInput: question, attachments: [] });
    const memory = buildAgentMemory(patientId, question);
    const artifacts = buildAgentArtifacts(patientId, question, plan);
    const steps = buildAgentSteps({
      mode: "agent_cluster",
      modelPlan: [],
      plan,
      artifacts,
    });
    const nextActions = dynamic.recommendations.map((item) => item.title).slice(0, 4);
    const structured = buildStructuredAgentView({
      patientId,
      summary: dynamic.summary,
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      memory,
      artifacts,
      nextActions,
      executionProfile: "observe",
    });
    const result: RecommendationResult = {
      id: `rec_${Date.now()}`,
      patient_id: patientId,
      summary: dynamic.summary,
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      confidence: 0.81,
      review_required: true,
      metadata: {
        original_question: question,
        effective_question: question,
        agent_trace: [
          { agent: "问题识别", status: "done", note: "识别为推荐请求" },
          { agent: "病例信息整理", status: "done", note: "补看患者背景" },
          { agent: "处理建议整理", status: "done", note: "整理为可执行建议" },
          { agent: "留痕记录", status: "done", note: "保存处理记录" },
        ],
      },
    };
    pushConversationHistory({
      id: result.id,
      source: "recommendation-service",
      workflow_type: "recommendation_request",
      patient_id: patientId,
      user_input: question,
      summary: result.summary,
      created_at: new Date().toISOString(),
      confidence: result.confidence,
      review_required: result.review_required,
      findings: result.findings,
      recommendations: result.recommendations,
      steps,
      agent_goal: `为${mockContexts[patientId]?.bed_no || "-"}床生成护理建议`,
      agent_mode: "assisted",
      plan,
      memory,
      artifacts,
      specialist_profiles: structured.specialist_profiles,
      hybrid_care_path: structured.hybrid_care_path,
      data_capsule: structured.data_capsule,
      health_graph: structured.health_graph,
      reasoning_cards: structured.reasoning_cards,
      next_actions: nextActions,
    });
    return result;
  },

  async runAiChat(payload: {
    mode: "single_model" | "agent_cluster";
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
    await sleep(620);
    const patientId = payload.patientId || "pat-001";
    const profile = normalizeExecutionProfile(payload.executionProfile);
    const plannerText = buildMissionAwareText(payload.userInput, payload.missionTitle, payload.successCriteria, payload.operatorNotes);
    const dynamic = dynamicSummary(plannerText || payload.userInput, profile);
    const workflowType =
      payload.mode === "single_model"
        ? "single_model_chat"
        : profile === "full_loop"
        ? "autonomous_care"
        : profile === "document"
        ? "document_generation"
        : "recommendation_request";

    const modelPlan =
      payload.mode === "single_model"
        ? [
            {
              model_id: payload.selectedModel || "minicpm3_4b_local",
              model_name:
                payload.selectedModel === "medgemma_local"
                  ? "MedGemma 4B（本地）"
                  : payload.selectedModel === "minicpm3_4b_local"
                  ? "MiniCPM3-4B（本地中文）"
                  : payload.selectedModel === "qwen2_5_3b_local"
                  ? "Qwen2.5-3B（本地轻量）"
                  : payload.selectedModel === "qwen3_8b_local"
                  ? "Qwen3-8B（规划/工具调用）"
                  : payload.selectedModel === "deepseek_r1_qwen_7b_local"
                  ? "DeepSeek-R1-Distill-Qwen-7B（复杂推理）"
                  : "MiniCPM3-4B（本地中文）",
              role: "直接回答",
              task: "按单模型策略问答",
              enabled: true,
            },
          ]
        : [
            {
              model_id: "care-planner",
              model_name: "处理顺序整理",
              role: "顺序整理",
              task: "把当前情况拆成先做、后做和谁来确认",
              enabled: true,
            },
            {
              model_id: "qwen3-8b-local-planner",
              model_name: "下一步安排",
              role: "梳理先后",
              task: "补齐漏掉的步骤，告诉你先做什么后做什么",
              enabled: true,
            },
            {
              model_id: "deepseek-r1-local",
              model_name: "重点再看一遍",
              role: "再核对",
              task: "对复杂情况再看一遍，避免遗漏",
              enabled: true,
            },
            {
              model_id: "minicpm3-4b-local-main",
              model_name: "当前回复整理（本地）",
              role: "整理重点",
              task: "理解提问、整理重点并生成护士能直接看的说明",
              enabled: true,
            },
            {
              model_id: "minicpm3-4b-local",
              model_name: "快速回答（本地）",
              role: "快速回答",
              task: "把问题先整理成护士能直接使用的说明",
              enabled: true,
            },
            { model_id: "funasr-local", model_name: "语音转文字", role: "转成文字", task: "把语音内容整理成文字", enabled: true },
            {
              model_id: "medgemma-local",
              model_name: "附件读取",
              role: "附件查看",
              task: "查看图片、PDF 和检查报告附件",
              enabled: Boolean((payload.attachments || []).length),
            },
            { model_id: "cosyvoice-local", model_name: "结果播报", role: "语音播报", task: "语音播报", enabled: true },
          ];

    const plan = buildAgentPlan({
      mode: payload.mode,
      userInput: plannerText || payload.userInput,
      attachments: payload.attachments,
      executionProfile: payload.executionProfile,
    });
    const memory = buildAgentMemory(patientId, plannerText || payload.userInput, profile);
    const artifacts = buildAgentArtifacts(patientId, plannerText || payload.userInput, plan);
    const steps = buildAgentSteps({
      mode: payload.mode,
      selectedModel: payload.selectedModel,
      modelPlan,
      plan,
      artifacts,
    });
    const nextActions = dynamic.recommendations.map((item) => item.title).slice(0, 4);
    const structured = buildStructuredAgentView({
      patientId,
      bedNo: payload.bedNo,
      missionTitle: payload.missionTitle,
      summary: withMissionSummary(dynamic.summary, payload.missionTitle),
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      memory,
      artifacts,
      nextActions,
      executionProfile: profile,
    });

    const response: AIChatResponse = {
      mode: payload.mode,
      selected_model: payload.mode === "single_model" ? payload.selectedModel || "minicpm3_4b_local" : "minicpm3_4b_local",
      cluster_profile: payload.mode === "agent_cluster" ? payload.clusterProfile || "nursing_default_cluster" : undefined,
      conversation_id: payload.conversationId,
      run_id: `run-${Date.now()}`,
      runtime_engine: buildRuntimeStatus().active_engine,
      workflow_type: workflowType,
      summary: withMissionSummary(dynamic.summary, payload.missionTitle),
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      confidence: payload.mode === "single_model" ? 0.75 : 0.84,
      review_required: true,
      steps,
      model_plan: modelPlan,
      agent_goal:
        payload.missionTitle
          ? `围绕${mockContexts[patientId]?.bed_no || payload.bedNo || "-"}床推进任务「${payload.missionTitle}」`
          : payload.mode === "single_model"
          ? `用单模型直接回答${mockContexts[patientId]?.bed_no || payload.bedNo || "-"}床问题`
          : `围绕${mockContexts[patientId]?.bed_no || payload.bedNo || "-"}床执行${EXECUTION_PROFILE_LABELS[profile]}任务`,
      agent_mode:
        payload.mode === "single_model"
          ? "direct_answer"
          : payload.agentMode || profile === "full_loop" || /自动|闭环|自治/.test(payload.userInput)
          ? "autonomous"
          : "assisted",
      execution_profile: profile,
      mission_title: payload.missionTitle,
      success_criteria: payload.successCriteria || [],
      plan,
      memory,
      artifacts,
      specialist_profiles: structured.specialist_profiles,
      hybrid_care_path: structured.hybrid_care_path,
      data_capsule: structured.data_capsule,
      health_graph: structured.health_graph,
      reasoning_cards: structured.reasoning_cards,
      pending_approvals: [],
      next_actions: nextActions,
      created_at: new Date().toISOString(),
    };

    pushConversationHistory({
      id: `ai_${Date.now()}`,
      source: "agent-orchestrator",
      workflow_type: response.workflow_type,
      patient_id: patientId,
      conversation_id: payload.conversationId,
      user_input: payload.userInput,
      summary: response.summary,
      created_at: response.created_at,
      confidence: response.confidence,
      review_required: response.review_required,
      run_id: response.run_id,
      runtime_engine: response.runtime_engine,
      findings: response.findings,
      recommendations: response.recommendations,
      steps: response.steps,
      agent_goal: response.agent_goal,
      agent_mode: response.agent_mode,
      execution_profile: response.execution_profile,
      mission_title: response.mission_title,
      success_criteria: response.success_criteria,
      plan: response.plan,
      memory: response.memory,
      artifacts: response.artifacts,
      specialist_profiles: response.specialist_profiles,
      hybrid_care_path: response.hybrid_care_path,
      data_capsule: response.data_capsule,
      health_graph: response.health_graph,
      reasoning_cards: response.reasoning_cards,
      pending_approvals: response.pending_approvals,
      next_actions: response.next_actions,
    });
    return response;
  },

  async analyzeMultimodal(
    patientId: string,
    inputRefs: string[],
    question?: string
  ): Promise<MultimodalAnalysisResult> {
    await sleep(550);
    return {
      patient_id: patientId,
      summary: `已接收${inputRefs.length}个多模态附件${question ? `，问题：${question}` : ""}。`,
      findings: inputRefs.map((item) => `附件：${item.slice(0, 48)}${item.length > 48 ? "..." : ""}`),
      recommendations: [{ title: "请结合临床数据进行人工复核", priority: 1 }],
      confidence: 0.73,
      review_required: true,
      created_at: new Date().toISOString(),
    };
  },

  async runVoiceWorkflow(question: string) {
    await sleep(550);
    const dynamic = dynamicSummary(question);
    const plan = buildAgentPlan({ mode: "agent_cluster", userInput: question, attachments: [] });
    const memory = buildAgentMemory("pat-001", question);
    const artifacts = buildAgentArtifacts("pat-001", question, plan);
    const steps = buildAgentSteps({
      mode: "agent_cluster",
      modelPlan: [],
      plan,
      artifacts,
    });
    const nextActions = dynamic.recommendations.map((item) => item.title).slice(0, 4);
    const structured = buildStructuredAgentView({
      patientId: "pat-001",
      summary: dynamic.summary,
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      memory,
      artifacts,
      nextActions,
      executionProfile: "observe",
    });
    const result = {
      summary: dynamic.summary,
      findings: dynamic.findings,
      recommendations: dynamic.recommendations,
      confidence: 0.83,
      review_required: true,
    };
    pushConversationHistory({
      id: `wf_${Date.now()}`,
      source: "agent-orchestrator",
      workflow_type: "voice_inquiry",
      patient_id: "pat-001",
      user_input: question,
      summary: result.summary,
      created_at: new Date().toISOString(),
      confidence: result.confidence,
      review_required: result.review_required,
      findings: result.findings,
      recommendations: result.recommendations,
      steps,
      agent_goal: "完成床旁语音问询并生成护理建议",
      agent_mode: "voice_assisted",
      plan,
      memory,
      artifacts,
      specialist_profiles: structured.specialist_profiles,
      hybrid_care_path: structured.hybrid_care_path,
      data_capsule: structured.data_capsule,
      health_graph: structured.health_graph,
      reasoning_cards: structured.reasoning_cards,
      next_actions: nextActions,
    });
    return result;
  },

  async getConversationHistory(
    patientId: string,
    limit = 30,
    conversationId?: string
  ): Promise<ConversationHistoryItem[]> {
    await sleep(220);
    return mockConversationHistory
      .filter((item) => item.patient_id === patientId)
      .filter((item) => !conversationId || item.conversation_id === conversationId)
      .slice(0, limit);
  },

  async createDocumentDraft(
    patientId: string,
    text: string,
    options?: { templateId?: string; templateText?: string; templateName?: string }
  ): Promise<DocumentDraft> {
    await sleep(650);
    const chosenTemplate = mockTemplates.find((item) => item.id === options?.templateId) || null;
    const templateText = options?.templateText || chosenTemplate?.template_text || "";
    const templateName = options?.templateName || chosenTemplate?.name || "默认模板";
    const spoken = text || "患者病情平稳，继续观察。";

    const rendered = templateText
      ? templateText
          .replace("{{patient_id}}", patientId)
          .replace("{{bed_no}}", mockContexts[patientId]?.bed_no || "-")
          .replace("{{diagnoses}}", (mockContexts[patientId]?.diagnoses || []).join("、"))
          .replace("{{risk_tags}}", (mockContexts[patientId]?.risk_tags || []).join("、"))
          .replace("{{pending_tasks}}", (mockContexts[patientId]?.pending_tasks || []).join("、"))
          .replace("{{spoken_text}}", spoken)
      : `[护理记录]\n患者ID: ${patientId}\n内容: ${spoken}`;

    const item: DocumentDraft = {
      id: `draft_${Date.now()}`,
      patient_id: patientId,
      document_type: "nursing_note",
      draft_text: `${rendered}\nAI提示: 需人工复核。`,
      status: "draft",
      structured_fields: {
        template_name: templateName,
        template_applied: Boolean(templateText || chosenTemplate),
      },
      updated_at: new Date().toISOString(),
    };
    mockDrafts.unshift(item);
    updateDocumentSync(patientId, item.status, item.updated_at, item.draft_text.slice(0, 70));
    pushConversationHistory({
      id: item.id,
      source: "document-service",
      workflow_type: "document_generation",
      patient_id: patientId,
      user_input: String(item.structured_fields?.template_name || ""),
      summary: item.draft_text.slice(0, 120),
      created_at: item.updated_at,
      review_required: true,
    });
    return item;
  },

  async importDocumentTemplate(payload: {
    name?: string;
    templateText?: string;
    templateBase64?: string;
    fileName?: string;
  }): Promise<DocumentTemplate> {
    await sleep(300);
    let templateText = payload.templateText || "";
    if (!templateText && payload.templateBase64) {
      templateText = "[Mock模板] 已接收Base64模板内容。";
    }
    const item: DocumentTemplate = {
      id: `tpl_${Date.now()}`,
      name: payload.name || payload.fileName || "导入模板",
      source_type: "import",
      template_text: templateText,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    mockTemplates.unshift(item);
    return item;
  },

  async listDocumentTemplates(): Promise<DocumentTemplate[]> {
    await sleep(250);
    return mockTemplates;
  },

  async listDrafts(patientId: string) {
    await sleep(300);
    return mockDrafts.filter((item) => item.patient_id === patientId);
  },

  async reviewDraft(draftId: string) {
    await sleep(220);
    const found = mockDrafts.find((item) => item.id === draftId);
    if (!found) {
      throw new Error("draft_not_found");
    }
    found.status = "reviewed";
    found.updated_at = new Date().toISOString();
    updateDocumentSync(found.patient_id, found.status, found.updated_at, found.draft_text.slice(0, 70));
    return found;
  },

  async updateDraft(draftId: string, draftText: string, editedBy?: string) {
    await sleep(220);
    const found = mockDrafts.find((item) => item.id === draftId);
    if (!found) {
      throw new Error("draft_not_found");
    }
    found.draft_text = draftText || found.draft_text;
    found.status = "draft";
    found.updated_at = new Date().toISOString();
    found.structured_fields = {
      ...(found.structured_fields || {}),
      manual_edited: true,
      edited_by: editedBy || null,
    };
    updateDocumentSync(found.patient_id, found.status, found.updated_at, found.draft_text.slice(0, 70));
    return found;
  },

  async submitDraft(draftId: string) {
    await sleep(220);
    const found = mockDrafts.find((item) => item.id === draftId);
    if (!found) {
      throw new Error("draft_not_found");
    }
    found.status = "submitted";
    found.updated_at = new Date().toISOString();
    updateDocumentSync(found.patient_id, found.status, found.updated_at, found.draft_text.slice(0, 70));
    return found;
  },

  async editDraft(draftId: string, draftText: string, editedBy?: string) {
    await sleep(220);
    const found = mockDrafts.find((item) => item.id === draftId);
    if (!found) {
      throw new Error("draft_not_found");
    }
    found.draft_text = draftText;
    found.status = "draft";
    found.updated_at = new Date().toISOString();
    found.structured_fields = {
      ...(found.structured_fields || {}),
      manual_edited: true,
      edited_by: editedBy || "unknown",
      edited_at: found.updated_at,
    };
    updateDocumentSync(found.patient_id, found.status, found.updated_at, found.draft_text.slice(0, 70));
    pushConversationHistory({
      id: `doc_edit_${Date.now()}`,
      source: "document-service",
      workflow_type: "document_edit",
      patient_id: found.patient_id,
      user_input: "manual_edit",
      summary: found.draft_text.slice(0, 120),
      created_at: found.updated_at,
      review_required: true,
    });
    return found;
  },

  async createThread(patientId: string, title: string, createdBy: string) {
    await sleep(300);
    mockThread = {
      id: `thread_${Date.now()}`,
      patient_id: patientId,
      thread_type: "discussion",
      title,
      created_by: createdBy,
      status: "open",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    pushConversationHistory({
      id: mockThread.id,
      source: "collaboration-service",
      workflow_type: "collaboration",
      patient_id: patientId,
      user_input: title,
      summary: "会话已创建",
      created_at: mockThread.updated_at,
      review_required: false,
    });
    return mockThread;
  },

  async sendMessage(threadId: string, content: string, senderId: string) {
    await sleep(200);
    const msg = {
      id: `msg_${Date.now()}`,
      thread_id: threadId,
      content,
      sender_id: senderId,
      message_type: "text",
      attachment_refs: [],
      ai_generated: false,
      created_at: new Date().toISOString(),
    };
    mockMessages.push(msg);
    if (mockThread && mockThread.id === threadId) {
      mockThread.updated_at = msg.created_at;
      pushConversationHistory({
        id: msg.id,
        source: "collaboration-service",
        workflow_type: "collaboration",
        patient_id: mockThread.patient_id,
        user_input: mockThread.title,
        summary: content,
        created_at: msg.created_at,
        review_required: false,
      });
    }
    return msg;
  },

  async getThread(threadId: string) {
    await sleep(200);
    return {
      thread:
        mockThread ||
        {
          id: threadId,
          patient_id: "pat-001",
          thread_type: "discussion",
          title: "Mock thread",
          status: "open",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      messages: mockMessages.filter((item) => item.thread_id === threadId),
      metadata: { message_count: mockMessages.filter((item) => item.thread_id === threadId).length },
    };
  },

  async getCollabHistory(patientId: string, limit = 50): Promise<CollaborationThreadHistoryItem[]> {
    await sleep(200);
    if (!mockThread || mockThread.patient_id !== patientId) {
      return [];
    }
    const messages = mockMessages.filter((item) => item.thread_id === mockThread.id);
    const latest = messages.length ? messages[messages.length - 1] : null;
    return [
      {
        thread: mockThread,
        latest_message: latest,
        message_count: messages.length,
      },
    ].slice(0, limit);
  },

  async searchCollabAccounts(query: string, excludeUserId?: string) {
    await sleep(120);
    const q = (query || "").trim().toLowerCase();
    return mockAccounts
      .filter((item) => (!excludeUserId ? true : item.id !== excludeUserId))
      .filter((item) => {
        if (!q) return true;
        return `${item.account} ${item.full_name} ${item.role_code}`.toLowerCase().includes(q);
      });
  },

  async getCollabContacts(userId: string) {
    await sleep(120);
    const ids = mockContacts[userId] || [];
    return {
      user_id: userId,
      contacts: mockAccounts.filter((item) => ids.includes(item.id)),
    };
  },

  async addCollabContact(userId: string, account: string) {
    await sleep(120);
    const target = mockAccounts.find((item) => item.account === account || item.id === account);
    if (!target) {
      throw new Error("account_not_found");
    }
    const curr = new Set(mockContacts[userId] || []);
    curr.add(target.id);
    mockContacts[userId] = Array.from(curr);
    return target;
  },

  async listDirectSessions(userId: string) {
    await sleep(120);
    return mockDirectSessions.filter((item) => item.user_id === userId || item.contact_user_id === userId);
  },

  async openDirectSession(payload: { userId: string; contactUserId: string; patientId?: string }) {
    await sleep(150);
    const exists = mockDirectSessions.find(
      (item) =>
        (item.user_id === payload.userId && item.contact_user_id === payload.contactUserId) ||
        (item.user_id === payload.contactUserId && item.contact_user_id === payload.userId)
    );
    if (exists) {
      return exists;
    }
    const contact = mockAccounts.find((item) => item.id === payload.contactUserId) || null;
    const session = {
      id: `ds-${Date.now()}`,
      user_id: payload.userId,
      contact_user_id: payload.contactUserId,
      patient_id: payload.patientId,
      status: "open",
      created_at: nowIso(),
      updated_at: nowIso(),
      latest_message: null,
      unread_count: 0,
      contact,
    };
    mockDirectSessions.unshift(session);
    return session;
  },

  async sendDirectMessage(payload: {
    sessionId: string;
    senderId: string;
    content: string;
    messageType?: string;
    attachmentRefs?: string[];
  }) {
    await sleep(120);
    const msg = {
      id: `dm-${Date.now()}`,
      thread_id: payload.sessionId,
      sender_id: payload.senderId,
      message_type: payload.messageType || "text",
      content: payload.content,
      attachment_refs: payload.attachmentRefs || [],
      ai_generated: payload.senderId === "ai-assistant",
      created_at: nowIso(),
    };
    mockDirectMessages.push(msg);
    const session = mockDirectSessions.find((item) => item.id === payload.sessionId);
    if (session) {
      session.latest_message = msg;
      session.updated_at = msg.created_at;
    }
  },

  async getDirectSessionDetail(sessionId: string, userId: string) {
    await sleep(120);
    const session = mockDirectSessions.find((item) => item.id === sessionId);
    if (!session) {
      throw new Error("direct_session_not_found");
    }
    if (session.user_id !== userId && session.contact_user_id !== userId) {
      throw new Error("permission_denied");
    }
    const messages = mockDirectMessages.filter((item) => item.thread_id === sessionId);
    return { session, messages };
  },

  async runAssistantDigest(payload: { userId: string; patientId: string; note?: string }) {
    await sleep(180);
    const patient = mockPatients[payload.patientId];
    const context = mockContexts[payload.patientId];
    const summary = `${context?.bed_no || "-"}床任务整理：${context?.risk_tags?.slice(0, 2).join("、") || "暂无高风险"}。${
      payload.note ? ` 备注：${payload.note}` : ""
    }`;
    return {
      summary,
      tasks: [
        "立即复测生命体征并确认趋势",
        "核对关键医嘱执行状态",
        "补录护理文书并完成交接班提醒",
      ],
      suggestions: ["先处理P1，再处理P2", "异常项先上报医生，再补写记录", "发送会诊消息时附上关键指标"],
      generated_message: `[AI值班助理] 请协助核对 ${patient?.full_name || payload.patientId} 的高风险医嘱与交接要点。`,
    };
  },
};



