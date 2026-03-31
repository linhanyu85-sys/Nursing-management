import React, { useEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system";
import { useNavigation } from "@react-navigation/native";

import { api, getApiErrorMessage } from "../api/endpoints";
import { subscribePatientContext, subscribeWardBeds } from "../api/realtime";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { VoiceTextInput } from "../components/VoiceTextInput";
import { ActionButton, AnimatedBlock, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors, radius } from "../theme";
import { formatAiText } from "../utils/text";
import type {
  AIChatResponse,
  AIChatMessage,
  AIChatMode,
  AIClusterProfile,
  AIExecutionProfile,
  AIModelOption,
  AIModelTask,
  AIRuntimeStatus,
  AgentQueueTask,
  AgentRunRecord,
  BedOverview,
  CareGraphSnapshot,
  ConversationHistoryItem,
  OrderListOut,
  PatientContext,
  PatientStateCapsule,
  ReasoningCheckpoint,
  RoleLane,
  ServiceRelayStage,
} from "../types";

const MODE_LABEL: Record<AIChatMode, string> = {
  single_model: "快速回答",
  agent_cluster: "系统协同",
};

const EXECUTION_PROFILE_META: Record<
  AIExecutionProfile,
  {
    label: string;
    summary: string;
    queueWorkflow: string;
    agentMode: string;
  }
> = {
  observe: {
    label: "快速梳理",
    summary: "优先抓当前风险、异常体征和接下来30分钟观察重点，适合先看清局势。",
    queueWorkflow: "voice_inquiry",
    agentMode: "assisted",
  },
  escalate: {
    label: "沟通上报",
    summary: "先整理上报依据和沟通摘要，方便和值班医生快速对齐。",
    queueWorkflow: "recommendation_request",
    agentMode: "assisted",
  },
  document: {
    label: "整理记录",
    summary: "先生成护理记录和交班草稿，方便人工核对后留痕。",
    queueWorkflow: "document_generation",
    agentMode: "assisted",
  },
  full_loop: {
    label: "持续跟进",
    summary: "系统会连续推进判断、提醒、沟通和留痕；涉及敏感动作时会停下来等你确认。",
    queueWorkflow: "autonomous_care",
    agentMode: "autonomous",
  },
};

const WORKFLOW_LABEL: Record<string, string> = {
  single_model_chat: "快速回答",
  recommendation_request: "沟通建议",
  autonomous_care: "持续跟进",
  voice_inquiry: "快速梳理",
  handover_generate: "交班草稿",
  document_generation: "护理文书",
};

const AGENT_MODE_LABEL: Record<string, string> = {
  workflow: "按固定流程",
  assisted: "辅助处理",
  autonomous: "持续跟进",
  direct_answer: "即时回答",
  voice_assisted: "语音辅助",
};

const ENGINE_LABEL: Record<string, string> = {
  state_machine: "标准流程",
  langgraph: "深度分析",
};

const PLAN_STATUS_LABEL: Record<string, string> = {
  done: "完成",
  pending: "待执行",
  skipped: "跳过",
  failed: "失败",
  approval_required: "待审批",
  rejected: "已拒绝",
};

const QUEUE_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  waiting_approval: "待审批",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const QUEUE_FILTER_LABEL: Record<string, string> = {
  all: "全部",
  waiting_approval: "待审批",
  running: "执行中",
  completed: "已完成",
};

const APPROVAL_TOOL_LABEL: Record<string, string> = {
  fetch_orders: "补看医嘱",
  recommend: "生成处理建议",
  create_document: "生成护理文书",
  create_handover: "生成交班草稿",
  request_order: "生成待确认医嘱请求",
  send_collaboration: "联系医生协作",
};

function formatExecutionProfileLabel(profile?: string): string {
  const key = String(profile || "").toLowerCase() as AIExecutionProfile;
  return EXECUTION_PROFILE_META[key]?.label || "快速梳理";
}

function executionProfileTone(profile?: string): "info" | "success" | "warning" | "danger" {
  if (profile === "full_loop") {
    return "danger";
  }
  if (profile === "document") {
    return "success";
  }
  if (profile === "escalate") {
    return "warning";
  }
  return "info";
}

const MODEL_FALLBACK: Record<string, { name: string; description: string }> = {
  minicpm3_4b_local: {
    name: "基础整理（本地）",
    description: "适合快速整理当前问题和生成床旁说明",
  },
  qwen2_5_3b_local: {
    name: "轻量回答（本地）",
    description: "适合低资源环境下做快速回答",
  },
  qwen3_8b_local: {
    name: "下一步提醒（本地）",
    description: "适合把先做什么、后做什么整理清楚",
  },
  deepseek_r1_qwen_7b_local: {
    name: "重点复看（本地）",
    description: "适合对复杂情况再看一遍，避免遗漏",
  },
  bailian_main: {
    name: "云端综合回答",
    description: "当本地回答不够时补充分析",
  },
  medgemma_local: {
    name: "附件查看（本地）",
    description: "适合查看图片、报告和病历附件",
  },
  qwen_light: {
    name: "云端补充回答",
    description: "适合快速补充短回答",
  },
};

const CLUSTER_FALLBACK: Record<string, string> = {
  nursing_default_cluster: "系统协同",
};

const TASK_FALLBACK: Record<string, { modelName: string; role: string; task: string }> = {
  "care-planner": {
    modelName: "处理顺序整理",
    role: "顺序整理",
    task: "把当前情况拆成先做、后做和谁来确认",
  },
  "qwen3-8b-local-planner": {
    modelName: "处理顺序补齐",
    role: "顺序整理",
    task: "补齐漏掉的步骤和先后顺序",
  },
  "deepseek-r1-local": {
    modelName: "重点再核对",
    role: "再核对",
    task: "对复杂情况再看一遍，避免遗漏",
  },
  "minicpm3-4b-local-main": {
    modelName: "床旁说明生成",
    role: "主说明",
    task: "理解提问、汇总重点并生成床旁说明",
  },
  "funasr-local": {
    modelName: "语音转文字",
    role: "语音转文字",
    task: "把录音整理成文字",
  },
  "medgemma-local": {
    modelName: "附件内容整理",
    role: "附件查看",
    task: "查看图片、PDF 和检查报告附件",
  },
  "minicpm3-4b-local": {
    modelName: "快速整理回答",
    role: "快速回答",
    task: "把问题先整理成护士能直接使用的说明",
  },
  "cosyvoice-local": {
    modelName: "结果播报",
    role: "语音播报",
    task: "把结果读出来",
  },
};

const DEFAULT_MODEL_OPTIONS: AIModelOption[] = Object.entries(MODEL_FALLBACK).map(([id, item]) => ({
  id,
  name: item.name,
  provider: id.includes("local") ? "local" : "bailian",
  description: item.description,
}));

const DEFAULT_CLUSTER_PROFILES: AIClusterProfile[] = [
  {
    id: "nursing_default_cluster",
    name: "系统协同",
    main_model: "基础整理（本地）",
    description: "系统会先整理重点，再排处理顺序；遇到复杂情况时再做一轮核对。",
    tasks: Object.entries(TASK_FALLBACK).map(([modelId, task]) => ({
      model_id: modelId,
      model_name: task.modelName,
      role: task.role,
      task: task.task,
      enabled: modelId !== "medgemma-local",
    })),
  },
];

type ConversationFolder = {
  id: string;
  title: string;
  latestAt: string;
  count: number;
};

type WorkspaceView = "result" | "queue" | "runs" | "history" | "system";

type InputEngineOption = {
  key: string;
  label: string;
  detail: string;
  mode: AIChatMode;
  modelId?: string;
};

function extractBedNo(input: string): string | undefined {
  const text = input || "";
  const direct = text.match(/(\d{1,3})\s*(床|号床|床位)/);
  if (direct?.[1]) {
    return direct[1];
  }
  const fallback = text.match(/^\s*(\d{1,3})(?=\D|$)/);
  return fallback?.[1];
}

function getConversationKey(item: ConversationHistoryItem): string {
  return item.conversation_id?.trim() || "legacy-default";
}

function buildConversationFolders(items: ConversationHistoryItem[]): ConversationFolder[] {
  const source = [...items].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const folders: ConversationFolder[] = [];
  const indexMap: Record<string, number> = {};
  const titleMap: Record<string, string> = {};

  source.forEach((item) => {
    const key = getConversationKey(item);
    const ts = item.created_at || new Date().toISOString();
    const trimmedInput = formatAiText(item.user_input || "").replace(/\s+/g, " ").trim();
    if (!titleMap[key]) {
      if (key === "legacy-default") {
        titleMap[key] = "历史会话";
      } else if (trimmedInput) {
        titleMap[key] = trimmedInput.slice(0, 14);
      } else {
        titleMap[key] = `新对话-${folders.length + 1}`;
      }
    }

    if (indexMap[key] === undefined) {
      indexMap[key] = folders.length;
      folders.push({
        id: key,
        title: titleMap[key],
        latestAt: ts,
        count: 1,
      });
      return;
    }

    const target = folders[indexMap[key]];
    target.count += 1;
    if (new Date(ts).getTime() > new Date(target.latestAt).getTime()) {
      target.latestAt = ts;
    }
  });

  return folders.sort((a, b) => new Date(b.latestAt).getTime() - new Date(a.latestAt).getTime());
}

function toMessageMode(item: ConversationHistoryItem): AIChatMode {
  return item.workflow_type === "single_model_chat" ? "single_model" : "agent_cluster";
}

function formatWorkflowLabel(workflowType?: string): string {
  const key = String(workflowType || "");
  return WORKFLOW_LABEL[key] || key || "未知流程";
}

function formatAgentModeLabel(agentMode?: string): string {
  const key = String(agentMode || "");
  return AGENT_MODE_LABEL[key] || key || "工作流";
}

function formatEngineLabel(engine?: string): string {
  const key = String(engine || "");
  return ENGINE_LABEL[key] || key || "稳定模式";
}

function formatPlanStatus(status?: string): string {
  const key = String(status || "");
  return PLAN_STATUS_LABEL[key] || key || "待执行";
}

function planStatusTone(status?: string): "info" | "success" | "warning" | "danger" {
  if (status === "done") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "skipped") {
    return "info";
  }
  if (status === "rejected" || status === "approval_required") {
    return "warning";
  }
  return "warning";
}

function formatQueueStatus(status?: string): string {
  const key = String(status || "");
  return QUEUE_STATUS_LABEL[key] || key || "排队中";
}

function formatApprovalToolLabel(tool?: string): string {
  const key = String(tool || "");
  return APPROVAL_TOOL_LABEL[key] || key || "系统动作";
}

const STEP_AGENT_LABEL: Record<string, string> = {
  "Planner Agent": "处理顺序整理",
  "Memory Agent": "历史回看",
  "Patient Context Agent": "病例信息整理",
  "Order Signal Agent": "医嘱核对",
  "Recommendation Agent": "处理建议整理",
  "Collaboration Agent": "医生沟通",
  "Handover Agent": "交班草稿整理",
  "Document Agent": "护理记录整理",
  "Order Request Agent": "医嘱请求整理",
  "Action Agent": "结果汇总",
  "Intent Router Agent": "问题识别",
  "Care Memory Agent": "历史回看",
  "Single Model Runner": "直接回答",
  "Tool Runner Agent": "工具执行",
  "Audit Agent": "留痕记录",
  "Queue Worker": "后台持续处理",
  "Approval Gate": "人工确认",
  "Retry Runner": "重新发起",
  planner_agent: "处理顺序整理",
  care_memory_agent: "历史回看",
  patient_context_agent: "病例信息整理",
  fetch_orders_agent: "补看医嘱",
  recommend_agent: "处理建议整理",
  create_document_agent: "护理记录整理",
  create_handover_agent: "交班草稿整理",
  request_order_agent: "医嘱请求整理",
  send_collaboration_agent: "联系医生",
};

function formatStepAgentLabel(agent?: string): string {
  const key = String(agent || "");
  return STEP_AGENT_LABEL[key] || key || "系统步骤";
}

function queueStatusTone(status?: string): "info" | "success" | "warning" | "danger" {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed" || status === "cancelled") {
    return "danger";
  }
  if (status === "waiting_approval") {
    return "warning";
  }
  return "info";
}

function formatRoleLaneStatus(status?: string): string {
  const value = String(status || "active").toLowerCase();
  if (value === "done" || value === "completed") {
    return "已完成";
  }
  if (value === "approval_required" || value === "waiting_approval") {
    return "待审批";
  }
  if (value === "handoff") {
    return "待接力";
  }
  if (value === "watch") {
    return "观察中";
  }
  if (value === "ready") {
    return "已就绪";
  }
  if (value === "rejected" || value === "blocked") {
    return "已阻塞";
  }
  return "推进中";
}

function roleLaneTone(status?: string): "info" | "success" | "warning" | "danger" {
  const value = String(status || "active").toLowerCase();
  if (value === "done" || value === "completed") {
    return "success";
  }
  if (value === "approval_required" || value === "waiting_approval" || value === "watch" || value === "handoff") {
    return "warning";
  }
  if (value === "rejected" || value === "blocked") {
    return "danger";
  }
  return "info";
}

function formatRelayStageStatus(status?: string): string {
  const value = String(status || "pending").toLowerCase();
  if (value === "done" || value === "completed") {
    return "已完成";
  }
  if (value === "approval_required" || value === "waiting_approval") {
    return "待确认";
  }
  if (value === "ready") {
    return "可执行";
  }
  if (value === "running" || value === "active") {
    return "进行中";
  }
  if (value === "blocked" || value === "rejected") {
    return "受阻";
  }
  return "待推进";
}

function relayStageTone(status?: string): "info" | "success" | "warning" | "danger" {
  const value = String(status || "pending").toLowerCase();
  if (value === "done" || value === "completed") {
    return "success";
  }
  if (value === "approval_required" || value === "waiting_approval" || value === "pending") {
    return "warning";
  }
  if (value === "blocked" || value === "rejected") {
    return "danger";
  }
  return "info";
}

function formatReasoningMode(mode?: string): string {
  const value = String(mode || "").toLowerCase();
  if (value === "scan") {
    return "先看风险";
  }
  if (value === "reverse_check") {
    return "反向再核对";
  }
  if (value === "align") {
    return "核对动作";
  }
  if (value === "escalate") {
    return "判断要不要上报";
  }
  if (value === "review") {
    return "说明为什么这样建议";
  }
  return "核对节点";
}

function hasMemoryContent(memory?: AIChatResponse["memory"]): boolean {
  return Boolean(
    memory &&
      (memory.conversation_summary ||
        memory.patient_facts.length ||
        memory.unresolved_tasks.length ||
        memory.last_actions.length ||
        memory.user_preferences.length)
  );
}

function buildHistoryResponse(item: ConversationHistoryItem): AIChatResponse {
  const mode = toMessageMode(item);
  const modelPlan =
    mode === "agent_cluster"
      ? DEFAULT_CLUSTER_PROFILES[0]?.tasks || []
      : [
          {
            model_id: "minicpm3_4b_local",
            model_name: MODEL_FALLBACK.minicpm3_4b_local.name,
            role: "直接回答",
            task: "按单模型策略问答",
            enabled: true,
          },
    ];
  return {
    mode,
    selected_model: mode === "single_model" ? "minicpm3_4b_local" : undefined,
    cluster_profile: mode === "agent_cluster" ? "nursing_default_cluster" : undefined,
    conversation_id: item.conversation_id,
    run_id: item.run_id,
    runtime_engine: item.runtime_engine,
    workflow_type: item.workflow_type,
    summary: item.summary,
    findings: item.findings || [],
    recommendations: item.recommendations || [],
    confidence: item.confidence ?? 0,
    review_required: item.review_required ?? true,
    steps: item.steps || [],
    model_plan: modelPlan,
    agent_goal: item.agent_goal,
    agent_mode: item.agent_mode || "workflow",
    execution_profile: item.execution_profile,
    mission_title: item.mission_title,
    success_criteria: item.success_criteria || [],
    plan: item.plan || [],
    memory: item.memory,
    artifacts: item.artifacts || [],
    specialist_profiles: item.specialist_profiles || [],
    hybrid_care_path: item.hybrid_care_path || [],
    data_capsule: item.data_capsule,
    health_graph: item.health_graph,
    reasoning_cards: item.reasoning_cards || [],
    pending_approvals: item.pending_approvals || [],
    next_actions: item.next_actions || [],
    created_at: item.created_at,
  };
}

function historyToMessages(items: ConversationHistoryItem[]): AIChatMessage[] {
  return [...items]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .flatMap((item) => {
      const rows: AIChatMessage[] = [];
      const mode = toMessageMode(item);
      if (item.user_input) {
        rows.push({
          id: `u-${item.id}`,
          role: "user",
          mode,
          text: formatAiText(item.user_input),
          timestamp: item.created_at,
        });
      }
      rows.push({
        id: `a-${item.id}`,
        role: "assistant",
        mode,
        text: formatAiText(item.summary),
        timestamp: item.created_at,
        response: buildHistoryResponse(item),
      });
      return rows;
    });
}

function StructuredAgentPanels({
  specialistProfiles,
  hybridCarePath,
  dataCapsule,
  healthGraph,
  reasoningCards,
}: {
  specialistProfiles?: RoleLane[];
  hybridCarePath?: ServiceRelayStage[];
  dataCapsule?: PatientStateCapsule;
  healthGraph?: CareGraphSnapshot;
  reasoningCards?: ReasoningCheckpoint[];
}) {
  const roleItems = specialistProfiles || [];
  const relayItems = hybridCarePath || [];
  const reasoningItems = reasoningCards || [];

  if (!roleItems.length && !relayItems.length && !dataCapsule && !healthGraph && !reasoningItems.length) {
    return null;
  }

  return (
    <>
      {roleItems.length ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>本次由谁分工</Text>
          {roleItems.map((item) => (
            <View key={item.id} style={styles.matrixItem}>
              <View style={styles.matrixHead}>
                <Text style={styles.matrixTitle}>{formatAiText(item.title)}</Text>
                <StatusPill text={formatRoleLaneStatus(item.status)} tone={roleLaneTone(item.status)} />
              </View>
              <Text style={styles.matrixMeta}>{formatAiText(item.role)}</Text>
              <Text style={styles.matrixFocus}>{formatAiText(item.focus)}</Text>
              {item.reason ? <Text style={styles.matrixHint}>为什么由它处理：{formatAiText(item.reason)}</Text> : null}
              {item.next_action ? <Text style={styles.matrixHint}>下一步接给：{formatAiText(item.next_action)}</Text> : null}
            </View>
          ))}
        </View>
      ) : null}

      {relayItems.length ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>处理接力顺序</Text>
          <View style={styles.relayRail}>
            {relayItems.map((item) => (
              <View key={item.id} style={styles.relayItem}>
                <View style={styles.matrixHead}>
                  <Text style={styles.matrixTitle}>{formatAiText(item.title)}</Text>
                  <StatusPill text={formatRelayStageStatus(item.status)} tone={relayStageTone(item.status)} />
                </View>
                <Text style={styles.relayOwner}>{formatAiText(item.owner)}</Text>
                {item.summary ? <Text style={styles.matrixHint}>{formatAiText(item.summary)}</Text> : null}
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {dataCapsule ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>当前病人重点</Text>
          <View style={styles.capsuleGrid}>
            <View style={styles.capsuleCard}>
              <Text style={styles.capsuleCardTitle}>当前情况</Text>
              {dataCapsule.event_summary.slice(0, 4).map((item, index) => (
                <Text key={`event-${index}`} style={styles.capsuleText}>
                  {formatAiText(item)}
                </Text>
              ))}
            </View>
            <View style={styles.capsuleCard}>
              <Text style={styles.capsuleCardTitle}>风险提醒</Text>
              {dataCapsule.risk_factors.slice(0, 4).map((item, index) => (
                <Text key={`risk-${index}`} style={styles.capsuleText}>
                  {formatAiText(item)}
                </Text>
              ))}
            </View>
            <View style={styles.capsuleCard}>
              <Text style={styles.capsuleCardTitle}>最近变化</Text>
              {dataCapsule.time_axis.slice(0, 4).map((item, index) => (
                <Text key={`time-${index}`} style={styles.capsuleText}>
                  {formatAiText(item)}
                </Text>
              ))}
            </View>
            <View style={styles.capsuleCard}>
              <Text style={styles.capsuleCardTitle}>信息来源</Text>
              {dataCapsule.data_layers.slice(0, 4).map((item, index) => (
                <Text key={`layer-${index}`} style={styles.capsuleText}>
                  {formatAiText(item)}
                </Text>
              ))}
            </View>
          </View>
        </View>
      ) : null}

      {healthGraph ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>关联重点</Text>
          <View style={styles.graphBox}>
            {healthGraph.nodes.slice(0, 6).length ? (
              <View style={styles.actionChipWrap}>
                {healthGraph.nodes.slice(0, 6).map((item, index) => (
                  <View key={`node-${index}`} style={styles.graphNode}>
                    <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {healthGraph.edges.slice(0, 4).map((item, index) => (
              <Text key={`edge-${index}`} style={styles.graphEdge}>
                {formatAiText(item)}
              </Text>
            ))}
            {healthGraph.dynamic_updates.slice(0, 3).map((item, index) => (
              <Text key={`dynamic-${index}`} style={styles.matrixHint}>
                最新变化：{formatAiText(item)}
              </Text>
            ))}
          </View>
        </View>
      ) : null}

      {reasoningItems.length ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>核对卡片</Text>
          {reasoningItems.map((item, index) => (
            <View key={`${item.mode}-${index}`} style={styles.reasoningCard}>
              <View style={styles.reasoningHead}>
                <Text style={styles.reasoningMode}>{formatReasoningMode(item.mode)}</Text>
                {typeof item.confidence === "number" ? (
                  <Text style={styles.reasoningScore}>可信度 {(item.confidence * 100).toFixed(0)}%</Text>
                ) : null}
              </View>
              <Text style={styles.matrixTitle}>{formatAiText(item.title)}</Text>
              <Text style={styles.matrixHint}>{formatAiText(item.summary)}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </>
  );
}

function ResponseDetails({
  response,
  onInspectRun,
}: {
  response: AIChatResponse;
  onInspectRun?: (runId: string) => void;
}) {
  const activeModels = response.model_plan.filter((item) => item.enabled).map((item) => item.model_name);
  const memory = response.memory;
  const [expanded, setExpanded] = useState(false);

  return (
    <View style={styles.responseCockpit}>
      <View style={styles.responseBadgeRow}>
        <StatusPill text={`建议把握度 ${(response.confidence * 100).toFixed(0)}%`} tone={response.confidence >= 0.8 ? "success" : "warning"} />
        <StatusPill text={response.review_required ? "需人工复核" : "可直接参考"} tone={response.review_required ? "warning" : "success"} />
        <StatusPill text={formatAgentModeLabel(response.agent_mode)} tone={response.agent_mode === "autonomous" ? "danger" : "info"} />
        <StatusPill text={formatExecutionProfileLabel(response.execution_profile)} tone={executionProfileTone(response.execution_profile)} />
      </View>

      <View style={styles.detailStrip}>
        <Text style={styles.detailStripLabel}>当前处理方式</Text>
        <Text style={styles.detailStripValue}>
          {formatWorkflowLabel(response.workflow_type)}
          {response.runtime_engine ? ` · ${formatEngineLabel(response.runtime_engine)}` : ""}
        </Text>
      </View>

      {(response.pending_approvals.length > 0 || response.plan.some((item) => item.status === "approval_required")) ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>当前状态</Text>
          <Text style={styles.detailLead}>这次不是彻底失败，系统已经完成初步判断，正在等你确认后继续。</Text>
          <Text style={styles.detailText}>确认后可继续生成交班草稿、护理记录或沟通摘要。</Text>
        </View>
      ) : null}

      {response.next_actions.length > 0 ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>接下来建议</Text>
          <View style={styles.actionChipWrap}>
            {response.next_actions.slice(0, 4).map((item, index) => (
              <View key={`${formatAiText(item)}-${index}`} style={styles.actionChip}>
                <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      <Pressable style={styles.inlineExpandBtn} onPress={() => setExpanded((prev) => !prev)}>
        <Text style={styles.inlineExpandText}>{expanded ? "收起处理详情" : "展开处理详情"}</Text>
      </Pressable>

      {expanded ? (
        <>
          {response.run_id ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>运行编号</Text>
              <Text style={styles.detailText}>{response.run_id}</Text>
              {onInspectRun ? (
                <ActionButton
                  label="查看过程"
                  onPress={() => onInspectRun(response.run_id!)}
                  variant="secondary"
                  style={styles.inspectAction}
                />
              ) : null}
            </View>
          ) : null}

          {response.agent_goal ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>本次目标</Text>
              <Text style={styles.detailLead}>{response.agent_goal}</Text>
            </View>
          ) : null}

          {response.mission_title || response.success_criteria?.length ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>护理任务说明</Text>
              {response.mission_title ? <Text style={styles.detailLead}>{response.mission_title}</Text> : null}
              {response.success_criteria?.length ? (
                <View style={styles.actionChipWrap}>
                  {response.success_criteria.map((item, index) => (
                    <View key={`${formatAiText(item)}-${index}`} style={styles.actionChip}>
                      <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </View>
          ) : null}

          {activeModels.length > 0 ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>当前参与的系统能力</Text>
              <Text style={styles.detailText}>{activeModels.join(" · ")}</Text>
            </View>
          ) : null}

          <StructuredAgentPanels
            specialistProfiles={response.specialist_profiles}
            hybridCarePath={response.hybrid_care_path}
            dataCapsule={response.data_capsule}
            healthGraph={response.health_graph}
            reasoningCards={response.reasoning_cards}
          />

          {response.plan.length > 0 ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>执行计划</Text>
              {response.plan.map((item) => (
                <View key={item.id} style={styles.planItem}>
                  <View style={styles.planHead}>
                    <Text style={styles.planTitle}>{formatAiText(item.title)}</Text>
                    <StatusPill text={formatPlanStatus(item.status)} tone={planStatusTone(item.status)} />
                  </View>
                  <Text style={styles.planMeta}>{item.tool ? `动作：${formatApprovalToolLabel(item.tool)}` : "动作：系统处理"}</Text>
                  {item.reason ? <Text style={styles.planReason}>{item.reason}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}

          {hasMemoryContent(memory) ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>历史参考</Text>
              {memory?.conversation_summary ? <Text style={styles.detailLead}>{memory.conversation_summary}</Text> : null}
              {memory?.patient_facts.slice(0, 4).map((item, index) => (
                <Text key={`fact-${index}`} style={styles.detailText}>
                  患者事实：{formatAiText(item)}
                </Text>
              ))}
              {memory?.unresolved_tasks.slice(0, 3).map((item, index) => (
                <Text key={`task-${index}`} style={styles.detailText}>
                  待继续处理：{formatAiText(item)}
                </Text>
              ))}
              {memory?.last_actions.slice(0, 3).map((item, index) => (
                <Text key={`action-${index}`} style={styles.detailText}>
                  最近动作：{formatAiText(item)}
                </Text>
              ))}
            </View>
          ) : null}

          {response.artifacts.length > 0 ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>已生成内容</Text>
              {response.artifacts.map((item, index) => (
                <View key={`${item.kind}-${index}`} style={styles.artifactItem}>
                  <View style={styles.artifactHead}>
                    <Text style={styles.artifactTitle}>{formatAiText(item.title)}</Text>
                    <StatusPill text={item.status} tone={item.status === "created" ? "success" : "info"} />
                  </View>
                  <Text style={styles.artifactMeta}>{item.kind}{item.reference_id ? ` · ${item.reference_id}` : ""}</Text>
                  {item.summary ? <Text style={styles.artifactSummary}>{formatAiText(item.summary)}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}

          {response.pending_approvals.length > 0 ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>待你确认</Text>
              {response.pending_approvals.map((item) => (
                <View key={item.id} style={styles.artifactItem}>
                  <View style={styles.artifactHead}>
                    <Text style={styles.artifactTitle}>{formatAiText(item.title)}</Text>
                    <StatusPill
                      text={item.status}
                      tone={item.status === "approved" ? "success" : item.status === "rejected" ? "danger" : "warning"}
                    />
                  </View>
                  {item.reason ? <Text style={styles.artifactSummary}>{item.reason}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}

          {response.steps.length > 0 ? (
            <View style={styles.detailSection}>
              <Text style={styles.detailLabel}>处理过程</Text>
              {response.steps.map((step, index) => (
                <View key={`${step.agent}-${index}`} style={styles.traceItem}>
                  <View style={styles.traceHead}>
                    <Text style={styles.traceAgent}>{formatStepAgentLabel(step.agent)}</Text>
                    <StatusPill text={formatPlanStatus(step.status)} tone={planStatusTone(step.status)} />
                  </View>
                  {step.note ? <Text style={styles.traceNote}>{step.note}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

function RunInspector({
  run,
  onRetry,
  retrying,
}: {
  run: AgentRunRecord;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <View style={styles.runInspectorBody}>
      <View style={styles.responseBadgeRow}>
        <StatusPill text={formatQueueStatus(run.status)} tone={queueStatusTone(run.status)} />
        <StatusPill text={formatWorkflowLabel(run.workflow_type)} tone="info" />
        <StatusPill text={formatExecutionProfileLabel(run.request.execution_profile)} tone={executionProfileTone(run.request.execution_profile)} />
      </View>

      <View style={styles.runMetricRow}>
        <View style={styles.runMetricCard}>
          <Text style={styles.queueSummaryLabel}>调用工具</Text>
          <Text style={styles.queueSummaryValue}>{run.tool_executions.length}</Text>
        </View>
        <View style={styles.runMetricCard}>
          <Text style={styles.queueSummaryLabel}>已生成内容</Text>
          <Text style={styles.queueSummaryValue}>{run.artifacts.length}</Text>
        </View>
        <View style={styles.runMetricCard}>
          <Text style={styles.queueSummaryLabel}>审批项</Text>
          <Text style={styles.queueSummaryValue}>{run.pending_approvals.length}</Text>
        </View>
        <View style={styles.runMetricCard}>
          <Text style={styles.queueSummaryLabel}>后续动作</Text>
          <Text style={styles.queueSummaryValue}>{run.next_actions.length}</Text>
        </View>
      </View>

      {(run.status === "waiting_approval" || run.pending_approvals.length > 0) ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>当前状态</Text>
          <Text style={styles.detailLead}>系统已经完成初步判断，正在等你确认后继续。</Text>
          <Text style={styles.detailText}>这不代表本次失败，而是为了把敏感动作交给你来决定。</Text>
        </View>
      ) : null}

      <View style={styles.detailSection}>
        <Text style={styles.detailLabel}>本次输入</Text>
        {run.request.user_input ? <Text style={styles.detailLead}>{formatAiText(run.request.user_input)}</Text> : null}
        <Text style={styles.detailText}>
          {run.request.bed_no ? `${run.request.bed_no}床` : run.patient_id || "未绑定病例"} · {formatAgentModeLabel(run.agent_mode)} ·{" "}
          {formatEngineLabel(run.runtime_engine)}
        </Text>
      </View>

      {run.request.mission_title || run.request.success_criteria.length || run.request.operator_notes ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>护理任务说明</Text>
          {run.request.mission_title ? <Text style={styles.detailLead}>{run.request.mission_title}</Text> : null}
          {run.request.success_criteria.length ? (
            <View style={styles.actionChipWrap}>
              {run.request.success_criteria.map((item, index) => (
                <View key={`${formatAiText(item)}-${index}`} style={styles.actionChip}>
                  <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
                </View>
              ))}
            </View>
          ) : null}
          {run.request.operator_notes ? <Text style={styles.detailText}>操作备注：{run.request.operator_notes}</Text> : null}
        </View>
      ) : null}

      {run.agent_goal ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>本次目标</Text>
          <Text style={styles.detailLead}>{run.agent_goal}</Text>
        </View>
      ) : null}

      {run.next_actions.length > 0 ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>接下来要做</Text>
          <View style={styles.actionChipWrap}>
            {run.next_actions.slice(0, 6).map((item, index) => (
              <View key={`${formatAiText(item)}-${index}`} style={styles.actionChip}>
                <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      <StructuredAgentPanels
        specialistProfiles={run.specialist_profiles}
        hybridCarePath={run.hybrid_care_path}
        dataCapsule={run.data_capsule}
        healthGraph={run.health_graph}
        reasoningCards={run.reasoning_cards}
      />

      {run.tool_executions.length > 0 ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>系统动作记录</Text>
          {run.tool_executions.map((item, index) => (
            <View key={`${item.item_id}-${index}`} style={styles.executionItem}>
              <View style={styles.artifactHead}>
                <Text style={styles.artifactTitle}>{formatAiText(item.title)}</Text>
                <StatusPill text={formatPlanStatus(item.status)} tone={planStatusTone(item.status)} />
              </View>
              <Text style={styles.artifactMeta}>
                {formatApprovalToolLabel(item.tool)} · {formatStepAgentLabel(item.agent)} · 尝试 {item.attempts} 次
              </Text>
              {item.error ? <Text style={styles.artifactSummary}>错误：{item.error}</Text> : null}
            </View>
          ))}
        </View>
      ) : null}

      {run.error ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>运行报错</Text>
          <Text style={styles.artifactSummary}>{run.error}</Text>
        </View>
      ) : null}

      {run.plan.length > 0 ? (
        <View style={styles.detailSection}>
          <Text style={styles.detailLabel}>本次处理计划</Text>
          {run.plan.map((item) => (
            <View key={item.id} style={styles.planItem}>
              <View style={styles.planHead}>
                <Text style={styles.planTitle}>{formatAiText(item.title)}</Text>
                <StatusPill text={formatPlanStatus(item.status)} tone={planStatusTone(item.status)} />
              </View>
              <Text style={styles.planMeta}>{item.tool ? `动作：${formatApprovalToolLabel(item.tool)}` : "动作：系统处理"}</Text>
              {item.reason ? <Text style={styles.planReason}>{item.reason}</Text> : null}
            </View>
          ))}
        </View>
      ) : null}

      {run.retry_available && onRetry ? (
        <View style={styles.rowWrap}>
          <ActionButton
            label={retrying ? "重试中" : "重试运行"}
            onPress={onRetry}
            variant="secondary"
            style={styles.queueEnqueueAction}
            disabled={Boolean(retrying)}
          />
        </View>
      ) : null}
    </View>
  );
}

export function RecommendationScreen() {
  const navigation = useNavigation<any>();
  const user = useAppStore((state) => state.user);
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);

  const [mode, setMode] = useState<AIChatMode>("agent_cluster");
  const [models, setModels] = useState<AIModelOption[]>([]);
  const [clusters, setClusters] = useState<AIClusterProfile[]>([]);
  const [selectedModel, setSelectedModel] = useState("minicpm3_4b_local");
  const [selectedCluster, setSelectedCluster] = useState("nursing_default_cluster");
  const [runtimeStatus, setRuntimeStatus] = useState<AIRuntimeStatus | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeBusy, setRuntimeBusy] = useState("");
  const [queueTasks, setQueueTasks] = useState<AgentQueueTask[]>([]);
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueBusyId, setQueueBusyId] = useState("");
  const [queueStatusFilter, setQueueStatusFilter] = useState<"all" | "waiting_approval" | "running" | "completed">("all");
  const [queueProfileFilter, setQueueProfileFilter] = useState<"all" | AIExecutionProfile>("all");
  const [runRecords, setRunRecords] = useState<AgentRunRecord[]>([]);
  const [runLoading, setRunLoading] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedRun, setSelectedRun] = useState<AgentRunRecord | null>(null);
  const [patientContext, setPatientContext] = useState<PatientContext | null>(null);
  const [patientOrders, setPatientOrders] = useState<OrderListOut | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [executionProfile, setExecutionProfile] = useState<AIExecutionProfile>("observe");
  const [missionTitle, setMissionTitle] = useState("");
  const [missionNotes, setMissionNotes] = useState("");
  const [successCriteria, setSuccessCriteria] = useState<string[]>([]);

  const [question, setQuestion] = useState("");
  const [attachments, setAttachments] = useState<Array<{ name: string; payload: string }>>([]);
  const [messages, setMessages] = useState<AIChatMessage[]>([]);
  const [folders, setFolders] = useState<ConversationFolder[]>([]);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retryBusyId, setRetryBusyId] = useState("");

  const [caseBeds, setCaseBeds] = useState<BedOverview[]>([]);
  const [lastResolvedPatientId, setLastResolvedPatientId] = useState("");
  const [lastResolvedBedNo, setLastResolvedBedNo] = useState("");
  const [lastAssistantSummary, setLastAssistantSummary] = useState("");
  const [lastCreatedDraftId, setLastCreatedDraftId] = useState("");
  const [lastCreatedOrderNo, setLastCreatedOrderNo] = useState("");
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("result");
  const [selectorExpanded, setSelectorExpanded] = useState(true);
  const [engineMenuOpen, setEngineMenuOpen] = useState(false);

  const patientId = selectedPatient?.id;
  const patientDisplayName =
    selectedPatient?.id && patientContext?.patient_id === selectedPatient.id
      ? patientContext.patient_name || selectedPatient.full_name
      : selectedPatient?.full_name || "当前病例";

  const activeCluster = useMemo(() => clusters.find((item) => item.id === selectedCluster), [clusters, selectedCluster]);

  const activeClusterTasks: AIModelTask[] = useMemo(() => {
    return activeCluster?.tasks || [];
  }, [activeCluster]);

  const availableLocalModelSet = useMemo(
    () => new Set((runtimeStatus?.available_local_models || []).map((item) => String(item).trim().toLowerCase()).filter(Boolean)),
    [runtimeStatus?.available_local_models]
  );

  const isLocalAliasReady = (alias?: string) => {
    const key = String(alias || "").trim().toLowerCase();
    return key ? availableLocalModelSet.has(key) : false;
  };

  const primaryReady = isLocalAliasReady(runtimeStatus?.local_model_aliases?.primary);
  const plannerReady = isLocalAliasReady(runtimeStatus?.local_model_aliases?.planner);
  const reasoningReady = isLocalAliasReady(runtimeStatus?.local_model_aliases?.reasoning);
  const multimodalReady = isLocalAliasReady(runtimeStatus?.local_model_aliases?.multimodal);

  const runtimeCapabilities = useMemo(
    () => {
      if (!runtimeStatus?.local_model_service_reachable) {
        return [
          { label: "基础整理", status: "服务未连上" },
          { label: "下一步提醒", status: "服务未连上" },
          { label: "重点复看", status: "服务未连上" },
          { label: "附件查看", status: "服务未连上" },
        ];
      }
      return [
        { label: "基础整理", status: primaryReady ? "已启动" : "未启动" },
        { label: "下一步提醒", status: plannerReady ? "已单独启动" : primaryReady ? "先共用基础整理" : "未启动" },
        { label: "重点复看", status: reasoningReady ? "已单独启动" : primaryReady ? "先共用基础整理" : "未启动" },
        { label: "附件查看", status: multimodalReady ? "已启动" : "未启动" },
      ];
    },
    [multimodalReady, plannerReady, primaryReady, reasoningReady, runtimeStatus?.local_model_service_reachable]
  );

  const runtimeFallbackText = useMemo(() => {
    const reason = String(runtimeStatus?.fallback_reason || "");
    if (!reason) {
      return "";
    }
    if (reason === "langgraph_unavailable_fallback") {
      return "深度复看暂未就绪，系统已自动改用标准流程，不影响基础判断和继续处理。";
    }
    if (reason === "engine_override") {
      return "当前处理方式由你手动指定。";
    }
    return "系统已自动改用更稳妥的处理方式，优先保证当前任务能继续完成。";
  }, [runtimeStatus?.fallback_reason]);

  const runtimeCapabilitySummary = useMemo(
    () => runtimeCapabilities.map((item) => `${item.label}${item.status}`).join(" · "),
    [runtimeCapabilities]
  );

  const runtimeModelSummary = useMemo(() => {
    if (!runtimeStatus?.local_model_service_reachable) {
      return "当前本地回答能力没有连上，所以系统只能给基础提示，生成和继续处理都容易失败。";
    }
    if (!primaryReady) {
      return "当前已经连上本地服务，但基础整理还没启动，请先启动至少一个本地回答模型。";
    }
    if (plannerReady && reasoningReady && multimodalReady) {
      return "基础整理、下一步提醒、重点复看和附件查看都已启动。";
    }
    if (!plannerReady && !reasoningReady && !multimodalReady) {
      return "目前只有基础整理已启动；下一步提醒和重点复看会先共用这一能力，附件查看还没启动。";
    }
    if (multimodalReady && !plannerReady && !reasoningReady) {
      return "基础整理和附件查看已启动；下一步提醒和重点复看会先共用基础整理。";
    }
    const extraReady = [
      plannerReady ? "下一步提醒" : "",
      reasoningReady ? "重点复看" : "",
      multimodalReady ? "附件查看" : "",
    ]
      .filter(Boolean)
      .join("、");
    return `当前基础整理已启动；${extraReady}也已单独启动，其余能力会先共用基础整理。`;
  }, [multimodalReady, plannerReady, primaryReady, reasoningReady, runtimeStatus?.local_model_service_reachable]);

  const profileMeta = EXECUTION_PROFILE_META[executionProfile];
  const normalizedMissionTitle = missionTitle.trim();
  const normalizedMissionNotes = missionNotes.trim();
  const normalizedSuccessCriteria = useMemo(
    () => successCriteria.map((item) => item.trim()).filter(Boolean),
    [successCriteria]
  );

  const visibleQueueTasks = useMemo(() => {
    return queueTasks.filter((item) => (queueStatusFilter === "all" ? true : item.status === queueStatusFilter)).filter((item) => {
      if (queueProfileFilter === "all") {
        return true;
      }
      return (item.payload.execution_profile || "observe") === queueProfileFilter;
    });
  }, [queueTasks, queueStatusFilter, queueProfileFilter]);

  const abnormalObservations = useMemo(() => {
    return (patientContext?.latest_observations || []).filter((item) => item.abnormal_flag);
  }, [patientContext]);

  const quickPrompts = useMemo(() => {
    const bedLabel = patientContext?.bed_no || selectedPatient?.id || "当前床位";
    const topObservation = abnormalObservations[0];
    const topRisk = patientContext?.risk_tags?.[0];
    const dueSoon = patientOrders?.stats?.due_30m || 0;
    const overdue = patientOrders?.stats?.overdue || 0;

    if (executionProfile === "escalate") {
      return [
        `请判断${bedLabel}是否需要立即上报医生，并给出升级依据与协作摘要`,
        `请围绕${bedLabel}整理当前最危险的3个信号，给出面向值班医生的沟通版本`,
        `请基于${bedLabel}的异常指标和医嘱状态，生成上报前的风险总览`,
      ];
    }

    if (executionProfile === "document") {
      return [
        `请为${bedLabel}生成护理记录草稿，并标出需要人工复核的内容`,
        `请为${bedLabel}生成交班摘要，列出下一班重点观察事项`,
        `请把${bedLabel}当前建议沉淀成文书与交班要点`,
      ];
    }

    if (executionProfile === "full_loop") {
      return [
        `请围绕${bedLabel}做一次持续跟进：先看风险、补看医嘱，需要时上报并补齐交班/文书`,
        `请持续跟进${bedLabel}，把异常指标、协作动作和留痕草稿都推进到位`,
        `请对${bedLabel}执行持续跟进，敏感动作先进入人工确认`,
      ];
    }

    return [
      `请先梳理${bedLabel}当前风险、异常指标和接下来30分钟观察重点`,
      `请总结${bedLabel}当前病情重点${topObservation ? `，特别关注${topObservation.name}${topObservation.value}` : ""}`,
      `请结合${topRisk || "当前风险标签"}${dueSoon || overdue ? `和${dueSoon + overdue}项临近/超时医嘱` : ""}给出优先处理顺序`,
    ];
  }, [abnormalObservations, executionProfile, patientContext, patientOrders, selectedPatient]);

  const latestAssistantMessage = useMemo(
    () => [...messages].reverse().find((item) => item.role === "assistant") || null,
    [messages]
  );
  const latestAssistantResponse = latestAssistantMessage?.response || null;
  const hasResultWorkspace = Boolean(lastAssistantSummary || latestAssistantResponse || loading || error);
  const workspaceTabs = useMemo(() => {
    const items = [
      { key: "result" as const, label: "输出", count: hasResultWorkspace ? 1 : 0 },
      { key: "history" as const, label: "历史", count: folders.length },
      { key: "queue" as const, label: "任务", count: visibleQueueTasks.length },
      { key: "system" as const, label: "状态", count: runtimeStatus?.task_queue?.waiting_approval || 0 },
    ];

    if (workspaceView === "runs") {
      items.splice(1, 0, { key: "runs" as const, label: "过程", count: runRecords.length });
    }

    return items;
  }, [
    error,
    folders.length,
    hasResultWorkspace,
    loading,
    runRecords.length,
    runtimeStatus?.task_queue?.waiting_approval,
    visibleQueueTasks.length,
    workspaceView,
  ]);

  useEffect(() => {
    if (visibleQueueTasks.some((item) => item.status === "waiting_approval")) {
      setWorkspaceView("queue");
    }
  }, [visibleQueueTasks]);

  useEffect(() => {
    if (!selectedPatient?.id) {
      setSelectorExpanded(true);
    }
  }, [selectedPatient?.id]);

  const missionTemplateTitle = useMemo(() => {
    const patientLabel = patientContext?.bed_no ? `${patientContext.bed_no}床` : selectedPatient?.full_name || "当前病例";
    return `${profileMeta.label} · ${patientLabel}`;
  }, [patientContext?.bed_no, profileMeta.label, selectedPatient?.full_name]);

  const missionCriteriaOptions = useMemo(() => {
    const patientLabel = patientContext?.bed_no ? `${patientContext.bed_no}床` : selectedPatient?.full_name || "当前病例";
    const topObservation = abnormalObservations[0];
    const dueSoon = patientOrders?.stats?.due_30m || 0;
    const overdue = patientOrders?.stats?.overdue || 0;
    const options =
      executionProfile === "escalate"
        ? [
            `判断${patientLabel}是否需要立即上报`,
            "生成给值班医生的协作摘要",
            "列出触发升级的关键依据",
          ]
        : executionProfile === "document"
        ? [
            `生成${patientLabel}护理记录草稿`,
            `生成${patientLabel}交班摘要`,
            "标记需要人工复核的文书段落",
          ]
        : executionProfile === "full_loop"
        ? [
            `围绕${patientLabel}完成风险识别与后续处理`,
            "敏感动作进入审批后继续推进",
            "同步产出协作摘要与文书草稿",
          ]
        : [
            `明确${patientLabel}当前最高风险`,
            "列出接下来30分钟观察重点",
            "给出优先处理顺序",
          ];

    if (topObservation?.name) {
      options.push(`解释${topObservation.name}异常对当前护理的影响`);
    }
    if (dueSoon || overdue) {
      options.push(`核对${dueSoon + overdue}项临近或超时医嘱`);
    }
    if (patientContext?.latest_document_sync) {
      options.push("同步最新文书状态与下一班待办");
    }

    return Array.from(new Set(options)).slice(0, 6);
  }, [
    abnormalObservations,
    executionProfile,
    patientContext?.bed_no,
    patientContext?.latest_document_sync,
    patientOrders?.stats?.due_30m,
    patientOrders?.stats?.overdue,
    selectedPatient?.full_name,
  ]);

  const resolvedMissionTitle = normalizedMissionTitle || missionTemplateTitle;
  const resolvedSuccessCriteria = useMemo(
    () => (normalizedSuccessCriteria.length ? normalizedSuccessCriteria : missionCriteriaOptions.slice(0, 3)),
    [missionCriteriaOptions, normalizedSuccessCriteria]
  );

  const inputEngineOptions = useMemo<InputEngineOption[]>(() => {
    const activeClusterId = selectedCluster || clusters[0]?.id || "nursing_default_cluster";
    const clusterLabel =
      CLUSTER_FALLBACK[activeClusterId] ||
      clusters.find((item) => item.id === activeClusterId)?.name ||
      activeCluster?.name ||
      "系统协同";

    return [
      {
        key: "agent_cluster",
        label: "AI Agent",
        detail: `${clusterLabel} · ${profileMeta.label}`,
        mode: "agent_cluster",
      },
      ...models.map((item) => {
        const fallback = MODEL_FALLBACK[item.id];
        return {
          key: `model:${item.id}`,
          label: fallback?.name || item.name,
          detail: fallback?.description || item.description || "单模型直接回答",
          mode: "single_model" as const,
          modelId: item.id,
        };
      }),
    ];
  }, [activeCluster?.name, clusters, models, profileMeta.label, selectedCluster]);

  const activeInputEngine = useMemo(() => {
    if (mode === "agent_cluster") {
      return inputEngineOptions[0];
    }

    return inputEngineOptions.find((item) => item.modelId === selectedModel) || inputEngineOptions[0];
  }, [inputEngineOptions, mode, selectedModel]);

  const loadPatientBoard = async () => {
    if (!patientId) {
      setPatientContext(null);
      setPatientOrders(null);
      return;
    }
    setContextLoading(true);
    try {
      const [context, orders] = await Promise.all([api.getPatientContext(patientId), api.getPatientOrders(patientId)]);
      setPatientContext(context);
      setPatientOrders(orders);
    } catch {
      setPatientContext(null);
      setPatientOrders(null);
    } finally {
      setContextLoading(false);
    }
  };

  const loadRuntimeStatus = async (silent = false) => {
    if (!silent) {
      setRuntimeLoading(true);
    }
    try {
      const status = await api.getAiRuntimeStatus();
      setRuntimeStatus(status);
    } catch {
      if (!silent) {
        setError("运行时状态暂不可达，已保留本地配置界面。");
      }
    } finally {
      if (!silent) {
        setRuntimeLoading(false);
      }
    }
  };

  const loadQueueTasks = async (silent = false) => {
    const currentConversationId = activeConversationId || undefined;
    const filter = patientId || currentConversationId
      ? { patientId, conversationId: currentConversationId, limit: 12 }
      : null;

    if (!filter) {
      setQueueTasks([]);
      return;
    }

    if (!silent) {
      setQueueLoading(true);
    }
    try {
      const items = await api.listAgentQueueTasks(filter);
      setQueueTasks(items);
    } catch {
      if (!silent) {
        setError("后台任务暂时取不到，请先刷新；如果一直失败，再检查后台服务。");
      }
    } finally {
      if (!silent) {
        setQueueLoading(false);
      }
    }
  };

  const loadRunRecords = async (silent = false, preferredRunId?: string, conversationIdOverride?: string) => {
    const currentConversationId = conversationIdOverride || activeConversationId || undefined;
    const filter = patientId || currentConversationId
      ? { patientId, conversationId: currentConversationId, limit: 16 }
      : null;

    if (!filter) {
      setRunRecords([]);
      setSelectedRunId("");
      setSelectedRun(null);
      return;
    }

    if (!silent) {
      setRunLoading(true);
    }
    try {
      const items = await api.listAgentRuns(filter);
      setRunRecords(items);
      const nextRunId =
        preferredRunId ||
        (selectedRunId && items.some((item) => item.id === selectedRunId) ? selectedRunId : items[0]?.id || "");
      setSelectedRunId(nextRunId);
      if (!nextRunId) {
        setSelectedRun(null);
        return;
      }

      const fallbackRun = items.find((item) => item.id === nextRunId) || null;
      try {
        const detail = await api.getAgentRun(nextRunId);
        setSelectedRun(detail);
        setError("");
      } catch (error) {
        if (fallbackRun) {
          setSelectedRun(fallbackRun);
          if (!silent) {
            setError(getApiErrorMessage(error, "这次结果已经出来了，处理过程还在同步，你可以先看下方建议。"));
          }
          return;
        }
        throw error;
      }
    } catch (error) {
      if (!silent) {
        setError(getApiErrorMessage(error, "当前这次处理回看暂时没取到，请先刷新；这不代表本次整理失败。"));
      }
    } finally {
      if (!silent) {
        setRunLoading(false);
      }
    }
  };

  const loadModels = async () => {
    try {
      const catalog = await api.getAiModels();
      const modelList = catalog.single_models || [];
      const clusterList = catalog.cluster_profiles || [];
      setModels(modelList);
      setClusters(clusterList);
      if (modelList.length > 0) {
        setSelectedModel((prev) => (modelList.some((item) => item.id === prev) ? prev : modelList[0].id));
      }
      if (clusterList.length > 0) {
        setSelectedCluster((prev) => (clusterList.some((item) => item.id === prev) ? prev : clusterList[0].id));
      }
    } catch {
      setModels(DEFAULT_MODEL_OPTIONS);
      setClusters(DEFAULT_CLUSTER_PROFILES);
      setSelectedModel("minicpm3_4b_local");
      setSelectedCluster("nursing_default_cluster");
      setError("系统说明暂时取不到，已切换为内置说明。");
    }
  };

  const switchRuntimeEngine = async (engine: "state_machine" | "langgraph") => {
    setRuntimeBusy(engine);
    try {
      const next = await api.setAiRuntimeEngine(engine);
      setRuntimeStatus(next);
    } catch {
      Alert.alert("切换失败", "处理方式切换失败，请稍后再试。");
    } finally {
      setRuntimeBusy("");
    }
  };

  const clearRuntimeOverride = async () => {
    setRuntimeBusy("clear");
    try {
      const next = await api.clearAiRuntimeEngine();
      setRuntimeStatus(next);
    } catch {
      Alert.alert("恢复失败", "无法恢复默认运行时配置。");
    } finally {
      setRuntimeBusy("");
    }
  };

  const loadHistory = async (preferredConversationId?: string, silent = false) => {
    if (!patientId) {
      setMessages([]);
      setFolders([]);
      setActiveConversationId("");
      return;
    }
    if (!silent) {
      setHistoryLoading(true);
    }
    try {
      const items = await api.getAllHistory(patientId, 200);
      const folderList = buildConversationFolders(items);
      setFolders(folderList);

      const targetConversationId =
        preferredConversationId ||
        (activeConversationId && folderList.some((item) => item.id === activeConversationId)
          ? activeConversationId
          : folderList[0]?.id || "");
      setActiveConversationId(targetConversationId);

      const selectedItems = targetConversationId
        ? items.filter((item) => getConversationKey(item) === targetConversationId)
        : [];
      setMessages(historyToMessages(selectedItems));
    } catch {
      if (!silent) {
        setError("历史记录刷新慢了一点，你可以先看当前回复，稍后点“刷新历史”。");
      }
    } finally {
      if (!silent) {
        setHistoryLoading(false);
      }
    }
  };

  useEffect(() => {
    loadModels();
    loadRuntimeStatus();
  }, []);

  useEffect(() => {
    loadHistory();
  }, [patientId]);

  useEffect(() => {
    loadPatientBoard();
  }, [patientId]);

  useEffect(() => {
    if (!departmentId) {
      return undefined;
    }
    const unsubscribe = subscribeWardBeds(
      departmentId,
      (event) => {
        if (event?.type !== "ward_beds_update" || !Array.isArray(event?.data)) {
          return;
        }
        const nextBeds = event.data as BedOverview[];
        setCaseBeds(nextBeds);
        if (!selectedPatient?.id) {
          return;
        }
        const matched = nextBeds.find((item) => item.current_patient_id === selectedPatient.id);
        if (matched?.patient_name && matched.patient_name !== selectedPatient.full_name) {
          setSelectedPatient({ ...selectedPatient, full_name: matched.patient_name });
        }
      },
      () => {}
    );
    return unsubscribe;
  }, [departmentId, selectedPatient, setSelectedPatient]);

  useEffect(() => {
    if (!patientId) {
      return undefined;
    }
    const unsubscribe = subscribePatientContext(
      patientId,
      (event) => {
        if (event?.type !== "patient_context_update" || !event?.data) {
          return;
        }
        const nextContext = event.data as PatientContext;
        setPatientContext(nextContext);
        void api
          .getPatient(patientId)
          .then((patient) => {
            setSelectedPatient(patient);
          })
          .catch(() => {
            const incomingName = String(nextContext.patient_name || "").trim();
            if (incomingName && selectedPatient && incomingName !== selectedPatient.full_name) {
              setSelectedPatient({ ...selectedPatient, full_name: incomingName });
            }
          });
      },
      () => {}
    );
    return unsubscribe;
  }, [patientId, selectedPatient, setSelectedPatient]);

  useEffect(() => {
    loadQueueTasks();
  }, [patientId, activeConversationId]);

  useEffect(() => {
    loadRunRecords();
  }, [patientId, activeConversationId]);

  useEffect(() => {
    const timer = setInterval(() => {
      loadRuntimeStatus(true);
      loadQueueTasks(true);
      loadRunRecords(true);
    }, 5000);
    return () => clearInterval(timer);
  }, [patientId, activeConversationId, selectedRunId]);

  useEffect(() => {
    setQuestion("");
    setAttachments([]);
    setMissionTitle("");
    setMissionNotes("");
    setSuccessCriteria([]);
    setError("");
    setMessages([]);
    setFolders([]);
    setActiveConversationId("");
    setLastCreatedDraftId("");
    setLastCreatedOrderNo("");
    setQueueTasks([]);
    setRunRecords([]);
    setSelectedRunId("");
    setSelectedRun(null);
    setPatientContext(null);
    setPatientOrders(null);
    setRetryBusyId("");
    setEngineMenuOpen(false);
  }, [patientId]);

  const ensureConversationId = (seedText: string) => {
    const conversationId = activeConversationId || `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    if (!activeConversationId) {
      const now = new Date().toISOString();
      const nextFolder: ConversationFolder = {
        id: conversationId,
        title: seedText.slice(0, 14) || `新对话-${folders.length + 1}`,
        latestAt: now,
        count: 0,
      };
      setFolders((prev) => [nextFolder, ...prev]);
      setActiveConversationId(conversationId);
    }
    return conversationId;
  };

  const createConversation = () => {
    const conversationId = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();
    const nextFolder: ConversationFolder = {
      id: conversationId,
      title: `新对话-${folders.length + 1}`,
      latestAt: now,
      count: 0,
    };
    setFolders((prev) => [nextFolder, ...prev]);
    setActiveConversationId(conversationId);
    setMessages([]);
    setQuestion("");
    setAttachments([]);
    setMissionTitle("");
    setMissionNotes("");
    setSuccessCriteria([]);
    setError("");
    setRunRecords([]);
    setSelectedRunId("");
    setSelectedRun(null);
    setWorkspaceView("history");
  };

  const applyPromptPreset = (preset: string) => {
    setQuestion(preset);
    setError("");
  };

  const applyMissionTemplate = () => {
    setMissionTitle((prev) => prev.trim() || missionTemplateTitle);
    setSuccessCriteria((prev) => (prev.length ? prev : missionCriteriaOptions.slice(0, 3)));
    setMissionNotes((prev) => prev.trim() || `围绕${profileMeta.label}推进任务，输出需要便于护士人工复核。`);
  };

  const clearMissionBrief = () => {
    setMissionTitle("");
    setMissionNotes("");
    setSuccessCriteria([]);
  };

  const toggleSuccessCriterion = (item: string) => {
    setSuccessCriteria((prev) => (prev.includes(item) ? prev.filter((entry) => entry !== item) : [...prev, item]));
  };

  const inspectRun = async (runId: string) => {
    setWorkspaceView("runs");
    setSelectedRunId(runId);
    setRunLoading(true);
    try {
      const detail = await api.getAgentRun(runId);
      setSelectedRun(detail);
      setError("");
    } catch (error) {
      const fallbackRun = runRecords.find((item) => item.id === runId) || null;
      if (fallbackRun) {
        setSelectedRun(fallbackRun);
        setError(getApiErrorMessage(error, "这次结果已经出来了，处理过程还在同步，你可以先看下方建议。"));
      } else {
        setError(getApiErrorMessage(error, "当前这次处理回看暂时没取到，请先刷新服务连接情况后再试。"));
      }
    } finally {
      setRunLoading(false);
    }
  };

  const retryRun = async (runId: string) => {
    setRetryBusyId(runId);
    setError("");
    try {
      const output = await api.retryAgentRun(runId);
      const conversationId =
        selectedRun?.id === runId
          ? selectedRun.conversation_id
          : runRecords.find((item) => item.id === runId)?.conversation_id || activeConversationId;
      await loadRuntimeStatus(true);
      await loadQueueTasks(true);
      if (patientId && conversationId) {
        await loadHistory(conversationId, true);
      }
      if (output.run_id) {
        await loadRunRecords(true, output.run_id, conversationId || undefined);
      } else {
        await loadRunRecords(true, undefined, conversationId || undefined);
      }
    } catch (error) {
      setError(getApiErrorMessage(error, "重新发起没成功。请先看“服务连接情况”里基础回答是否已连接，再重试。"));
    } finally {
      setRetryBusyId("");
    }
  };

  const pickImage = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert("相册权限被拒绝");
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.72,
    });
    if (result.canceled) {
      return;
    }

    const next: Array<{ name: string; payload: string }> = [];
    for (const item of result.assets) {
      const base64 =
        item.base64 ||
        (item.uri
          ? await FileSystem.readAsStringAsync(item.uri, { encoding: FileSystem.EncodingType.Base64 })
          : "");
      if (!base64) {
        continue;
      }
      const mime = item.mimeType || "image/jpeg";
      next.push({
        name: item.fileName || item.uri.split("/").pop() || `image-${Date.now()}.jpg`,
        payload: `data:${mime};base64,${base64}`,
      });
    }
    setAttachments((prev) => [...prev, ...next]);
  };

  const pickDocument = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["application/pdf", "image/*"],
      copyToCacheDirectory: true,
      multiple: true,
    });
    if (result.canceled) {
      return;
    }

    const next: Array<{ name: string; payload: string }> = [];
    for (const item of result.assets) {
      try {
        const base64 = await FileSystem.readAsStringAsync(item.uri, {
          encoding: FileSystem.EncodingType.Base64,
        });
        const mime = item.mimeType || "application/octet-stream";
        next.push({
          name: item.name || item.uri.split("/").pop() || `file-${Date.now()}`,
          payload: `data:${mime};base64,${base64}`,
        });
      } catch {
        Alert.alert("附件读取失败", `无法读取文件：${item.name || item.uri}`);
      }
    }
    setAttachments((prev) => [...prev, ...next]);
  };

  const resolveTargetPatient = async (text: string): Promise<{ patientId?: string; bedNo?: string; display?: string }> => {
    const bedNo = extractBedNo(text);

    if (!bedNo) {
      if (selectedPatient?.id) {
        return { patientId: selectedPatient.id, display: `${patientDisplayName}（${selectedPatient.id}）` };
      }
      return {};
    }

    let list = caseBeds;
    if (!list.length) {
      list = await api.getWardBeds(departmentId);
      setCaseBeds(Array.isArray(list) ? list : []);
    }

    const matched = (Array.isArray(list) ? list : []).find((item) => String(item.bed_no) === String(bedNo));
    if (matched?.current_patient_id) {
      const targetId = matched.current_patient_id;
      if (!selectedPatient || selectedPatient.id !== targetId) {
        try {
          const p = await api.getPatient(targetId);
          setSelectedPatient(p);
        } catch {
          // ignore
        }
      }
      return {
        patientId: targetId,
        bedNo,
        display: `${matched.bed_no}床 · ${matched.patient_name || targetId}`,
      };
    }

    // 找不到床位映射时，也把床号交给后端做二次解析
    return {
      patientId: selectedPatient?.id,
      bedNo,
      display: `${bedNo}床（待后端解析）`,
    };
  };

  const send = async () => {
    const text = question.trim();
    if (!text) {
      Alert.alert("请输入问题");
      return;
    }

    const target = await resolveTargetPatient(text);
    if (!target.patientId && !target.bedNo) {
      Alert.alert("请先选择病例", "你可以先选择病例，或直接在问题中写“23床...”进行跨病例问询。");
      return;
    }

    const conversationId = ensureConversationId(text);

    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        mode,
        text,
        timestamp: now,
      },
    ]);
    setLoading(true);
    setError("");
    setWorkspaceView("result");
    setEngineMenuOpen(false);

    try {
      const inferredAgentMode = mode === "single_model" ? "direct_answer" : profileMeta.agentMode;
      const response = await api.runAiChat({
        mode,
        selectedModel: mode === "single_model" ? selectedModel : undefined,
        clusterProfile: mode === "agent_cluster" ? selectedCluster : undefined,
        patientId: target.patientId,
        bedNo: target.bedNo,
        conversationId,
        departmentId,
        userInput: text,
        missionTitle: resolvedMissionTitle || undefined,
        successCriteria: resolvedSuccessCriteria,
        operatorNotes: normalizedMissionNotes || undefined,
        attachments: attachments.map((item) => item.payload),
        requestedBy: user?.id,
        agentMode: inferredAgentMode,
        executionProfile,
      });

      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          mode,
          text: response.summary,
          timestamp: response.created_at,
          response,
        },
      ]);
      setQuestion("");
      setAttachments([]);
      setFolders((prev) =>
        prev.map((item) =>
          item.id === conversationId
            ? {
                ...item,
                latestAt: response.created_at,
                count: item.count + 2,
                title: item.title.startsWith("新对话-") ? text.slice(0, 14) || item.title : item.title,
              }
            : item
        )
      );

      setLastResolvedPatientId(String(target.patientId || ""));
      setLastResolvedBedNo(String(target.bedNo || ""));
      setLastAssistantSummary(formatAiText(response.summary));
      setWorkspaceView("result");
      setSelectorExpanded(false);
      if (target.patientId || patientId) {
        await loadHistory(conversationId, true);
      }
      if (response.run_id) {
        await loadRunRecords(true, response.run_id, conversationId || undefined);
      } else {
        await loadRunRecords(true, undefined, conversationId || undefined);
      }
    } catch (error) {
      setWorkspaceView("result");
      setError(getApiErrorMessage(error, "本次整理没有发出去。请先看“服务连接情况”里基础回答是否已连接，再重试。"));
    } finally {
      setLoading(false);
    }
  };

  const enqueueCurrentTask = async () => {
    if (mode !== "agent_cluster") {
      Alert.alert("当前模式不支持", "后台持续处理只在“系统协同”模式下启用。");
      return;
    }

    const text = question.trim();
    if (!text) {
      Alert.alert("请输入问题");
      return;
    }

    const target = await resolveTargetPatient(text);
    if (!target.patientId && !target.bedNo) {
      Alert.alert("请先选择病例", "你可以先选择病例，或直接在问题中写“23床...”进行跨病例问询。");
      return;
    }

    const conversationId = ensureConversationId(text);
    const now = new Date().toISOString();
    const inferredAgentMode = profileMeta.agentMode;
    const requestedWorkflowType = profileMeta.queueWorkflow;
    const requestedEngine = runtimeStatus?.configured_engine || undefined;

    setQueueBusyId("enqueue");
    setError("");
    try {
      const task = await api.enqueueAgentTask({
        workflowType: requestedWorkflowType,
        patientId: target.patientId,
        bedNo: target.bedNo,
        conversationId,
        departmentId,
        userInput: text,
        missionTitle: resolvedMissionTitle || undefined,
        successCriteria: resolvedSuccessCriteria,
        operatorNotes: normalizedMissionNotes || undefined,
        attachments: attachments.map((item) => item.payload),
        requestedBy: user?.id,
        agentMode: inferredAgentMode,
        executionProfile,
        requestedEngine,
        priority:
          /危急|紧急|低血压|少尿|胸痛|呼吸困难/i.test(text) || executionProfile === "full_loop" || executionProfile === "escalate"
            ? 40
            : executionProfile === "document"
            ? 60
            : 80,
      });

      setMessages((prev) => [
        ...prev,
        {
          id: `u-queue-${Date.now()}`,
          role: "user",
          mode,
          text,
          timestamp: now,
        },
        {
          id: `a-queue-${task.id}`,
          role: "assistant",
          mode,
          text: task.summary || "任务已进入后台队列，系统会继续推进，需要你确认时再提醒你。",
          timestamp: task.updated_at,
        },
      ]);
      setFolders((prev) =>
        prev.map((item) =>
          item.id === conversationId
            ? {
                ...item,
                latestAt: task.updated_at,
                count: item.count + 2,
                title: item.title.startsWith("新对话-") ? text.slice(0, 14) || item.title : item.title,
              }
            : item
        )
      );
      setQuestion("");
      setAttachments([]);
      setLastResolvedPatientId(String(target.patientId || ""));
      setLastResolvedBedNo(String(target.bedNo || ""));
      setWorkspaceView("queue");
      await loadQueueTasks(true);
      await loadRuntimeStatus(true);
      await loadRunRecords(true);
    } catch {
      setError("后台持续处理暂时没有接上，请先刷新服务连接情况后再试。");
    } finally {
      setQueueBusyId("");
    }
  };

  const decideQueueTask = async (task: AgentQueueTask, decision: "approve" | "reject") => {
    const pendingIds = task.approvals.filter((item) => item.status === "pending").map((item) => item.id);
    if (!pendingIds.length) {
      Alert.alert("无需审批", "当前任务没有待审批动作。");
      return;
    }

    setQueueBusyId(`${decision}:${task.id}`);
    setError("");
    try {
      if (decision === "approve") {
        await api.approveAgentQueueTask({
          taskId: task.id,
          approvalIds: pendingIds,
          decidedBy: user?.id,
          comment: "已在移动端 cockpit 批准继续执行",
        });
      } else {
        await api.rejectAgentQueueTask({
          taskId: task.id,
          approvalIds: pendingIds,
          decidedBy: user?.id,
          comment: "已在移动端 cockpit 拒绝敏感动作",
        });
      }
      await loadQueueTasks(true);
      await loadRuntimeStatus(true);
      await loadRunRecords(true, task.run_id || selectedRunId || undefined);
      if ((task.payload.patient_id || patientId) && (task.payload.conversation_id || activeConversationId)) {
        await loadHistory(task.payload.conversation_id || activeConversationId);
      }
    } catch {
      setError(decision === "approve" ? "审批通过失败，请稍后重试。" : "拒绝动作失败，请稍后重试。");
    } finally {
      setQueueBusyId("");
    }
  };

  const createDocumentFromLatest = async () => {
    if (!lastAssistantSummary || !lastResolvedPatientId) {
      Alert.alert("暂无可落地结果", "请先发起一次 AI 对话并生成结果。");
      return;
    }
    try {
      const draft = await api.createDocumentDraft(lastResolvedPatientId, lastAssistantSummary, {
        templateName: "AI对话生成模板",
      });
      setLastCreatedDraftId(draft.id);
      Alert.alert("文书已生成", `草稿ID：${draft.id}\n位置：文书中心 > 草稿列表`);
    } catch {
      Alert.alert("生成失败", "文书草稿这一步暂时没接上。请先确认文书服务已启动，再重试。");
    }
  };

  const createOrderRequestFromLatest = async () => {
    if (!lastAssistantSummary || !lastResolvedPatientId || !user?.id) {
      Alert.alert("暂无可落地结果", "请先发起一次 AI 对话并生成结果。\n且需已登录。");
      return;
    }
    try {
      const order = await api.createOrderRequest({
        patientId: lastResolvedPatientId,
        requestedBy: user.id,
        title: "请医生核对 AI 推荐结论",
        details: `来源：AI对话推荐\n目标床位：${lastResolvedBedNo || "-"}\n结论摘要：\n${lastAssistantSummary}`,
        priority: "P2",
      });
      setLastCreatedOrderNo(order.order_no);
      Alert.alert("医嘱请求已生成", `单号：${order.order_no}\n位置：医嘱中心 > 当前医嘱`);
    } catch {
      Alert.alert("生成失败", "医嘱请求这一步暂时没接上。请先确认医嘱服务已启动，再重试。");
    }
  };

  const openConversation = async (conversationId: string) => {
    setWorkspaceView("history");
    setActiveConversationId(conversationId);
    if (patientId) {
      await loadHistory(conversationId);
      await loadRunRecords(true, undefined, conversationId);
    }
  };

  const renderWorkspacePane = () => {
    if (workspaceView === "result") {
      if (!hasResultWorkspace) {
        return (
          <View style={styles.emptyWorkspace}>
            <Text style={styles.emptyWorkspaceTitle}>输出会出现在这里</Text>
            <Text style={styles.emptyWorkspaceText}>先选病例，再输入任务。系统返回后这里只保留当前结论和最关键的后续动作。</Text>
          </View>
        );
      }

      return (
        <View style={styles.workspacePane}>
          {loading ? (
            <View style={styles.outputStateBox}>
              <Text style={styles.outputStateTitle}>正在生成结果</Text>
              <Text style={styles.outputStateText}>
                系统正在根据当前病例、输入内容和附件整理答案。这里不再显示假进度，完成后会直接刷新成结果。
              </Text>
            </View>
          ) : null}

          {!loading && error ? (
            <View style={styles.outputErrorBox}>
              <Text style={styles.outputErrorTitle}>这次没有顺利返回结果</Text>
              <Text style={styles.outputErrorText}>{error}</Text>
            </View>
          ) : null}

          {lastAssistantSummary ? (
            <View style={styles.resultHero}>
              <View style={styles.resultHeroHead}>
                <Text style={styles.resultHeroEyebrow}>当前结论</Text>
                <View style={styles.responseBadgeRow}>
                  {lastResolvedBedNo ? <StatusPill text={`${lastResolvedBedNo}床`} tone="success" /> : null}
                  {latestAssistantResponse ? (
                    <StatusPill
                      text={`把握度 ${(latestAssistantResponse.confidence * 100).toFixed(0)}%`}
                      tone={latestAssistantResponse.confidence >= 0.8 ? "success" : "warning"}
                    />
                  ) : null}
                </View>
              </View>
              <Text style={styles.resultHeroText}>{lastAssistantSummary}</Text>
              {(lastResolvedPatientId || lastResolvedBedNo) ? (
                <Text style={styles.resultHeroMeta}>
                  目标病例：{lastResolvedBedNo ? `${lastResolvedBedNo}床` : "-"} / {lastResolvedPatientId || "-"}
                </Text>
              ) : null}
            </View>
          ) : null}

          {(lastAssistantSummary || lastCreatedDraftId || lastCreatedOrderNo) ? (
            <View style={styles.resultActionBand}>
              <View style={styles.inlineSectionHead}>
                <View style={styles.runtimeTitleWrap}>
                  <Text style={styles.sectionTitle}>落地动作</Text>
                  <Text style={styles.runtimeLead}>把当前结果继续沉淀成文书、医嘱请求，或直接跳到对应中心处理。</Text>
                </View>
              </View>
              <View style={styles.rowWrap}>
                <ActionButton label="生成文书草稿" onPress={createDocumentFromLatest} variant="secondary" style={styles.flexHalf} />
                <ActionButton label="生成医嘱请求" onPress={createOrderRequestFromLatest} style={styles.flexHalf} />
              </View>
              <View style={styles.rowWrap}>
                <ActionButton
                  label="打开文书中心"
                  onPress={() => navigation.navigate("Document")}
                  variant="secondary"
                  style={styles.flexHalf}
                />
                <ActionButton
                  label="打开医嘱中心"
                  onPress={() => navigation.navigate("Orders")}
                  variant="secondary"
                  style={styles.flexHalf}
                />
              </View>
              {lastCreatedDraftId ? <Text style={styles.resultActionMeta}>文书草稿 ID：{lastCreatedDraftId}</Text> : null}
              {lastCreatedOrderNo ? <Text style={styles.resultActionMeta}>医嘱请求单号：{lastCreatedOrderNo}</Text> : null}
            </View>
          ) : null}

          {latestAssistantResponse ? (
            <View style={styles.workspaceEmbedded}>
              <ResponseDetails response={latestAssistantResponse} onInspectRun={inspectRun} />
            </View>
          ) : null}
        </View>
      );
    }

    if (workspaceView === "queue") {
      return (
        <View style={styles.workspacePane}>
          <View style={styles.queueSummaryRow}>
            <View style={styles.queueSummaryChip}>
              <Text style={styles.queueSummaryLabel}>值守状态</Text>
              <Text style={styles.queueSummaryValue}>
                {runtimeStatus?.task_queue?.worker_running
                  ? "运行中"
                  : runtimeStatus?.task_queue?.worker_enabled
                  ? "待机"
                  : "关闭"}
              </Text>
            </View>
            <View style={styles.queueSummaryChip}>
              <Text style={styles.queueSummaryLabel}>排队中</Text>
              <Text style={styles.queueSummaryValue}>{runtimeStatus?.task_queue?.queued || 0}</Text>
            </View>
            <View style={styles.queueSummaryChip}>
              <Text style={styles.queueSummaryLabel}>待确认</Text>
              <Text style={styles.queueSummaryValue}>{runtimeStatus?.task_queue?.waiting_approval || 0}</Text>
            </View>
            <View style={styles.queueSummaryChip}>
              <Text style={styles.queueSummaryLabel}>已完成</Text>
              <Text style={styles.queueSummaryValue}>{runtimeStatus?.task_queue?.completed || 0}</Text>
            </View>
          </View>

          <View style={styles.rowWrap}>
            <ActionButton
              label={queueLoading ? "同步中" : "刷新队列"}
              onPress={() => loadQueueTasks()}
              variant="secondary"
              style={styles.queueEnqueueAction}
              disabled={queueLoading || Boolean(queueBusyId)}
            />
          </View>

          <View style={styles.filterWrap}>
            {(["all", "waiting_approval", "running", "completed"] as const).map((item) => {
              const active = queueStatusFilter === item;
              return (
                <Pressable
                  key={item}
                  style={[styles.filterChip, active && styles.filterChipActive]}
                  onPress={() => setQueueStatusFilter(item)}
                >
                  <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>{QUEUE_FILTER_LABEL[item]}</Text>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.filterWrap}>
            {(["all", "observe", "escalate", "document", "full_loop"] as const).map((item) => {
              const active = queueProfileFilter === item;
              const label = item === "all" ? "全部姿态" : EXECUTION_PROFILE_META[item].label;
              return (
                <Pressable
                  key={item}
                  style={[styles.filterChip, active && styles.filterChipActive]}
                  onPress={() => setQueueProfileFilter(item)}
                >
                  <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>{label}</Text>
                </Pressable>
              );
            })}
          </View>

          {visibleQueueTasks.length === 0 ? (
            <Text style={styles.tip}>当前病例或当前会话下还没有后台任务，适合把需要持续跟进或等待审批的动作排入队列。</Text>
          ) : (
            <View style={styles.queueList}>
              {visibleQueueTasks.map((task) => {
                const pendingApprovals = task.approvals.filter((item) => item.status === "pending");
                const busyApprove = queueBusyId === `approve:${task.id}`;
                const busyReject = queueBusyId === `reject:${task.id}`;
                return (
                  <View key={task.id} style={styles.queueItem}>
                    <View style={styles.queueHead}>
                      <View style={styles.queueHeadText}>
                        <Text style={styles.queueTitle}>
                          {task.payload.mission_title || task.summary || formatWorkflowLabel(task.workflow_type)}
                        </Text>
                        <Text style={styles.queueMeta}>
                          {formatWorkflowLabel(task.workflow_type)} ·{" "}
                          {task.payload.bed_no ? `${task.payload.bed_no}床` : task.payload.patient_id || "未绑定病例"}
                        </Text>
                      </View>
                      <StatusPill text={formatQueueStatus(task.status)} tone={queueStatusTone(task.status)} />
                    </View>

                    {task.payload.user_input ? <Text style={styles.queuePrompt}>{formatAiText(task.payload.user_input)}</Text> : null}

                    {task.payload.mission_title || task.payload.success_criteria?.length ? (
                      <View style={styles.queueOutputBox}>
                        <Text style={styles.detailLabel}>任务说明</Text>
                        {task.payload.mission_title ? <Text style={styles.queueOutputText}>{task.payload.mission_title}</Text> : null}
                        {task.payload.success_criteria?.length ? (
                          <View style={styles.actionChipWrap}>
                            {task.payload.success_criteria.map((item, index) => (
                              <View key={`${task.id}-criteria-${index}`} style={styles.actionChip}>
                                <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
                              </View>
                            ))}
                          </View>
                        ) : null}
                      </View>
                    ) : null}

                    <Text style={styles.queueMeta}>
                      处理方式 {formatExecutionProfileLabel(task.payload.execution_profile)} · 执行方式{" "}
                      {formatAgentModeLabel(task.payload.agent_mode)}
                    </Text>
                    {task.payload.operator_notes ? <Text style={styles.queueMeta}>操作备注：{task.payload.operator_notes}</Text> : null}

                    <Text style={styles.queueMeta}>
                      更新时间 {new Date(task.updated_at).toLocaleString()} · 尝试 {task.attempt_count} 次 · 恢复 {task.resume_count} 次
                    </Text>

                    {(task.runtime_engine || task.requested_engine || task.run_id) ? (
                      <Text style={styles.queueMeta}>
                        处理引擎 {formatEngineLabel(task.runtime_engine || task.requested_engine)} · 处理编号 {task.run_id || "-"}
                      </Text>
                    ) : null}

                    {task.run_id ? (
                      <View style={styles.rowWrap}>
                        <ActionButton
                          label="查看过程"
                          onPress={() => inspectRun(task.run_id!)}
                          variant="secondary"
                          style={styles.actionMini}
                          disabled={runLoading}
                        />
                      </View>
                    ) : null}

                    {pendingApprovals.length > 0 ? (
                      <View style={styles.detailSection}>
                        <Text style={styles.detailLabel}>待审批动作</Text>
                        {pendingApprovals.map((item) => (
                          <View key={item.id} style={styles.queueApprovalItem}>
                            <View style={styles.artifactHead}>
                              <Text style={styles.artifactTitle}>{formatAiText(item.title)}</Text>
                              <StatusPill text="待审批" tone="warning" />
                            </View>
                            {item.reason ? <Text style={styles.artifactSummary}>{item.reason}</Text> : null}
                          </View>
                        ))}
                        <View style={styles.rowWrap}>
                          <ActionButton
                            label={busyApprove ? "批准中" : "批准继续"}
                            onPress={() => decideQueueTask(task, "approve")}
                            style={styles.flexHalf}
                            disabled={busyApprove || busyReject}
                          />
                          <ActionButton
                            label={busyReject ? "处理中" : "拒绝动作"}
                            onPress={() => decideQueueTask(task, "reject")}
                            variant="danger"
                            style={styles.flexHalf}
                            disabled={busyApprove || busyReject}
                          />
                        </View>
                      </View>
                    ) : null}

                    {task.last_output?.summary ? (
                      <View style={styles.queueOutputBox}>
                        <Text style={styles.detailLabel}>最新结果</Text>
                        <Text style={styles.queueOutputText}>{task.last_output.summary}</Text>
                        {task.last_output.next_actions.length > 0 ? (
                          <View style={styles.actionChipWrap}>
                            {task.last_output.next_actions.slice(0, 3).map((item, index) => (
                              <View key={`${task.id}-${index}`} style={styles.actionChip}>
                                <Text style={styles.actionChipText}>{formatAiText(item)}</Text>
                              </View>
                            ))}
                          </View>
                        ) : null}
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </View>
          )}
        </View>
      );
    }

    if (workspaceView === "runs") {
      return (
        <View style={styles.workspacePane}>
          {runRecords.length > 0 ? (
            <ScrollView
              horizontal
              style={styles.folderList}
              contentContainerStyle={styles.folderListContent}
              showsHorizontalScrollIndicator={false}
            >
              {runRecords.map((run) => {
                const active = run.id === selectedRunId;
                return (
                  <Pressable key={run.id} style={[styles.runChip, active && styles.runChipActive]} onPress={() => inspectRun(run.id)}>
                    <Text style={[styles.runChipTitle, active && styles.runChipTitleActive]} numberOfLines={1}>
                      {run.request.mission_title ||
                        `${run.bed_no ? `${run.bed_no}床` : run.patient_id || "本次处理"} · ${formatWorkflowLabel(run.workflow_type)}`}
                    </Text>
                    <Text style={styles.runChipMeta} numberOfLines={1}>
                      {run.bed_no ? `${run.bed_no}床 · ` : ""}
                      {formatExecutionProfileLabel(run.request.execution_profile)} · {formatQueueStatus(run.status)}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          ) : (
            <Text style={styles.tip}>当前没有可回看的处理记录。发起一次对话或后台任务后，这里会显示每次处理的详细过程。</Text>
          )}

          {selectedRun ? (
            <View style={styles.workspaceEmbedded}>
              <RunInspector run={selectedRun} onRetry={() => retryRun(selectedRun.id)} retrying={retryBusyId === selectedRun.id} />
            </View>
          ) : null}
        </View>
      );
    }

    if (workspaceView === "history") {
      return (
        <View style={styles.workspacePane}>
          <View style={styles.headActions}>
            <ActionButton label="新建对话" onPress={createConversation} variant="secondary" style={styles.actionMini} />
            <ActionButton label="刷新历史" onPress={() => loadHistory(activeConversationId)} variant="secondary" style={styles.actionMini} />
          </View>

          {folders.length > 0 ? (
            <ScrollView
              horizontal
              style={styles.folderList}
              contentContainerStyle={styles.folderListContent}
              showsHorizontalScrollIndicator={false}
            >
              {folders.map((folder) => {
                const active = folder.id === activeConversationId;
                return (
                  <Pressable
                    key={folder.id}
                    style={[styles.folderChip, active && styles.folderChipActive]}
                    onPress={() => openConversation(folder.id)}
                  >
                    <Text style={[styles.folderTitle, active && styles.folderTitleActive]} numberOfLines={1}>
                      {folder.title}
                    </Text>
                    <Text style={styles.folderMeta} numberOfLines={1}>
                      {folder.count}条 · {new Date(folder.latestAt).toLocaleString()}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          ) : (
            <Text style={styles.tip}>暂无会话，请先点击“新建对话”或直接提问。</Text>
          )}

          {historyLoading ? <Text style={styles.tip}>正在同步历史...</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {messages.length === 0 ? <Text style={styles.tip}>暂无消息，开始你的第一个问题。</Text> : null}

          <View style={styles.historyViewport}>
            <ScrollView style={styles.chatList} nestedScrollEnabled>
              {messages.map((msg) => (
                <View key={msg.id} style={[styles.bubble, msg.role === "user" ? styles.userBubble : styles.assistantBubble]}>
                  <Text style={[styles.bubbleTag, msg.role === "user" ? styles.userTag : styles.assistantTag]}>
                    {msg.role === "user" ? "我" : "AI"} · {MODE_LABEL[msg.mode]}
                  </Text>
                  <Text style={styles.bubbleText}>{formatAiText(msg.text)}</Text>
                  <Text style={styles.bubbleTime}>{new Date(msg.timestamp).toLocaleString()}</Text>
                  {msg.response ? <ResponseDetails response={msg.response} onInspectRun={inspectRun} /> : null}
                </View>
              ))}
            </ScrollView>
          </View>
        </View>
      );
    }

    return (
      <View style={styles.workspacePane}>
        <View style={styles.systemStrip}>
          {runtimeCapabilities.map((item) => (
            <View key={item.label} style={styles.systemStripItem}>
              <Text style={styles.systemStripLabel}>{item.label}</Text>
              <Text style={styles.systemStripValue}>{item.status}</Text>
            </View>
          ))}
        </View>

        <View style={styles.runtimeGrid}>
          <View style={styles.runtimeMetric}>
            <Text style={styles.runtimeMetricLabel}>默认处理方式</Text>
            <Text style={styles.runtimeMetricValue}>{formatEngineLabel(runtimeStatus?.configured_engine)}</Text>
            <Text style={styles.runtimeMetricNote}>
              当前实际使用：{formatEngineLabel(runtimeStatus?.active_engine)}
              {runtimeStatus?.override_enabled ? " · 已手动切换" : " · 按系统默认"}
            </Text>
          </View>
          <View style={styles.runtimeMetric}>
            <Text style={styles.runtimeMetricLabel}>自动安排下一步</Text>
            <Text style={styles.runtimeMetricValue}>{runtimeStatus?.planner_llm_enabled ? "已开启" : "先按标准流程"}</Text>
            <Text style={styles.runtimeMetricNote}>
              最多安排 {runtimeStatus?.planner_max_steps || 0} 步 · 响应慢时会自动回到稳妥方式
            </Text>
          </View>
          <View style={styles.runtimeMetric}>
            <Text style={styles.runtimeMetricLabel}>基础回答</Text>
            <Text style={styles.runtimeMetricValue}>{runtimeStatus?.local_model_service_reachable ? "已连接" : "未连接"}</Text>
            <Text style={styles.runtimeMetricNote}>{runtimeModelSummary}</Text>
          </View>
          <View style={styles.runtimeMetric}>
            <Text style={styles.runtimeMetricLabel}>后台持续处理</Text>
            <Text style={styles.runtimeMetricValue}>{runtimeStatus?.task_queue?.queued || 0}</Text>
            <Text style={styles.runtimeMetricNote}>
              运行中 {runtimeStatus?.task_queue?.running || 0} · 待审批 {runtimeStatus?.task_queue?.waiting_approval || 0}
            </Text>
          </View>
        </View>

        {runtimeFallbackText ? <Text style={styles.runtimeWarning}>{runtimeFallbackText}</Text> : null}

        <View style={styles.systemNoteBlock}>
          <Text style={styles.detailLabel}>现在能帮你做什么</Text>
          <Text style={styles.runtimeAliasText}>{runtimeCapabilitySummary}</Text>
        </View>

        {runtimeStatus?.approval_required_tools?.length ? (
          <View style={styles.systemNoteBlock}>
            <Text style={styles.detailLabel}>需要人工确认的动作</Text>
            <Text style={styles.runtimeAliasText}>
              {runtimeStatus.approval_required_tools.map(formatApprovalToolLabel).join(" · ")}
            </Text>
          </View>
        ) : null}

        <View style={styles.runtimeActionRow}>
          <ActionButton
            label={runtimeLoading ? "刷新中" : "刷新服务连接"}
            onPress={() => loadRuntimeStatus()}
            variant="secondary"
            style={styles.runtimeAction}
            disabled={runtimeLoading || Boolean(runtimeBusy)}
          />
          <ActionButton
            label={runtimeBusy === "langgraph" ? "切换中" : "切到深度分析"}
            onPress={() => switchRuntimeEngine("langgraph")}
            variant="secondary"
            style={styles.runtimeAction}
            disabled={runtimeLoading || runtimeBusy === "langgraph"}
          />
          <ActionButton
            label={runtimeBusy === "state_machine" ? "切换中" : "切回稳妥模式"}
            onPress={() => switchRuntimeEngine("state_machine")}
            variant="secondary"
            style={styles.runtimeAction}
            disabled={runtimeLoading || runtimeBusy === "state_machine"}
          />
          <ActionButton
            label={runtimeBusy === "clear" ? "恢复中" : "恢复默认设置"}
            onPress={clearRuntimeOverride}
            variant="secondary"
            style={styles.runtimeAction}
            disabled={runtimeLoading || runtimeBusy === "clear" || !runtimeStatus?.override_enabled}
          />
        </View>

        <View style={styles.systemCapabilityBlock}>
          <View style={styles.inlineSectionHead}>
            <View style={styles.runtimeTitleWrap}>
              <Text style={styles.sectionTitle}>处理方式与系统能力</Text>
              <Text style={styles.runtimeLead}>这里保留细颗粒度能力切换；主工作区只保留最常用的信息与动作。</Text>
            </View>
            <StatusPill text={MODE_LABEL[mode]} tone="info" />
          </View>

          <View style={styles.modeRow}>
            {(["single_model", "agent_cluster"] as AIChatMode[]).map((item) => {
              const active = item === mode;
              return (
                <Pressable key={item} style={[styles.modeBtn, active && styles.modeBtnActive]} onPress={() => setMode(item)}>
                  <Text style={[styles.modeText, active && styles.modeTextActive]}>{MODE_LABEL[item]}</Text>
                </Pressable>
              );
            })}
          </View>

          {mode === "single_model" ? (
            <View style={styles.blockGap}>
              <Text style={styles.subTitle}>快速回答能力</Text>
              <View style={styles.chipWrap}>
                {models.map((model) => {
                  const active = model.id === selectedModel;
                  const fallback = MODEL_FALLBACK[model.id];
                  return (
                    <Pressable
                      key={model.id}
                      onPress={() => setSelectedModel(model.id)}
                      style={[styles.modelChip, active && styles.modelChipActive]}
                    >
                      <Text style={[styles.modelChipTitle, active && styles.modelChipTitleActive]}>
                        {fallback?.name || model.name}
                      </Text>
                      <Text style={styles.modelChipDesc}>{fallback?.description || model.description}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ) : (
            <View style={styles.blockGap}>
              <Text style={styles.subTitle}>系统这次怎么帮你</Text>
              <View style={styles.clusterRow}>
                {clusters.map((cluster) => {
                  const active = cluster.id === selectedCluster;
                  const clusterName = CLUSTER_FALLBACK[cluster.id] || cluster.name;
                  return (
                    <Pressable
                      key={cluster.id}
                      onPress={() => setSelectedCluster(cluster.id)}
                      style={[styles.clusterBtn, active && styles.clusterBtnActive]}
                    >
                      <Text style={[styles.clusterName, active && styles.clusterNameActive]}>{clusterName}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={styles.mainModel}>当前基础回答：{activeCluster?.main_model || "基础整理（本地）"}</Text>
              <Text style={styles.tip}>
                {activeCluster?.description || "系统会先整理重点，再排处理顺序；遇到复杂情况时再做一轮核对。"}
              </Text>
              {activeClusterTasks.map((task) => {
                const fallback = TASK_FALLBACK[task.model_id];
                return (
                  <View key={`${task.model_id}-${task.role}`} style={styles.taskRow}>
                    <Text style={styles.taskModel}>{fallback?.modelName || task.model_name}</Text>
                    <Text style={styles.taskText}>
                      {fallback?.role || task.role} · {fallback?.task || task.task} ·{" "}
                      {task.enabled
                        ? ["care-planner", "care-memory", "funasr-local", "cosyvoice-local", "care-critic"].includes(task.model_id)
                          ? "系统自带，无需额外启动"
                          : "已单独启动"
                        : task.model_id === "qwen3-8b-local-planner" || task.model_id === "deepseek-r1-local"
                        ? primaryReady
                          ? "暂未单独开启，先由基础整理代做"
                          : "未启动"
                        : task.model_id === "medgemma-local"
                        ? multimodalReady
                          ? "查看附件时可直接使用"
                          : "附件专用能力未开启，先不处理附件"
                        : "未启动"}
                    </Text>
                  </View>
                );
              })}
            </View>
          )}
        </View>
      </View>
    );
  };

  return (
    <ScreenShell
      title="智能方案推荐"
      subtitle={
        selectedPatient
          ? `当前病例：${patientDisplayName}（${selectedPatient.id}）`
          : "页面只保留三块：选病例、输任务、看结果。先选病例，再决定由 AI Agent 还是单个模型处理。"
      }
      rightNode={
        <View style={styles.headerPillStack}>
          <StatusPill text={loading ? "处理中" : activeInputEngine?.label || MODE_LABEL[mode]} tone={loading ? "warning" : "info"} />
          <StatusPill text={profileMeta.label} tone={executionProfileTone(executionProfile)} />
        </View>
      }
    >
      <AnimatedBlock delay={30}>
        <SurfaceCard style={styles.stackPanel}>
          <View style={styles.moduleHead}>
            <View style={styles.moduleStep}>
              <Text style={styles.moduleStepText}>1</Text>
            </View>
            <View style={styles.moduleTextWrap}>
              <Text style={styles.moduleTitle}>选病例</Text>
              <Text style={styles.moduleSubtext}>先锁定病例，后面的输入和输出都围绕这一位患者展开。</Text>
            </View>
            <Pressable style={styles.selectorToggle} onPress={() => setSelectorExpanded((prev) => !prev)}>
              <Text style={styles.inlineExpandText}>
                {selectorExpanded ? "收起列表" : selectedPatient ? "切换病例" : "展开列表"}
              </Text>
            </Pressable>
          </View>

          {selectedPatient ? (
            <View style={styles.patientSummaryCard}>
              <View style={styles.patientSummaryHead}>
                <View style={styles.moduleTextWrap}>
                  <Text style={styles.patientSummaryTitle}>{patientDisplayName}</Text>
                  <Text style={styles.patientSummaryMeta}>
                    {patientContext?.bed_no ? `${patientContext.bed_no}床` : selectedPatient.id} ·{" "}
                    {(patientContext?.diagnoses || []).slice(0, 2).join(" · ") || "等待同步诊断"}
                  </Text>
                </View>
                <StatusPill
                  text={contextLoading ? "同步中" : patientContext?.bed_no ? `${patientContext.bed_no}床` : "已选中"}
                  tone={contextLoading ? "warning" : "success"}
                />
              </View>

              <View style={styles.patientMetricGrid}>
                <View style={styles.patientMetricBox}>
                  <Text style={styles.patientMetricLabel}>异常观察</Text>
                  <Text style={styles.patientMetricValue}>
                    {(abnormalObservations.length ? abnormalObservations : patientContext?.latest_observations || []).length}
                  </Text>
                </View>
                <View style={styles.patientMetricBox}>
                  <Text style={styles.patientMetricLabel}>待办任务</Text>
                  <Text style={styles.patientMetricValue}>{patientContext?.pending_tasks.length || 0}</Text>
                </View>
                <View style={styles.patientMetricBox}>
                  <Text style={styles.patientMetricLabel}>临近医嘱</Text>
                  <Text style={styles.patientMetricValue}>
                    {(patientOrders?.stats?.due_30m || 0) + (patientOrders?.stats?.overdue || 0)}
                  </Text>
                </View>
              </View>

              <View style={styles.actionChipWrap}>
                {(patientContext?.risk_tags || []).slice(0, 3).map((item, index) => (
                  <View key={`${formatAiText(item)}-${index}`} style={styles.riskChip}>
                    <Text style={styles.riskChipText}>{formatAiText(item)}</Text>
                  </View>
                ))}
                {(patientContext?.pending_tasks || []).slice(0, 2).map((item, index) => (
                  <View key={`${formatAiText(item)}-${index}`} style={styles.pendingChip}>
                    <Text style={styles.pendingChipText}>{formatAiText(item)}</Text>
                  </View>
                ))}
              </View>

              <Text style={styles.moduleSubtext}>
                {(abnormalObservations.length ? abnormalObservations : patientContext?.latest_observations || [])
                  .slice(0, 2)
                  .map((item) => `${item.name}${item.value ? ` ${item.value}` : ""}`)
                  .join(" · ") || "当前还没有同步到明确异常观察。"}
              </Text>
            </View>
          ) : (
            <View style={styles.emptySelectionPanel}>
              <Text style={styles.emptySelectionTitle}>还没有锁定病例</Text>
              <Text style={styles.emptySelectionText}>你可以先从下方选病例，也可以直接输入“23床...”让系统按床号定位。</Text>
            </View>
          )}

          {selectorExpanded ? (
            <View style={styles.selectorWrap}>
              <PatientCaseSelector
                departmentId={departmentId}
                selectedPatient={selectedPatient}
                onSelectPatient={setSelectedPatient}
                onCasesUpdated={setCaseBeds}
                embedded
              />
            </View>
          ) : null}
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={56}>
        <SurfaceCard style={styles.stackPanel}>

          <View style={styles.moduleHead}>
            <View style={styles.moduleStep}>
              <Text style={styles.moduleStepText}>2</Text>
            </View>
            <View style={styles.moduleTextWrap}>
              <Text style={styles.moduleTitle}>输入</Text>
              <Text style={styles.moduleSubtext}>先选 AI Agent 或单个模型，再输入这次要处理的任务。</Text>
            </View>
            <StatusPill text={formatExecutionProfileLabel(executionProfile)} tone={executionProfileTone(executionProfile)} />
          </View>

          <View style={styles.inputControlGrid}>
            <View style={styles.blockGap}>
              <Text style={styles.detailLabel}>回答方式</Text>
              <Pressable style={styles.dropdownTrigger} onPress={() => setEngineMenuOpen((prev) => !prev)}>
                <View style={styles.dropdownLabelBlock}>
                  <Text style={styles.dropdownValue}>{activeInputEngine?.label || "选择方式"}</Text>
                  <Text style={styles.dropdownMeta}>{activeInputEngine?.detail || "选择 AI Agent 或一个单模型"}</Text>
                </View>
                <Text style={styles.dropdownCaret}>{engineMenuOpen ? "收起" : "展开"}</Text>
              </Pressable>

              {engineMenuOpen ? (
                <View style={styles.dropdownMenu}>
                  {inputEngineOptions.map((item) => {
                    const active = mode === item.mode && (item.mode === "agent_cluster" || item.modelId === selectedModel);
                    return (
                      <Pressable
                        key={item.key}
                        style={[styles.dropdownOption, active && styles.dropdownOptionActive]}
                        onPress={() => {
                          if (item.mode === "agent_cluster") {
                            setMode("agent_cluster");
                            if (!clusters.some((cluster) => cluster.id === selectedCluster) && clusters[0]?.id) {
                              setSelectedCluster(clusters[0].id);
                            }
                          } else if (item.modelId) {
                            setMode("single_model");
                            setSelectedModel(item.modelId);
                          }
                          setEngineMenuOpen(false);
                        }}
                      >
                        <Text style={[styles.dropdownOptionTitle, active && styles.dropdownOptionTitleActive]}>{item.label}</Text>
                        <Text style={[styles.dropdownOptionMeta, active && styles.dropdownOptionMetaActive]}>{item.detail}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              ) : null}
            </View>

            <View style={styles.blockGap}>
              <Text style={styles.detailLabel}>任务类型</Text>
              <View style={styles.profileRail}>
                {(Object.keys(EXECUTION_PROFILE_META) as AIExecutionProfile[]).map((item) => {
                  const active = executionProfile === item;
                  return (
                    <Pressable
                      key={item}
                      style={[styles.profileChip, active && styles.profileChipActive]}
                      onPress={() => setExecutionProfile(item)}
                    >
                      <Text style={[styles.profileChipLabel, active && styles.profileChipLabelActive]}>
                        {EXECUTION_PROFILE_META[item].label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={styles.tip}>{profileMeta.summary}</Text>
              <Text style={styles.tip}>{runtimeModelSummary}</Text>
            </View>
          </View>

          <View style={styles.inputBriefBox}>
            <Text style={styles.detailLabel}>本次默认任务</Text>
            <Text style={styles.moduleSubtext}>{resolvedMissionTitle}</Text>
            <Text style={styles.tip}>{resolvedSuccessCriteria.slice(0, 3).join(" · ")}</Text>
          </View>

          <View style={styles.quickPromptWrap}>
            {quickPrompts.map((item, index) => (
              <Pressable key={`${formatAiText(item)}-${index}`} style={styles.quickPromptChip} onPress={() => applyPromptPreset(item)}>
                <Text style={styles.quickPromptText}>{formatAiText(item)}</Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.missionField}>
            <Text style={styles.detailLabel}>补充要求（可选）</Text>
            <TextInput
              value={missionNotes}
              onChangeText={setMissionNotes}
              placeholder="例如：先给我风险排序，再决定是否需要上报医生。"
              placeholderTextColor={colors.subText}
              multiline
              textAlignVertical="top"
              style={[styles.missionInput, styles.missionTextArea]}
            />
          </View>

          <View style={styles.attachRow}>
            <ActionButton label="添加图片" onPress={pickImage} variant="secondary" style={styles.attachBtn} />
            <ActionButton label="添加文件" onPress={pickDocument} variant="secondary" style={styles.attachBtn} />
            <ActionButton label={`清空附件(${attachments.length})`} onPress={() => setAttachments([])} variant="secondary" style={styles.attachBtn} />
          </View>

          {attachments.length > 0 ? (
            <View style={styles.fileList}>
              {attachments.map((item, index) => (
                <Text key={`${item.name}-${index}`} style={styles.fileItem}>
                  • {item.name}
                </Text>
              ))}
            </View>
          ) : (
            <Text style={styles.tip}>支持语音、文字和附件混合输入。若你直接输入“23床...”，系统会优先按床号定位病例。</Text>
          )}

          <View style={styles.workspaceEmbedded}>
            <VoiceTextInput
              value={question}
              onChangeText={setQuestion}
              onSubmit={send}
              placeholder="请输入想让系统处理的问题"
              embedded
              disabled={loading}
              submitLabel={loading ? "处理中" : "发送"}
              hideTip
            />
          </View>

          <View style={styles.queueActionRow}>
            <ActionButton
              label={queueBusyId === "enqueue" ? "排队中" : "后台持续跟进"}
              onPress={enqueueCurrentTask}
              variant="secondary"
              style={styles.queueEnqueueAction}
              disabled={loading || mode !== "agent_cluster" || !question.trim() || queueBusyId === "enqueue"}
            />
          </View>
          {mode !== "agent_cluster" ? <Text style={styles.tip}>后台持续跟进仅在 AI Agent 模式下可用。</Text> : null}
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={82}>
        <SurfaceCard style={styles.stackPanel}>
          <View style={styles.moduleHead}>
            <View style={styles.moduleStep}>
              <Text style={styles.moduleStepText}>3</Text>
            </View>
            <View style={styles.moduleTextWrap}>
              <Text style={styles.moduleTitle}>输出</Text>
              <Text style={styles.moduleSubtext}>结果、历史、持续任务和系统状态都收在这一块里，不再散开显示。</Text>
            </View>
            <StatusPill
              text={
                loading
                  ? "正在生成"
                  : error
                  ? "需要重试"
                  : lastAssistantSummary
                  ? "已返回"
                  : workspaceTabs.find((item) => item.key === workspaceView)?.label || "等待输入"
              }
              tone={loading ? "warning" : error ? "danger" : lastAssistantSummary ? "success" : "info"}
            />
          </View>

          {error && workspaceView !== "result" ? (
            <View style={styles.workspaceInfoBanner}>
              <Text style={styles.workspaceInfoText}>{error}</Text>
            </View>
          ) : null}

          <ScrollView
            horizontal
            style={styles.workspaceTabs}
            contentContainerStyle={styles.folderListContent}
            showsHorizontalScrollIndicator={false}
          >
            {workspaceTabs.map((item) => {
              const active = workspaceView === item.key;
              return (
                <Pressable
                  key={item.key}
                  style={[styles.workspaceTab, active && styles.workspaceTabActive]}
                  onPress={() => setWorkspaceView(item.key)}
                >
                  <Text style={[styles.workspaceTabLabel, active && styles.workspaceTabLabelActive]}>{item.label}</Text>
                  {item.count > 0 ? (
                    <View style={[styles.workspaceTabCount, active && styles.workspaceTabCountActive]}>
                      <Text style={[styles.workspaceTabCountText, active && styles.workspaceTabCountTextActive]}>{item.count}</Text>
                    </View>
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>

          <View style={styles.workspaceViewport}>{renderWorkspacePane()}</View>
        </SurfaceCard>
      </AnimatedBlock>
    </ScreenShell>
  );
}
const styles = StyleSheet.create({
  stackPanel: {
    backgroundColor: "#fbfdff",
    borderColor: "#d7e1ea",
    gap: 14,
  },
  moduleHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
  },
  moduleStep: {
    width: 28,
    height: 28,
    borderRadius: 999,
    backgroundColor: "#e9f0ff",
    alignItems: "center",
    justifyContent: "center",
  },
  moduleStepText: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: "800",
  },
  moduleTextWrap: {
    flex: 1,
    gap: 3,
  },
  moduleTitle: {
    color: colors.text,
    fontSize: 17,
    fontWeight: "800",
  },
  moduleSubtext: {
    color: colors.subText,
    fontSize: 12.8,
    lineHeight: 19,
  },
  patientSummaryCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#dbe6f1",
    backgroundColor: "#f5f9fe",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 10,
  },
  patientSummaryHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  patientSummaryTitle: {
    color: colors.primary,
    fontSize: 19,
    fontWeight: "800",
  },
  patientSummaryMeta: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  patientMetricGrid: {
    flexDirection: "row",
    gap: 8,
  },
  patientMetricBox: {
    flex: 1,
    borderRadius: 14,
    backgroundColor: "#ffffff",
    paddingVertical: 10,
    paddingHorizontal: 10,
    gap: 2,
  },
  patientMetricLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
  },
  patientMetricValue: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: "800",
  },
  inputControlGrid: {
    gap: 12,
  },
  dropdownTrigger: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    borderWidth: 1,
    borderColor: "#d8e2ec",
    borderRadius: 16,
    backgroundColor: "#ffffff",
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  dropdownLabelBlock: {
    flex: 1,
    gap: 2,
  },
  dropdownValue: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "800",
  },
  dropdownMeta: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  dropdownCaret: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "700",
  },
  dropdownMenu: {
    marginTop: 8,
    borderWidth: 1,
    borderColor: "#d8e2ec",
    borderRadius: 16,
    backgroundColor: "#ffffff",
    overflow: "hidden",
  },
  dropdownOption: {
    paddingVertical: 11,
    paddingHorizontal: 14,
    gap: 2,
    borderTopWidth: 1,
    borderTopColor: "#edf2f7",
  },
  dropdownOptionActive: {
    backgroundColor: "#edf3ff",
  },
  dropdownOptionTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  dropdownOptionTitleActive: {
    color: colors.primary,
  },
  dropdownOptionMeta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 17,
  },
  dropdownOptionMetaActive: {
    color: "#456497",
  },
  inputBriefBox: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#dbe6f0",
    backgroundColor: "#f7fbff",
    paddingVertical: 12,
    paddingHorizontal: 14,
    gap: 4,
  },
  outputStateBox: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#dce6f1",
    backgroundColor: "#f6f9fd",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 6,
  },
  outputStateTitle: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: "800",
  },
  outputStateText: {
    color: colors.subText,
    fontSize: 13,
    lineHeight: 19,
  },
  outputErrorBox: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#f2d0c9",
    backgroundColor: "#fff6f3",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 6,
  },
  outputErrorTitle: {
    color: colors.danger,
    fontSize: 16,
    fontWeight: "800",
  },
  outputErrorText: {
    color: "#9d4332",
    fontSize: 13,
    lineHeight: 19,
  },
  headerPillStack: {
    gap: 6,
    alignItems: "flex-end",
  },
  commandDeck: {
    backgroundColor: "#fbfdff",
    borderColor: "#d6e0ea",
    gap: 18,
  },
  deckHero: {
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#d8e4f0",
    backgroundColor: "#edf4fb",
    paddingVertical: 16,
    paddingHorizontal: 16,
    gap: 16,
  },
  deckHeroCopy: {
    gap: 6,
  },
  deckEyebrow: {
    color: colors.secondary,
    fontSize: 11.5,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  deckTitle: {
    color: colors.primary,
    fontSize: 27,
    lineHeight: 33,
    fontWeight: "800",
  },
  deckBody: {
    color: colors.subText,
    fontSize: 13.5,
    lineHeight: 20,
  },
  deckStatGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  deckStat: {
    flex: 1,
    minWidth: "23%",
    borderRadius: 14,
    backgroundColor: "#ffffff",
    paddingVertical: 10,
    paddingHorizontal: 10,
    gap: 4,
  },
  deckStatLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  deckStatValue: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: "800",
  },
  deckDivider: {
    height: 1,
    backgroundColor: "#e2eaf2",
  },
  deckSection: {
    gap: 12,
  },
  inlineSectionHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  inlineSectionNote: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  selectorToggle: {
    alignSelf: "flex-start",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d8e3ef",
    backgroundColor: "#ffffff",
    paddingVertical: 7,
    paddingHorizontal: 12,
  },
  selectorWrap: {
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: "#e3ebf3",
    paddingTop: 12,
  },
  emptySelectionPanel: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#dbe6f0",
    backgroundColor: "#f8fbfe",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 6,
  },
  emptySelectionTitle: {
    color: colors.primary,
    fontSize: 17,
    fontWeight: "800",
  },
  emptySelectionText: {
    color: colors.subText,
    fontSize: 13,
    lineHeight: 19,
  },
  profileRail: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  profileChip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d8e1ec",
    backgroundColor: "#ffffff",
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  profileChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  profileChipLabel: {
    color: colors.subText,
    fontSize: 12.5,
    fontWeight: "700",
  },
  profileChipLabelActive: {
    color: colors.primary,
  },
  workspaceShell: {
    backgroundColor: "#f8fbfd",
    borderColor: "#d8e1e9",
    gap: 12,
  },
  workspaceHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  workspaceTabs: {
    marginTop: 2,
    marginBottom: 2,
  },
  workspaceTab: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#ffffff",
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  workspaceTabActive: {
    borderColor: colors.primary,
    backgroundColor: "#edf3ff",
  },
  workspaceTabLabel: {
    color: colors.subText,
    fontSize: 12.5,
    fontWeight: "700",
  },
  workspaceTabLabelActive: {
    color: colors.primary,
  },
  workspaceTabCount: {
    minWidth: 20,
    height: 20,
    borderRadius: 999,
    backgroundColor: "#eef2f7",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
  },
  workspaceTabCountActive: {
    backgroundColor: "#dbe7ff",
  },
  workspaceTabCountText: {
    color: colors.subText,
    fontSize: 11,
    fontWeight: "800",
  },
  workspaceTabCountTextActive: {
    color: colors.primary,
  },
  workspaceViewport: {
    marginTop: 2,
  },
  workspaceInfoBanner: {
    borderRadius: 12,
    backgroundColor: "#fff5e8",
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  workspaceInfoText: {
    color: colors.warning,
    fontSize: 12.5,
    fontWeight: "700",
    lineHeight: 18,
  },
  workspacePane: {
    gap: 12,
  },
  workspaceEmbedded: {
    gap: 8,
  },
  emptyWorkspace: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#dce6ef",
    backgroundColor: "#f7fafc",
    paddingVertical: 18,
    paddingHorizontal: 16,
    gap: 8,
  },
  emptyWorkspaceTitle: {
    color: colors.primary,
    fontSize: 17,
    fontWeight: "800",
  },
  emptyWorkspaceText: {
    color: colors.subText,
    fontSize: 13.5,
    lineHeight: 20,
  },
  resultHero: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#d6e5f4",
    backgroundColor: "#edf5ff",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 10,
  },
  resultHeroHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10,
  },
  resultHeroEyebrow: {
    color: colors.secondary,
    fontSize: 11.5,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  resultHeroText: {
    color: colors.primary,
    fontSize: 18,
    lineHeight: 26,
    fontWeight: "800",
  },
  resultHeroMeta: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  resultActionBand: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#dbe5ef",
    backgroundColor: "#ffffff",
    paddingVertical: 12,
    paddingHorizontal: 12,
    gap: 10,
  },
  resultActionMeta: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "700",
  },
  historyViewport: {
    maxHeight: 560,
    borderRadius: 16,
    backgroundColor: "#f7fafc",
    padding: 8,
  },
  systemStrip: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  systemStripItem: {
    flex: 1,
    minWidth: "30%",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#dbe4ed",
    backgroundColor: "#ffffff",
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 4,
  },
  systemStripLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  systemStripValue: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: "800",
  },
  systemNoteBlock: {
    borderRadius: 12,
    backgroundColor: "#eef5ff",
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  sectionTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 16,
  },
  situationCard: {
    backgroundColor: "#f7fbfa",
    borderColor: "#cfe7de",
  },
  situationHero: {
    borderRadius: 18,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#d8ebe4",
    paddingVertical: 14,
    paddingHorizontal: 14,
    gap: 12,
  },
  situationHeroText: {
    gap: 4,
  },
  situationName: {
    color: colors.primary,
    fontSize: 22,
    fontWeight: "800",
    lineHeight: 28,
  },
  situationSubline: {
    color: colors.subText,
    fontSize: 13,
    lineHeight: 19,
  },
  situationMetricRail: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  situationMetric: {
    flex: 1,
    minWidth: "23%",
    borderRadius: 14,
    backgroundColor: "#f3f9f7",
    paddingVertical: 10,
    paddingHorizontal: 10,
    gap: 4,
  },
  situationMetricLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  situationMetricValue: {
    color: colors.accent,
    fontSize: 16,
    fontWeight: "800",
  },
  situationBody: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  situationColumn: {
    flex: 1,
    minWidth: "46%",
    borderRadius: 14,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#d8ebe4",
    paddingVertical: 12,
    paddingHorizontal: 12,
    gap: 8,
  },
  signalRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
    borderRadius: 12,
    backgroundColor: "#f5fbf8",
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  signalName: {
    flex: 1,
    color: colors.text,
    fontSize: 12.8,
    fontWeight: "700",
  },
  signalValue: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "700",
  },
  situationNote: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  riskChip: {
    borderRadius: 999,
    backgroundColor: "#e7f7f2",
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  riskChipText: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
  },
  pendingChip: {
    borderRadius: 999,
    backgroundColor: "#fff2df",
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  pendingChipText: {
    color: colors.warning,
    fontSize: 12,
    fontWeight: "700",
  },
  directiveCard: {
    backgroundColor: "#fbf8ff",
    borderColor: "#ddd3ef",
  },
  directiveGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  directiveOption: {
    width: "48%",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#ddd7e8",
    backgroundColor: "#ffffff",
    paddingVertical: 10,
    paddingHorizontal: 11,
    gap: 5,
  },
  directiveOptionActive: {
    borderColor: "#4966a5",
    backgroundColor: "#edf1ff",
  },
  directiveOptionTitle: {
    color: colors.text,
    fontSize: 13.2,
    fontWeight: "800",
  },
  directiveOptionTitleActive: {
    color: colors.primary,
  },
  directiveOptionText: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  directiveSummaryBox: {
    borderRadius: 14,
    backgroundColor: "#f4f1fb",
    paddingVertical: 11,
    paddingHorizontal: 12,
    gap: 5,
  },
  directiveSummary: {
    color: colors.text,
    fontSize: 13.4,
    lineHeight: 20,
    fontWeight: "700",
  },
  directiveMeta: {
    color: colors.subText,
    fontSize: 12.2,
    lineHeight: 18,
  },
  quickPromptWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  quickPromptChip: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#d8e1f0",
    backgroundColor: "#ffffff",
    paddingVertical: 9,
    paddingHorizontal: 10,
  },
  quickPromptText: {
    color: colors.primary,
    fontSize: 12.5,
    lineHeight: 18,
    fontWeight: "700",
  },
  inspectAction: {
    alignSelf: "flex-start",
    minWidth: 92,
  },
  runtimeCard: {
    backgroundColor: "#f8fbff",
    borderColor: "#c7d8ef",
  },
  runtimeHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
  },
  runtimeTitleWrap: {
    flex: 1,
    gap: 4,
  },
  runtimeLead: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  runtimeGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  runtimeMetric: {
    minWidth: "31%",
    flex: 1,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#d6e3f3",
    backgroundColor: "#ffffff",
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  runtimeMetricLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  runtimeMetricValue: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: "800",
  },
  runtimeMetricNote: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  runtimeWarning: {
    color: colors.warning,
    fontWeight: "700",
    fontSize: 12.5,
  },
  runtimeAliasBox: {
    borderRadius: 12,
    backgroundColor: "#eef5ff",
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  runtimeAliasText: {
    color: colors.text,
    fontSize: 12.5,
    lineHeight: 19,
  },
  runtimeActionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  runtimeAction: {
    minWidth: 110,
    flexGrow: 1,
  },
  subTitle: {
    color: colors.primary,
    fontWeight: "700",
    fontSize: 13.5,
  },
  modeRow: {
    marginTop: 10,
    flexDirection: "row",
    gap: 10,
  },
  modeBtn: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: "#f9fbff",
    alignItems: "center",
    paddingVertical: 11,
  },
  modeBtnActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  modeText: {
    color: colors.subText,
    fontWeight: "700",
  },
  modeTextActive: {
    color: colors.primary,
  },
  blockGap: {
    marginTop: 10,
    gap: 8,
  },
  chipWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  modelChip: {
    width: "48%",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 3,
  },
  modelChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#eef4ff",
  },
  modelChipTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 13,
  },
  modelChipTitleActive: {
    color: colors.primary,
  },
  modelChipDesc: {
    color: colors.subText,
    fontSize: 11.5,
    lineHeight: 16,
  },
  clusterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  clusterBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 18,
    paddingVertical: 7,
    paddingHorizontal: 12,
    backgroundColor: "#f9fbff",
  },
  clusterBtnActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  clusterName: {
    color: colors.subText,
    fontWeight: "700",
    fontSize: 12.5,
  },
  clusterNameActive: {
    color: colors.primary,
  },
  mainModel: {
    color: colors.primary,
    fontWeight: "700",
    fontSize: 12.5,
  },
  taskRow: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    padding: 9,
    gap: 2,
    backgroundColor: "#ffffff",
  },
  taskModel: {
    color: colors.text,
    fontWeight: "700",
  },
  taskText: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  attachRow: {
    flexDirection: "row",
    gap: 8,
  },
  missionCard: {
    marginTop: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#d7e1ef",
    backgroundColor: "#f9fbff",
    paddingVertical: 12,
    paddingHorizontal: 12,
    gap: 10,
  },
  missionField: {
    gap: 6,
  },
  missionInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    backgroundColor: "#ffffff",
    color: colors.text,
    fontSize: 13,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  missionTextArea: {
    minHeight: 88,
  },
  criteriaWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  criteriaChip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d6e0ef",
    backgroundColor: "#ffffff",
    paddingVertical: 8,
    paddingHorizontal: 11,
  },
  criteriaChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  criteriaChipText: {
    color: colors.subText,
    fontSize: 12,
    fontWeight: "700",
  },
  criteriaChipTextActive: {
    color: colors.primary,
  },
  composerHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
  },
  queueActionRow: {
    marginTop: 2,
  },
  attachBtn: {
    flex: 1,
  },
  fileList: {
    marginTop: 8,
    gap: 4,
  },
  fileItem: {
    color: colors.text,
    fontSize: 12.5,
  },
  sectionHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  headActions: {
    flexDirection: "row",
    gap: 6,
  },
  actionMini: {
    minWidth: 88,
  },
  queueEnqueueAction: {
    width: "100%",
  },
  queueCard: {
    backgroundColor: "#fbfcff",
    borderColor: "#d6e3f3",
  },
  queueSummaryRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  filterWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  filterChip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#ffffff",
    paddingVertical: 7,
    paddingHorizontal: 11,
  },
  filterChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#edf3ff",
  },
  filterChipText: {
    color: colors.subText,
    fontSize: 12,
    fontWeight: "700",
  },
  filterChipTextActive: {
    color: colors.primary,
  },
  queueSummaryChip: {
    flex: 1,
    minWidth: "22%",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d9e5f5",
    backgroundColor: "#ffffff",
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 2,
  },
  queueSummaryLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  queueSummaryValue: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: "800",
  },
  queueList: {
    gap: 10,
  },
  queueItem: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#d7e1f0",
    backgroundColor: "#ffffff",
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 6,
  },
  queueHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10,
  },
  queueHeadText: {
    flex: 1,
    gap: 3,
  },
  queueTitle: {
    color: colors.text,
    fontSize: 13.5,
    fontWeight: "800",
    lineHeight: 19,
  },
  queueMeta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  queuePrompt: {
    color: colors.text,
    fontSize: 12.5,
    lineHeight: 19,
  },
  queueApprovalItem: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#f0d7aa",
    backgroundColor: "#fff8eb",
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 4,
  },
  queueOutputBox: {
    gap: 6,
    borderRadius: 12,
    backgroundColor: "#f4f8fe",
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  queueOutputText: {
    color: colors.text,
    fontSize: 12.5,
    lineHeight: 19,
  },
  runInspectorCard: {
    backgroundColor: "#f7fafc",
    borderColor: "#d7e1ea",
  },
  runChip: {
    width: 182,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 10,
    backgroundColor: "#ffffff",
    gap: 3,
  },
  runChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  runChipTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "700",
  },
  runChipTitleActive: {
    color: colors.primary,
  },
  runChipMeta: {
    color: colors.subText,
    fontSize: 11.5,
  },
  runInspectorBody: {
    gap: 10,
    marginTop: 8,
  },
  runMetricRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  runMetricCard: {
    flex: 1,
    minWidth: "23%",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d6e3ec",
    backgroundColor: "#ffffff",
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 2,
  },
  executionItem: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d8e2ec",
    backgroundColor: "#ffffff",
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 4,
  },
  rowWrap: {
    flexDirection: "row",
    gap: 8,
  },
  flexHalf: {
    flex: 1,
  },
  folderList: {
    marginTop: 8,
    marginBottom: 6,
  },
  folderListContent: {
    gap: 8,
    paddingRight: 8,
  },
  folderChip: {
    width: 176,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 10,
    backgroundColor: "#f9fbff",
    gap: 2,
  },
  folderChipActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  folderTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "700",
  },
  folderTitleActive: {
    color: colors.primary,
  },
  folderMeta: {
    color: colors.subText,
    fontSize: 11.5,
  },
  tip: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  error: {
    color: colors.danger,
    fontWeight: "600",
    marginTop: 6,
  },
  chatList: {
    maxHeight: 560,
    marginTop: 8,
  },
  bubble: {
    borderRadius: 14,
    borderWidth: 1,
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 4,
    marginBottom: 8,
  },
  userBubble: {
    marginLeft: 36,
    borderColor: "#bed3ff",
    backgroundColor: "#edf3ff",
    alignSelf: "flex-end",
  },
  assistantBubble: {
    marginRight: 26,
    borderColor: colors.border,
    backgroundColor: "#ffffff",
    alignSelf: "flex-start",
  },
  bubbleTag: {
    fontSize: 12,
    fontWeight: "700",
  },
  userTag: {
    color: "#3459ac",
  },
  assistantTag: {
    color: colors.primary,
  },
  bubbleText: {
    color: colors.text,
    fontSize: 14.5,
    lineHeight: 21,
  },
  bubbleTime: {
    color: colors.subText,
    fontSize: 11,
  },
  responseCockpit: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    marginTop: 8,
    paddingTop: 8,
    gap: 8,
  },
  responseBadgeRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  detailStrip: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderRadius: 12,
    backgroundColor: "#f4f8fe",
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 10,
  },
  detailStripLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  detailStripValue: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "800",
  },
  inlineExpandBtn: {
    alignSelf: "flex-start",
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d7e3f3",
    backgroundColor: "#ffffff",
    paddingVertical: 7,
    paddingHorizontal: 12,
  },
  inlineExpandText: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "700",
  },
  detailSection: {
    gap: 6,
  },
  detailLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  detailLead: {
    color: colors.text,
    fontSize: 13,
    lineHeight: 19,
    fontWeight: "700",
  },
  detailText: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 19,
  },
  actionChipWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  actionChip: {
    borderRadius: 999,
    backgroundColor: "#e7f3ef",
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  actionChipText: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
  },
  planItem: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    backgroundColor: "#fbfdff",
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 4,
  },
  planHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  planTitle: {
    flex: 1,
    color: colors.text,
    fontSize: 12.8,
    fontWeight: "700",
  },
  planMeta: {
    color: colors.primary,
    fontSize: 11.5,
    fontWeight: "700",
  },
  planReason: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  artifactItem: {
    borderRadius: 12,
    backgroundColor: "#f7fafc",
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 4,
  },
  artifactHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  artifactTitle: {
    flex: 1,
    color: colors.text,
    fontSize: 12.8,
    fontWeight: "700",
  },
  artifactMeta: {
    color: colors.primary,
    fontSize: 11.5,
    fontWeight: "700",
  },
  artifactSummary: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  traceItem: {
    borderLeftWidth: 2,
    borderLeftColor: "#cfe0f5",
    paddingLeft: 10,
    gap: 4,
  },
  traceHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  traceAgent: {
    flex: 1,
    color: colors.text,
    fontSize: 12.8,
    fontWeight: "700",
  },
  traceNote: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  matrixItem: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#dbe5ef",
    backgroundColor: "#fbfdff",
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 5,
  },
  matrixHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  matrixTitle: {
    flex: 1,
    color: colors.text,
    fontSize: 12.8,
    fontWeight: "700",
  },
  matrixMeta: {
    color: colors.primary,
    fontSize: 11.5,
    fontWeight: "700",
  },
  matrixFocus: {
    color: colors.text,
    fontSize: 12.5,
    lineHeight: 18,
  },
  matrixHint: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  relayRail: {
    gap: 8,
  },
  relayItem: {
    borderLeftWidth: 3,
    borderLeftColor: "#bfd3ea",
    backgroundColor: "#f7fbff",
    borderRadius: 12,
    paddingVertical: 9,
    paddingHorizontal: 11,
    gap: 4,
  },
  relayOwner: {
    color: colors.primary,
    fontSize: 11.8,
    fontWeight: "700",
  },
  capsuleGrid: {
    gap: 8,
  },
  capsuleCard: {
    borderRadius: 12,
    backgroundColor: "#f6fafc",
    borderWidth: 1,
    borderColor: "#d9e6ee",
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 4,
  },
  capsuleCardTitle: {
    color: colors.text,
    fontSize: 12.2,
    fontWeight: "700",
  },
  capsuleText: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  graphBox: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#d8e2ec",
    backgroundColor: "#f9fbfe",
    paddingVertical: 10,
    paddingHorizontal: 11,
    gap: 7,
  },
  graphNode: {
    borderRadius: 999,
    backgroundColor: "#eef5ff",
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  graphEdge: {
    color: colors.primary,
    fontSize: 12,
    lineHeight: 18,
    fontWeight: "600",
  },
  reasoningCard: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d9e4ea",
    backgroundColor: "#ffffff",
    paddingVertical: 9,
    paddingHorizontal: 10,
    gap: 5,
  },
  reasoningHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  reasoningMode: {
    color: "#2c5f8a",
    fontSize: 11.5,
    fontWeight: "800",
  },
  reasoningScore: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
  },
});

