"use strict";

const STORAGE_KEY = "ai_nursing_admin_console_v4";

const VIEW_TITLES = {
  overview: "总览",
  cases: "病例",
  accounts: "账号",
  documents: "文书与模板",
  messages: "消息与智能流",
  monitor: "监控",
};

const ROLE_OPTIONS = [
  { value: "nurse", label: "责任护士" },
  { value: "senior_nurse", label: "高年资护士" },
  { value: "charge_nurse", label: "护士长" },
  { value: "resident_doctor", label: "住院医师" },
  { value: "attending_doctor", label: "主治医师" },
  { value: "consultant", label: "会诊专家" },
  { value: "pharmacist", label: "临床药师" },
  { value: "admin", label: "系统管理员" },
  { value: "auditor", label: "审计人员" },
];

const ACCOUNT_STATUS_OPTIONS = [
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
  { value: "locked", label: "锁定" },
];

const CASE_STATUS_OPTIONS = [
  { value: "admitted", label: "在院" },
  { value: "transferred", label: "转科" },
  { value: "discharged", label: "出院" },
];

const OBSERVATION_FLAGS = [
  { value: "normal", label: "正常" },
  { value: "low", label: "偏低" },
  { value: "high", label: "偏高" },
  { value: "critical", label: "危急" },
];

function runtimeApiBaseOverride() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    return String(params.get("apiBase") || "").trim();
  } catch {
    return "";
  }
}

function detectDefaultApiBase() {
  const runtimeApiBase = runtimeApiBaseOverride();
  if (runtimeApiBase) {
    return runtimeApiBase;
  }
  const isHttp = window.location.protocol === "http:" || window.location.protocol === "https:";
  if (isHttp && (window.location.port === "8000" || window.location.pathname.startsWith("/admin"))) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8000";
}

const DEFAULT_CFG = {
  apiBase: detectDefaultApiBase(),
  departmentId: "",
  departmentPinned: false,
  caseStatus: "",
  accountStatus: "",
  operatorUsername: "",
};

const state = {
  cfg: loadConfig(),
  view: "overview",
  loading: false,
  search: "",
  searchTimer: null,
  lastSyncAt: "",
  gatewayHealth: null,
  departments: [],
  analytics: null,
  cases: [],
  selectedCaseId: "",
  caseBundle: null,
  caseDraft: null,
  accounts: [],
  selectedAccountUsername: "",
  accountDraft: null,
  documents: [],
  selectedDocumentId: "",
  documentDraft: null,
  templates: [],
  selectedTemplateId: "",
  templateDraft: null,
  workflowHistory: [],
  threadHistory: [],
  directSessions: [],
  selectedDirectSessionId: "",
  directSessionDetail: null,
  liveBeds: [],
  binding: null,
  deviceSessions: [],
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  boot().catch(handleError);
});

async function boot() {
  cacheEls();
  bindEvents();
  render();
  await refreshAll({ init: true });
}

function cacheEls() {
  [
    "nav-list",
    "view-title",
    "view-root",
    "gateway-status",
    "refresh-btn",
    "open-config-btn",
    "config-drawer",
    "close-config-btn",
    "save-config-btn",
    "cfg-api-base",
    "department-select",
    "global-search",
    "case-status-filter",
    "account-status-filter",
    "operator-select",
    "current-department-name",
    "current-department-meta",
    "operator-name",
    "operator-role",
    "system-strip",
    "toast-stack",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  els["nav-list"].addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    state.view = String(button.dataset.view || "overview");
    render();
  });

  els["refresh-btn"].addEventListener("click", () => {
    refreshAll().catch(handleError);
  });

  els["open-config-btn"].addEventListener("click", () => {
    els["cfg-api-base"].value = state.cfg.apiBase || DEFAULT_CFG.apiBase;
    els["config-drawer"].classList.remove("hidden");
  });

  els["close-config-btn"].addEventListener("click", () => {
    els["config-drawer"].classList.add("hidden");
  });

  els["config-drawer"].addEventListener("click", (event) => {
    if (event.target === els["config-drawer"]) {
      els["config-drawer"].classList.add("hidden");
    }
  });

  els["save-config-btn"].addEventListener("click", async () => {
    state.cfg.apiBase = String(els["cfg-api-base"].value || "").trim() || DEFAULT_CFG.apiBase;
    saveConfig(state.cfg);
    els["config-drawer"].classList.add("hidden");
    await refreshAll();
  });

  els["department-select"].addEventListener("change", async (event) => {
    state.cfg.departmentId = String(event.target.value || "");
    state.cfg.departmentPinned = true;
    saveConfig(state.cfg);
    await Promise.all([refreshOverview(), refreshCases({ keepSelection: true }), refreshMonitor()]);
    render();
  });

  els["case-status-filter"].addEventListener("change", async (event) => {
    state.cfg.caseStatus = String(event.target.value || "");
    saveConfig(state.cfg);
    await refreshCases({ keepSelection: true });
    render();
  });

  els["account-status-filter"].addEventListener("change", async (event) => {
    state.cfg.accountStatus = String(event.target.value || "");
    saveConfig(state.cfg);
    await refreshAccounts({ keepSelection: true });
    render();
  });

  els["operator-select"].addEventListener("change", (event) => {
    setCurrentOperator(String(event.target.value || ""));
  });

  els["global-search"].addEventListener("input", (event) => {
    state.search = String(event.target.value || "").trim();
    scheduleSearchRefresh();
  });

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    try {
      await handleAction(String(target.dataset.action || ""), target);
    } catch (error) {
      handleError(error);
    }
  });
}

async function handleAction(action, target) {
  switch (action) {
    case "new-case":
      prepareNewCaseDraft();
      render();
      return;
    case "select-case":
      await selectCase(String(target.dataset.id || ""));
      return;
    case "save-case":
      await saveCaseFromForm();
      return;
    case "add-observation":
      state.caseDraft = collectCaseDraftFromDom();
      state.caseDraft.latest_observations.push({ name: "", value: "", abnormal_flag: "normal" });
      render();
      return;
    case "remove-observation": {
      const index = Number(target.dataset.index || -1);
      if (index >= 0) {
        state.caseDraft = collectCaseDraftFromDom();
        state.caseDraft.latest_observations.splice(index, 1);
        if (!state.caseDraft.latest_observations.length) {
          state.caseDraft.latest_observations.push({ name: "", value: "", abnormal_flag: "normal" });
        }
        render();
      }
      return;
    }
    case "new-account":
      prepareNewAccountDraft();
      render();
      return;
    case "select-account":
      selectAccount(String(target.dataset.username || ""));
      render();
      return;
    case "save-account":
      await saveAccountFromForm();
      return;
    case "set-operator":
      setCurrentOperator(String(target.dataset.username || ""));
      return;
    case "select-document":
      selectDocument(String(target.dataset.id || ""));
      render();
      return;
    case "save-document":
      await saveDocumentFromForm();
      return;
    case "review-document":
      await reviewDocument(String(target.dataset.id || ""));
      return;
    case "submit-document":
      await submitDocument(String(target.dataset.id || ""));
      return;
    case "new-template":
      prepareNewTemplateDraft();
      render();
      return;
    case "select-template":
      selectTemplate(String(target.dataset.id || ""));
      render();
      return;
    case "save-template":
      await saveTemplateFromForm();
      return;
    case "select-session":
      await selectDirectSession(String(target.dataset.id || ""));
      return;
    case "send-session-message":
      await sendSessionMessageFromForm();
      return;
    case "clear-search":
      state.search = "";
      els["global-search"].value = "";
      await Promise.all([
        refreshCases({ keepSelection: true }),
        refreshAccounts({ keepSelection: true }),
        refreshMessages({ keepSelection: true }),
      ]);
      render();
      return;
    default:
      return;
  }
}

async function refreshAll(options = {}) {
  state.loading = true;
  render();
  try {
    await refreshGateway();
    await refreshDepartments();
    await refreshAccounts({ keepSelection: !options.init });
    await reconcileDepartmentSelection({
      preferPopulated: Boolean(options.init) || !state.cfg.departmentPinned,
    });
    await Promise.all([
      refreshOverview(),
      refreshCases({ keepSelection: !options.init }),
      refreshDocuments({ keepSelection: !options.init }),
      refreshMessages({ keepSelection: !options.init }),
      refreshMonitor(),
    ]);
    ensureCurrentOperator();
    state.lastSyncAt = new Date().toISOString();
  } finally {
    state.loading = false;
    render();
  }
}

async function refreshGateway() {
  try {
    state.gatewayHealth = await api("/health");
  } catch (error) {
    state.gatewayHealth = { status: "error", detail: errorText(error) };
  }
}

async function refreshDepartments() {
  const rows = normalizeArray(await api("/api/admin/departments"));
  state.departments = rows;
  const validIds = new Set(rows.map((item) => String(item.id || "")));
  if (!validIds.has(state.cfg.departmentId)) {
    state.cfg.departmentId = "";
    state.cfg.departmentPinned = false;
    saveConfig(state.cfg);
  }
}

async function reconcileDepartmentSelection(options = {}) {
  const rows = normalizeArray(state.departments);
  if (!rows.length) {
    if (state.cfg.departmentId) {
      state.cfg.departmentId = "";
      state.cfg.departmentPinned = false;
      saveConfig(state.cfg);
    }
    return;
  }

  const validIds = new Set(rows.map((item) => String(item.id || "")));
  const currentId = String(state.cfg.departmentId || "");
  if (validIds.has(currentId) && (!options.preferPopulated || state.cfg.departmentPinned)) {
    return;
  }

  const nextId = String((await pickPreferredDepartmentId(rows, { currentId })) || "");
  const fallbackId = nextId || (validIds.has(currentId) ? currentId : String(rows[0]?.id || ""));
  if (!fallbackId || fallbackId === currentId) {
    return;
  }

  state.cfg.departmentId = fallbackId;
  state.cfg.departmentPinned = false;
  saveConfig(state.cfg);
}

async function pickPreferredDepartmentId(rows, options = {}) {
  const departments = normalizeArray(rows);
  if (!departments.length) {
    return "";
  }

  const currentId = String(options.currentId || "");
  const counts = await fetchDepartmentCaseCounts();
  if (currentId && ((counts.get(currentId) || 0) > 0 || counts.size === 0)) {
    return currentId;
  }

  const operatorMatchedId = findPreferredDepartmentForOperator(departments, counts);
  if (operatorMatchedId) {
    return operatorMatchedId;
  }

  let best = null;
  departments.forEach((item, index) => {
    const id = String(item.id || "");
    const count = counts.get(id) || 0;
    if (!best || count > best.count || (count === best.count && count > 0 && index < best.index)) {
      best = { id, count, index };
    }
  });

  if (best?.count > 0) {
    return best.id;
  }

  return currentId && departments.some((item) => String(item.id || "") === currentId) ? currentId : String(departments[0]?.id || "");
}

async function fetchDepartmentCaseCounts() {
  const counts = new Map();
  try {
    const rows = normalizeArray(
      await api("/api/admin/patient-cases", {
        params: { limit: 500 },
      }),
    );
    rows.forEach((item) => {
      const departmentId = String(item.department_id || "");
      if (!departmentId) {
        return;
      }
      counts.set(departmentId, (counts.get(departmentId) || 0) + 1);
    });
  } catch (error) {
    console.warn("Failed to infer populated departments.", error);
  }
  return counts;
}

function findPreferredDepartmentForOperator(rows, counts = new Map()) {
  const operator = getCurrentOperator();
  const operatorKey = normalizeDepartmentKey(operator?.department);
  if (!operatorKey) {
    return "";
  }

  const ranked = normalizeArray(rows)
    .map((item, index) => ({
      id: String(item.id || ""),
      key: normalizeDepartmentKey(item.name || item.code || item.id),
      count: counts.get(String(item.id || "")) || 0,
      index,
    }))
    .sort((a, b) => b.count - a.count || a.index - b.index);

  const direct = ranked.find(
    (item) => item.count > 0 && item.key && (item.key === operatorKey || item.key.startsWith(operatorKey) || operatorKey.startsWith(item.key)),
  );
  if (direct?.id) {
    return direct.id;
  }

  const prefix = operatorKey.slice(0, Math.min(2, operatorKey.length));
  const fuzzy = prefix.length >= 2 ? ranked.find((item) => item.count > 0 && item.key.startsWith(prefix)) : null;
  return fuzzy?.id || "";
}

function normalizeDepartmentKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/护理单元|病区|病房|科室|住院楼|楼层|住院|单元|科/g, "");
}

async function refreshOverview() {
  if (!state.cfg.departmentId) {
    state.analytics = null;
    return;
  }
  state.analytics = await api("/api/admin/ward-analytics", {
    params: { department_id: state.cfg.departmentId },
  });
}

async function refreshCases(options = {}) {
  if (!state.cfg.departmentId) {
    state.cases = [];
    prepareNewCaseDraft();
    return;
  }

  const rows = normalizeArray(
    await api("/api/admin/patient-cases", {
      params: {
        department_id: state.cfg.departmentId,
        query: state.search,
        current_status: state.cfg.caseStatus,
        limit: 200,
      },
    }),
  ).sort((a, b) => compareByBed(a.bed_no, b.bed_no) || compareText(a.full_name, b.full_name));

  state.cases = rows;
  const nextId =
    options.keepSelection && state.selectedCaseId && rows.some((item) => String(item.patient_id) === state.selectedCaseId)
      ? state.selectedCaseId
      : rows[0]?.patient_id || "";

  if (nextId) {
    await selectCase(nextId, { silent: true });
  } else {
    prepareNewCaseDraft();
  }
}

async function refreshAccounts(options = {}) {
  const rows = normalizeArray(
    await api("/api/admin/accounts", {
      params: {
        query: state.search,
        status_filter: state.cfg.accountStatus,
      },
    }),
  )
    .map(normalizeAdminAccount)
    .sort((a, b) => compareText(a.full_name, b.full_name));

  state.accounts = rows;
  ensureCurrentOperator();
  const nextUsername =
    options.keepSelection && state.selectedAccountUsername && rows.some((item) => item.username === state.selectedAccountUsername)
      ? state.selectedAccountUsername
      : state.cfg.operatorUsername || rows[0]?.username || "";

  if (nextUsername) {
    selectAccount(nextUsername);
  } else {
    prepareNewAccountDraft();
  }
}

async function refreshDocuments(options = {}) {
  const [documentsRaw, templatesRaw] = await Promise.all([
    api("/api/document/history", { params: { limit: 250 } }),
    api("/api/document/templates"),
  ]);

  state.documents = normalizeArray(documentsRaw).sort(compareByUpdatedAt);
  state.templates = normalizeArray(templatesRaw).sort(compareByUpdatedAt);

  const nextDocumentId =
    options.keepSelection && state.selectedDocumentId && state.documents.some((item) => item.id === state.selectedDocumentId)
      ? state.selectedDocumentId
      : state.documents[0]?.id || "";
  const nextTemplateId =
    options.keepSelection && state.selectedTemplateId && state.templates.some((item) => item.id === state.selectedTemplateId)
      ? state.selectedTemplateId
      : state.templates[0]?.id || "";

  if (nextDocumentId) {
    selectDocument(nextDocumentId);
  } else {
    state.selectedDocumentId = "";
    state.documentDraft = null;
  }

  if (nextTemplateId) {
    selectTemplate(nextTemplateId);
  } else {
    prepareNewTemplateDraft();
  }
}

async function refreshMessages(options = {}) {
  const [workflowRaw, threadsRaw, sessionsRaw] = await Promise.all([
    api("/api/workflow/history", { params: { limit: 120 } }).catch(() => []),
    api("/api/collab/history", { params: { limit: 120 } }).catch(() => []),
    api("/api/admin/direct-sessions", { params: { query: state.search, limit: 120 } }).catch(() => []),
  ]);

  state.workflowHistory = normalizeArray(workflowRaw).sort(compareByUpdatedAt);
  state.threadHistory = normalizeArray(threadsRaw).sort((a, b) =>
    compareByUpdatedAt(a?.latest_message?.created_at || a?.thread?.updated_at, b?.latest_message?.created_at || b?.thread?.updated_at),
  );
  state.directSessions = normalizeArray(sessionsRaw).sort(compareByUpdatedAt);

  const nextId =
    options.keepSelection && state.selectedDirectSessionId && state.directSessions.some((item) => item.id === state.selectedDirectSessionId)
      ? state.selectedDirectSessionId
      : state.directSessions[0]?.id || "";

  if (nextId) {
    await selectDirectSession(nextId, { silent: true });
  } else {
    state.selectedDirectSessionId = "";
    state.directSessionDetail = null;
  }
}

async function refreshMonitor() {
  const [bedsResult, bindingResult, sessionsResult] = await Promise.allSettled([
    state.cfg.departmentId ? api(`/api/wards/${encodeURIComponent(state.cfg.departmentId)}/beds`) : Promise.resolve([]),
    api("/api/device/binding"),
    api("/api/device/sessions"),
  ]);

  state.liveBeds = bedsResult.status === "fulfilled" ? normalizeArray(bedsResult.value) : [];
  state.binding = bindingResult.status === "fulfilled" ? bindingResult.value : { detail: errorText(bindingResult.reason) };
  state.deviceSessions = sessionsResult.status === "fulfilled" ? normalizeArray(sessionsResult.value) : [];
}

async function selectCase(patientId, options = {}) {
  if (!patientId) {
    prepareNewCaseDraft();
    if (!options.silent) render();
    return;
  }
  state.selectedCaseId = patientId;
  state.caseBundle = await api(`/api/admin/patient-cases/${encodeURIComponent(patientId)}`);
  state.caseDraft = bundleToCaseDraft(state.caseBundle);
  if (!options.silent) render();
}

function selectAccount(username) {
  const account = state.accounts.find((item) => item.username === username);
  if (!account) {
    prepareNewAccountDraft();
    return;
  }
  state.selectedAccountUsername = username;
  state.accountDraft = accountToDraft(account);
}

function selectDocument(documentId) {
  const item = state.documents.find((row) => row.id === documentId);
  state.selectedDocumentId = item?.id || "";
  state.documentDraft = item ? documentToDraft(item) : null;
}

function selectTemplate(templateId) {
  const item = state.templates.find((row) => row.id === templateId);
  if (!item) {
    prepareNewTemplateDraft();
    return;
  }
  state.selectedTemplateId = item.id;
  state.templateDraft = templateToDraft(item);
}

async function selectDirectSession(sessionId, options = {}) {
  if (!sessionId) {
    state.selectedDirectSessionId = "";
    state.directSessionDetail = null;
    if (!options.silent) render();
    return;
  }
  state.selectedDirectSessionId = sessionId;
  state.directSessionDetail = await api(`/api/admin/direct-sessions/${encodeURIComponent(sessionId)}`);
  if (!options.silent) render();
}

function prepareNewCaseDraft() {
  state.selectedCaseId = "";
  state.caseBundle = null;
  state.caseDraft = {
    patient_id: "",
    encounter_id: "",
    bed_no: "",
    room_no: "",
    full_name: "",
    mrn: "",
    inpatient_no: "",
    gender: "",
    age: "",
    blood_type: "",
    allergy_info: "",
    current_status: "admitted",
    diagnosesText: "",
    riskTagsText: "",
    pendingTasksText: "",
    latest_observations: [{ name: "", value: "", abnormal_flag: "normal" }],
  };
}

function prepareNewAccountDraft() {
  state.selectedAccountUsername = "";
  state.accountDraft = {
    id: "",
    username: "",
    full_name: "",
    role_code: "nurse",
    department: currentDepartment()?.name || "",
    title: "",
    phone: "",
    email: "",
    status: "active",
    password: "",
  };
}

function prepareNewTemplateDraft() {
  state.selectedTemplateId = "";
  state.templateDraft = {
    id: "",
    name: "",
    document_type: "nursing_note",
    trigger_keywords_text: "",
    source_refs_text: "",
    template_text: "",
    source_type: "import",
    updated_at: "",
  };
}

function bundleToCaseDraft(bundle) {
  const patient = bundle?.patient || {};
  const context = bundle?.context || {};
  const bed = bundle?.bed || {};
  const observations = Array.isArray(context.latest_observations) && context.latest_observations.length
    ? context.latest_observations.map((item) => ({
        name: String(item?.name || ""),
        value: String(item?.value || ""),
        abnormal_flag: String(item?.abnormal_flag || "normal"),
      }))
    : [{ name: "", value: "", abnormal_flag: "normal" }];

  return {
    patient_id: String(patient.id || ""),
    encounter_id: String(context.encounter_id || ""),
    bed_no: String(bed.bed_no || context.bed_no || ""),
    room_no: String(bed.room_no || ""),
    full_name: String(patient.full_name || context.patient_name || ""),
    mrn: String(patient.mrn || ""),
    inpatient_no: String(patient.inpatient_no || ""),
    gender: String(patient.gender || ""),
    age: patient.age ?? "",
    blood_type: String(patient.blood_type || ""),
    allergy_info: String(patient.allergy_info || ""),
    current_status: String(patient.current_status || "admitted"),
    diagnosesText: listToText(context.diagnoses),
    riskTagsText: listToText(context.risk_tags),
    pendingTasksText: listToText(context.pending_tasks),
    latest_observations: observations,
  };
}

function normalizeAdminAccount(row) {
  return {
    ...row,
    username: String(row.username || row.account || ""),
    full_name: String(row.full_name || row.username || row.account || ""),
    status: String(row.status || "active"),
  };
}

function accountToDraft(account) {
  return {
    id: String(account.id || ""),
    username: String(account.username || account.account || ""),
    full_name: String(account.full_name || ""),
    role_code: String(account.role_code || "nurse"),
    department: String(account.department || ""),
    title: String(account.title || ""),
    phone: String(account.phone || ""),
    email: String(account.email || ""),
    status: String(account.status || "active"),
    password: "",
  };
}

function documentToDraft(item) {
  return {
    id: String(item.id || ""),
    patient_id: String(item.patient_id || ""),
    document_type: String(item.document_type || ""),
    status: String(item.status || "draft"),
    source_type: String(item.source_type || "ai"),
    created_by: String(item.created_by || ""),
    updated_at: String(item.updated_at || item.created_at || ""),
    draft_text: String(item.draft_text || ""),
    structured_text: safePrettyJson(item.structured_fields || {}),
  };
}

function templateToDraft(item) {
  return {
    id: String(item.id || ""),
    name: String(item.name || ""),
    document_type: String(item.document_type || "nursing_note"),
    trigger_keywords_text: listToText(item.trigger_keywords),
    source_refs_text: listToText(item.source_refs),
    template_text: String(item.template_text || ""),
    source_type: String(item.source_type || "import"),
    updated_at: String(item.updated_at || item.created_at || ""),
  };
}

async function saveCaseFromForm() {
  const draft = collectCaseDraftFromDom();
  if (!draft.full_name.trim()) throw new Error("请先填写患者姓名");
  if (!draft.bed_no.trim()) throw new Error("请先填写床位号");

  const payload = {
    patient_id: emptyToNull(draft.patient_id),
    encounter_id: emptyToNull(draft.encounter_id),
    bed_no: draft.bed_no.trim(),
    room_no: emptyToNull(draft.room_no),
    full_name: draft.full_name.trim(),
    mrn: emptyToNull(draft.mrn),
    inpatient_no: emptyToNull(draft.inpatient_no),
    gender: emptyToNull(draft.gender),
    age: numberOrNull(draft.age),
    blood_type: emptyToNull(draft.blood_type),
    allergy_info: emptyToNull(draft.allergy_info),
    current_status: draft.current_status || "admitted",
    diagnoses: parseTextList(draft.diagnosesText),
    risk_tags: parseTextList(draft.riskTagsText),
    pending_tasks: parseTextList(draft.pendingTasksText),
    latest_observations: draft.latest_observations
      .map((item) => ({
        name: String(item.name || "").trim(),
        value: String(item.value || "").trim(),
        abnormal_flag: String(item.abnormal_flag || "normal"),
      }))
      .filter((item) => item.name || item.value),
  };

  const bundle = await api("/api/admin/patient-cases", { method: "POST", body: payload });
  state.caseBundle = bundle;
  state.caseDraft = bundleToCaseDraft(bundle);
  state.selectedCaseId = bundle?.patient?.id || state.selectedCaseId;
  toast("病例已保存", "病例修改已经回写到手机端统一数据源。");
  await Promise.all([refreshOverview(), refreshCases({ keepSelection: true }), refreshMonitor(), refreshDocuments({ keepSelection: true })]);
  render();
}

async function saveAccountFromForm() {
  const draft = collectAccountDraftFromDom();
  if (!draft.username.trim()) throw new Error("请先填写账号名");
  if (!draft.full_name.trim()) throw new Error("请先填写显示姓名");

  const payload = {
    id: emptyToNull(draft.id),
    username: draft.username.trim(),
    full_name: draft.full_name.trim(),
    role_code: draft.role_code || "nurse",
    department: emptyToNull(draft.department),
    title: emptyToNull(draft.title),
    phone: emptyToNull(draft.phone),
    email: emptyToNull(draft.email),
    status: draft.status || "active",
    password: emptyToNull(draft.password),
  };

  const saved = normalizeAdminAccount(await api("/api/admin/accounts/upsert", { method: "POST", body: payload }));
  state.cfg.operatorUsername = saved.username || payload.username;
  saveConfig(state.cfg);
  toast("账号已保存", "登录账号与协作账号已经同步更新。");
  await refreshAccounts({ keepSelection: true });
  selectAccount(saved.username || payload.username);
  render();
}

async function saveDocumentFromForm() {
  const draft = collectDocumentDraftFromDom();
  if (!draft.id) throw new Error("当前只能编辑已存在的手机端文书草稿");
  await api(`/api/document/${encodeURIComponent(draft.id)}/edit`, {
    method: "POST",
    body: {
      draft_text: draft.draft_text,
      structured_fields: parseJsonTextarea(draft.structured_text),
      edited_by: currentOperatorId(),
    },
  });
  toast("文书已保存", "手机端打开同一份草稿时会同步看到修改。");
  await refreshDocuments({ keepSelection: true });
  render();
}

async function reviewDocument(documentId) {
  const id = documentId || state.selectedDocumentId;
  if (!id) throw new Error("请先选择文书");
  await api(`/api/document/${encodeURIComponent(id)}/review`, {
    method: "POST",
    body: {
      reviewed_by: currentOperatorId(),
      review_note: "后台管理台审核",
    },
  });
  toast("文书已审核", "状态已经同步回统一文书流。");
  await refreshDocuments({ keepSelection: true });
  render();
}

async function submitDocument(documentId) {
  const id = documentId || state.selectedDocumentId;
  if (!id) throw new Error("请先选择文书");
  await api(`/api/document/${encodeURIComponent(id)}/submit`, {
    method: "POST",
    body: {
      submitted_by: currentOperatorId(),
    },
  });
  toast("文书已归档", "患者详情和手机端文书流会同步更新。");
  await refreshDocuments({ keepSelection: true });
  render();
}

async function saveTemplateFromForm() {
  const draft = collectTemplateDraftFromDom();
  if (!draft.name.trim()) throw new Error("请先填写模板名称");
  if (!draft.template_text.trim()) throw new Error("请先填写模板正文");

  const payload = {
    name: draft.name.trim(),
    document_type: emptyToNull(draft.document_type),
    template_text: draft.template_text,
    trigger_keywords: parseTextList(draft.trigger_keywords_text),
    source_refs: parseTextList(draft.source_refs_text),
    requested_by: currentOperatorId(),
  };

  if (draft.id) {
    await api(`/api/document/templates/${encodeURIComponent(draft.id)}/update`, { method: "POST", body: payload });
    toast("模板已更新", "手机端模板库会读取同一份模板。");
  } else {
    await api("/api/document/template/import", { method: "POST", body: payload });
    toast("模板已导入", "新模板已经进入统一模板库。");
  }

  await refreshDocuments({ keepSelection: true });
  render();
}

async function sendSessionMessageFromForm() {
  const sessionId = valueOf("session-id");
  const senderId = valueOf("session-sender-id");
  const content = valueOf("session-message-body").trim();
  if (!sessionId) throw new Error("请先选择会话");
  if (!content) throw new Error("请先输入消息内容");

  await api("/api/collab/direct/message", {
    method: "POST",
    body: {
      session_id: sessionId,
      sender_id: senderId || currentOperatorId(),
      message_type: "text",
      content,
      attachment_refs: [],
    },
  });

  toast("消息已发送", "手机端协作消息流会同步收到这条消息。");
  await refreshMessages({ keepSelection: true });
  render();
}

function collectCaseDraftFromDom() {
  const observations = Array.from(document.querySelectorAll("[data-observation-row]")).map((row) => ({
    name: String(row.querySelector("[data-field='name']")?.value || ""),
    value: String(row.querySelector("[data-field='value']")?.value || ""),
    abnormal_flag: String(row.querySelector("[data-field='flag']")?.value || "normal"),
  }));

  return {
    patient_id: valueOf("case-patient-id"),
    encounter_id: valueOf("case-encounter-id"),
    bed_no: valueOf("case-bed-no"),
    room_no: valueOf("case-room-no"),
    full_name: valueOf("case-full-name"),
    mrn: valueOf("case-mrn"),
    inpatient_no: valueOf("case-inpatient-no"),
    gender: valueOf("case-gender"),
    age: valueOf("case-age"),
    blood_type: valueOf("case-blood-type"),
    allergy_info: valueOf("case-allergy-info"),
    current_status: valueOf("case-current-status"),
    diagnosesText: valueOf("case-diagnoses"),
    riskTagsText: valueOf("case-risk-tags"),
    pendingTasksText: valueOf("case-pending-tasks"),
    latest_observations: observations.length ? observations : [{ name: "", value: "", abnormal_flag: "normal" }],
  };
}

function collectAccountDraftFromDom() {
  return {
    id: valueOf("account-id"),
    username: valueOf("account-username"),
    full_name: valueOf("account-full-name"),
    role_code: valueOf("account-role"),
    department: valueOf("account-department"),
    title: valueOf("account-title"),
    phone: valueOf("account-phone"),
    email: valueOf("account-email"),
    status: valueOf("account-status"),
    password: valueOf("account-password"),
  };
}

function collectDocumentDraftFromDom() {
  return {
    id: valueOf("doc-id"),
    draft_text: valueOf("doc-text"),
    structured_text: valueOf("doc-structured"),
  };
}

function collectTemplateDraftFromDom() {
  return {
    id: valueOf("template-id"),
    name: valueOf("template-name"),
    document_type: valueOf("template-document-type"),
    trigger_keywords_text: valueOf("template-keywords"),
    source_refs_text: valueOf("template-sources"),
    template_text: valueOf("template-text"),
  };
}

function scheduleSearchRefresh() {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => {
    Promise.all([
      refreshCases({ keepSelection: true }),
      refreshAccounts({ keepSelection: true }),
      refreshMessages({ keepSelection: true }),
    ])
      .then(() => render())
      .catch(handleError);
  }, 260);
  render();
}

function ensureCurrentOperator() {
  if (!state.accounts.length) {
    state.cfg.operatorUsername = "";
    saveConfig(state.cfg);
    return;
  }
  if (!state.accounts.some((item) => item.username === state.cfg.operatorUsername)) {
    state.cfg.operatorUsername = state.accounts.find((item) => item.status === "active")?.username || state.accounts[0].username;
    saveConfig(state.cfg);
  }
}

function setCurrentOperator(username) {
  state.cfg.operatorUsername = username;
  saveConfig(state.cfg);
  render();
  toast("操作账号已切换", operatorLabel(getCurrentOperator()) || username || "未选择");
}

function currentDepartment() {
  return state.departments.find((item) => String(item.id) === String(state.cfg.departmentId)) || null;
}

function getCurrentOperator() {
  return state.accounts.find((item) => item.username === state.cfg.operatorUsername) || null;
}

function currentOperatorId() {
  const operator = getCurrentOperator();
  return operator?.id || operator?.username || "admin-console";
}

function updateHeaderMeta() {
  els["view-title"].textContent = VIEW_TITLES[state.view] || "总览";
  Array.from(els["nav-list"].querySelectorAll("[data-view]")).forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });

  els["global-search"].value = state.search;
  els["cfg-api-base"].value = state.cfg.apiBase || DEFAULT_CFG.apiBase;
  els["case-status-filter"].value = state.cfg.caseStatus || "";
  els["account-status-filter"].value = state.cfg.accountStatus || "";

  els["department-select"].innerHTML = state.departments
    .map((item) => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.name || item.id)}</option>`)
    .join("");
  els["department-select"].value = state.cfg.departmentId || "";

  els["operator-select"].innerHTML = state.accounts
    .map((item) => `<option value="${escapeAttr(item.username)}">${escapeHtml(operatorLabel(item) || item.username)}</option>`)
    .join("");
  els["operator-select"].value = state.cfg.operatorUsername || "";

  const department = currentDepartment();
  const operator = getCurrentOperator();
  els["current-department-name"].textContent = department?.name || "未选择";
  els["current-department-meta"].textContent = department?.location || "当前后台按统一病区数据源工作";
  els["operator-name"].textContent = operator?.full_name || operator?.username || "未选择";
  els["operator-role"].textContent = operator ? `${roleLabel(operator.role_code)} · ${operator.department || "未填写科室"}` : "请选择要代入的后台账号";

  const gateway = gatewayStatusInfo();
  els["gateway-status"].textContent = gateway.label;
  els["gateway-status"].className = `status-chip ${gateway.tone}`;
}

function render() {
  updateHeaderMeta();
  renderSystemStrip();

  if (state.loading && !state.departments.length && !state.accounts.length) {
    els["view-root"].innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>正在加载统一后台数据...</p>
      </div>
    `;
    return;
  }

  switch (state.view) {
    case "cases":
      els["view-root"].innerHTML = renderCasesView();
      return;
    case "accounts":
      els["view-root"].innerHTML = renderAccountsView();
      return;
    case "documents":
      els["view-root"].innerHTML = renderDocumentsView();
      return;
    case "messages":
      els["view-root"].innerHTML = renderMessagesView();
      return;
    case "monitor":
      els["view-root"].innerHTML = renderMonitorView();
      return;
    default:
      els["view-root"].innerHTML = renderOverviewView();
  }
}

function renderSystemStrip() {
  const gateway = gatewayStatusInfo();
  const syncLabel = state.lastSyncAt ? formatDateTime(state.lastSyncAt) : "尚未同步";

  els["system-strip"].innerHTML = [
    renderSystemPill("当前病区", currentDepartment()?.name || "未选择", currentDepartment()?.location || "统一病区源"),
    renderSystemPill("当前操作账号", operatorLabel(getCurrentOperator()) || "未选择", getCurrentOperator()?.status || "待选择"),
    renderSystemPill("病例数", String(state.cases.length), "和手机端患者档案共用数据"),
    renderSystemPill("文书数", String(state.documents.length), `模板 ${state.templates.length} 份`),
    renderSystemPill("消息流", String(state.directSessions.length), "包含协作会话与 AI 历史"),
    renderSystemPill("网关", gateway.short, `${gateway.detail} · ${syncLabel}`),
  ].join("");
}

function renderOverviewView() {
  const analytics = state.analytics || {};
  const hotspots = normalizeArray(analytics.hotspots).slice(0, 8);
  const kpis = [
    { label: "在院患者", value: state.cases.filter((item) => item.current_status === "admitted").length, meta: "当前病区实时病例" },
    { label: "可管理账号", value: state.accounts.length, meta: "登录与协作账号联通" },
    { label: "文书草稿", value: state.documents.filter((item) => item.status === "draft").length, meta: "手机端草稿实时回写" },
    { label: "协作会话", value: state.directSessions.length, meta: "消息与 AI 流统一管理" },
  ];

  return `
    <section class="dashboard-grid">
      <article class="panel span-12">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">统一数据源</div>
            <h3>手机端与 Web 管理端共用同一套后端</h3>
            <p>病例、账号、文书、模板、消息和 AI 历史都从同一网关读取，后台改动会直接体现在手机端后续刷新中。</p>
          </div>
        </div>
        <div class="metric-grid">
          ${kpis.map((item) => `
            <div class="metric-card">
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(String(item.value))}</strong>
              <span>${escapeHtml(item.meta)}</span>
            </div>
          `).join("")}
        </div>
      </article>
      <article class="panel span-7">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">重点床位</div>
            <h3>病区风险热点</h3>
          </div>
        </div>
        ${hotspots.length ? `
          <div class="timeline-list">
            ${hotspots.map((item) => `
              <div class="timeline-item">
                <strong>${escapeHtml(`${item.bed_no || "-"}床 · ${item.patient_name || "未命名患者"}`)}</strong>
                <div class="record-meta">${escapeHtml((item.reasons || []).join("；") || "暂无风险原因")}</div>
                <div class="tag-row">
                  ${renderTag(`分值 ${item.score ?? 0}`, item.score >= 3 ? "bad" : item.score >= 1 ? "warn" : "good")}
                  ${renderTag(item.latest_observation || "暂无观察", "neutral")}
                </div>
              </div>
            `).join("")}
          </div>
        ` : renderEmpty("当前病区暂无重点热点。")}
      </article>
      <article class="panel span-5">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">联通状态</div>
            <h3>后台概况</h3>
          </div>
        </div>
        <div class="facts">
          ${renderFact("API 网关", gatewayStatusInfo().label)}
          ${renderFact("设备绑定", state.binding?.detail ? "异常" : "在线")}
          ${renderFact("模板库", `${state.templates.length} 份`)}
          ${renderFact("AI 历史", `${state.workflowHistory.length} 条`)}
          ${renderFact("协作线程", `${state.threadHistory.length} 条`)}
          ${renderFact("直接会话", `${state.directSessions.length} 条`)}
        </div>
      </article>
    </section>
  `;
}

function renderCasesView() {
  const draft = state.caseDraft;
  return `
    <section class="content-grid">
      <article class="panel span-4">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">病例列表</div>
            <h3>当前病区患者</h3>
          </div>
          <div class="panel-actions">
            <button class="ghost-btn" data-action="clear-search" type="button">清空搜索</button>
            <button class="primary-btn" data-action="new-case" type="button">新建病例</button>
          </div>
        </div>
        ${state.cases.length ? `<div class="record-list">${state.cases.map((item) => renderCaseRow(item)).join("")}</div>` : renderEmpty("当前病区暂无病例。")}
      </article>
      <article class="panel span-8">
        ${draft ? renderCaseEditor(draft) : renderEmpty("请先选择病例。")}
      </article>
    </section>
  `;
}

function renderAccountsView() {
  const draft = state.accountDraft;
  return `
    <section class="content-grid">
      <article class="panel span-4">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">账号列表</div>
            <h3>统一账号中心</h3>
          </div>
          <div class="panel-actions">
            <button class="primary-btn" data-action="new-account" type="button">新建账号</button>
          </div>
        </div>
        ${state.accounts.length ? `<div class="record-list">${state.accounts.map((item) => renderAccountRow(item)).join("")}</div>` : renderEmpty("暂无账号数据。")}
      </article>
      <article class="panel span-8">
        ${draft ? renderAccountEditor(draft) : renderEmpty("请先选择账号。")}
      </article>
    </section>
  `;
}

function renderDocumentsView() {
  const documents = filteredDocuments();
  const templates = filteredTemplates();
  return `
    <section class="content-grid">
      <article class="panel span-4">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">手机端文书</div>
            <h3>文书草稿与归档</h3>
          </div>
        </div>
        <div class="tag-row">
          ${renderTag(`草稿 ${state.documents.filter((item) => item.status === "draft").length}`, "warn")}
          ${renderTag(`待归档 ${state.documents.filter((item) => item.status === "reviewed").length}`, "neutral")}
          ${renderTag(`已归档 ${state.documents.filter((item) => item.status === "submitted").length}`, "good")}
        </div>
        ${documents.length ? `<div class="record-list">${documents.map((item) => renderDocumentRow(item)).join("")}</div>` : renderEmpty("没有命中文书。")}
      </article>
      <article class="panel span-8">
        ${state.documentDraft ? renderDocumentEditor(state.documentDraft) : renderEmpty("请先选择一份文书。")}
      </article>
      <article class="panel span-4">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">模板库</div>
            <h3>标准模板</h3>
          </div>
          <div class="panel-actions">
            <button class="primary-btn" data-action="new-template" type="button">新建模板</button>
          </div>
        </div>
        ${templates.length ? `<div class="record-list">${templates.map((item) => renderTemplateRow(item)).join("")}</div>` : renderEmpty("暂无模板。")}
      </article>
      <article class="panel span-8">
        ${state.templateDraft ? renderTemplateEditor(state.templateDraft) : renderEmpty("请先选择模板。")}
      </article>
    </section>
  `;
}

function renderMessagesView() {
  const detail = state.directSessionDetail;
  const unifiedHistory = buildUnifiedHistory();
  return `
    <section class="content-grid">
      <article class="panel span-4">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">直接会话</div>
            <h3>手机端协作消息</h3>
          </div>
        </div>
        ${state.directSessions.length ? `<div class="record-list">${state.directSessions.map((item) => renderDirectSessionRow(item)).join("")}</div>` : renderEmpty("当前没有直接会话。")}
      </article>
      <article class="panel span-8">
        ${detail ? renderDirectSessionDetail(detail) : renderEmpty("请先选择一条会话。")}
      </article>
      <article class="panel span-12">
        <div class="panel-head">
          <div>
            <div class="topbar-kicker">智能流与协作历史</div>
            <h3>AI 历史、文书协作与病例线程</h3>
          </div>
        </div>
        ${unifiedHistory.length ? `<div class="timeline-list">${unifiedHistory.map((item) => renderHistoryItem(item)).join("")}</div>` : renderEmpty("当前没有命中的历史流。")}
      </article>
    </section>
  `;
}

function renderMonitorView() {
  return `
    <section class="monitor-grid">
      <article class="panel span-4">
        <div class="panel-head"><div><div class="topbar-kicker">网关健康</div><h3>统一入口状态</h3></div></div>
        <div class="facts">
          ${renderFact("API 网关", gatewayStatusInfo().label)}
          ${renderFact("设备绑定", state.binding?.detail ? "异常" : "在线")}
          ${renderFact("设备会话", `${state.deviceSessions.length} 条`)}
          ${renderFact("床位快照", `${state.liveBeds.length} 条`)}
        </div>
      </article>
      <article class="panel span-4">
        <div class="panel-head"><div><div class="topbar-kicker">设备绑定</div><h3>原始绑定数据</h3></div></div>
        <pre class="code-block">${escapeHtml(safePrettyJson(state.binding || {}))}</pre>
      </article>
      <article class="panel span-4">
        <div class="panel-head"><div><div class="topbar-kicker">设备会话</div><h3>当前活跃记录</h3></div></div>
        ${state.deviceSessions.length ? `<div class="timeline-list">${state.deviceSessions.map((item) => `
          <div class="timeline-item">
            <strong>${escapeHtml(String(item.session_id || item.id || "设备会话"))}</strong>
            <div class="record-meta">${escapeHtml(safePrettyJson(item))}</div>
          </div>
        `).join("")}</div>` : renderEmpty("当前没有活跃设备会话。")}
      </article>
      <article class="panel span-12">
        <div class="panel-head"><div><div class="topbar-kicker">床位快照</div><h3>病区实时床位</h3></div></div>
        ${state.liveBeds.length ? `<div class="timeline-list">${state.liveBeds.map((item) => `
          <div class="timeline-item">
            <strong>${escapeHtml(`${item.bed_no || "-"}床 · ${item.patient_name || "空床"}`)}</strong>
            <div class="record-meta">${escapeHtml(`状态：${item.status || "-"} · 风险：${(item.risk_tags || []).join("、") || "无"}`)}</div>
            <div class="record-subline">${escapeHtml((item.pending_tasks || []).join("；") || "暂无待办")}</div>
          </div>
        `).join("")}</div>` : renderEmpty("当前病区暂无床位快照。")}
      </article>
    </section>
  `;
}

function renderCaseEditor(draft) {
  return `
    <div class="panel-head">
      <div>
        <div class="topbar-kicker">病例编辑</div>
        <h3>${escapeHtml(draft.full_name || "新建病例")}</h3>
      </div>
      <div class="panel-actions">
        <button class="primary-btn" data-action="save-case" type="button">保存病例</button>
      </div>
    </div>
    <div class="form-grid">
      ${renderInput("病例 ID", "case-patient-id", draft.patient_id, { readonly: true })}
      ${renderInput("就诊 ID", "case-encounter-id", draft.encounter_id)}
      ${renderInput("床位号", "case-bed-no", draft.bed_no)}
      ${renderInput("房间号", "case-room-no", draft.room_no)}
      ${renderInput("姓名", "case-full-name", draft.full_name)}
      ${renderInput("病历号 MRN", "case-mrn", draft.mrn)}
      ${renderInput("住院号", "case-inpatient-no", draft.inpatient_no)}
      ${renderInput("性别", "case-gender", draft.gender)}
      ${renderInput("年龄", "case-age", draft.age, { type: "number" })}
      ${renderInput("血型", "case-blood-type", draft.blood_type)}
      ${renderSelect("当前状态", "case-current-status", draft.current_status, CASE_STATUS_OPTIONS)}
      ${renderInput("当前病区", "case-department", currentDepartment()?.name || "", { readonly: true })}
      ${renderTextarea("过敏信息", "case-allergy-info", draft.allergy_info, { full: true })}
      ${renderTextarea("诊断列表", "case-diagnoses", draft.diagnosesText)}
      ${renderTextarea("风险标签", "case-risk-tags", draft.riskTagsText)}
      ${renderTextarea("待办任务", "case-pending-tasks", draft.pendingTasksText, { full: true })}
    </div>
    <div class="panel-head" style="margin-top:16px">
      <div><div class="topbar-kicker">最新观察</div><h3>观察列表</h3></div>
      <div class="panel-actions">
        <button class="ghost-btn" data-action="add-observation" type="button">新增观察</button>
      </div>
    </div>
    <div class="record-list">
      ${(draft.latest_observations || []).map((item, index) => `
        <div class="record-button" data-observation-row="${index}">
          <div class="form-grid">
            ${renderInlineInput("观察项", "name", item.name)}
            ${renderInlineInput("结果", "value", item.value)}
            ${renderInlineSelect("异常级别", "flag", item.abnormal_flag || "normal", OBSERVATION_FLAGS)}
            <div class="field">
              <span>操作</span>
              <button class="ghost-btn" data-action="remove-observation" data-index="${index}" type="button">删除</button>
            </div>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderAccountEditor(draft) {
  return `
    <div class="panel-head">
      <div><div class="topbar-kicker">账号编辑</div><h3>${escapeHtml(draft.full_name || "新建账号")}</h3></div>
      <div class="panel-actions">
        ${draft.username ? `<button class="ghost-btn" data-action="set-operator" data-username="${escapeAttr(draft.username)}" type="button">设为操作账号</button>` : ""}
        <button class="primary-btn" data-action="save-account" type="button">保存账号</button>
      </div>
    </div>
    <div class="form-grid">
      ${renderInput("内部 ID", "account-id", draft.id, { readonly: true })}
      ${renderInput("账号名", "account-username", draft.username)}
      ${renderInput("显示姓名", "account-full-name", draft.full_name)}
      ${renderSelect("角色", "account-role", draft.role_code, ROLE_OPTIONS)}
      ${renderInput("所属科室", "account-department", draft.department)}
      ${renderInput("岗位/职称", "account-title", draft.title)}
      ${renderSelect("账号状态", "account-status", draft.status, ACCOUNT_STATUS_OPTIONS)}
      ${renderInput("重置密码", "account-password", draft.password)}
      ${renderInput("手机号", "account-phone", draft.phone)}
      ${renderInput("邮箱", "account-email", draft.email)}
    </div>
  `;
}

function renderDocumentEditor(draft) {
  return `
    <div class="panel-head">
      <div><div class="topbar-kicker">文书编辑</div><h3>${escapeHtml(draft.document_type || "文书草稿")}</h3></div>
      <div class="panel-actions">
        <button class="ghost-btn" data-action="review-document" data-id="${escapeAttr(draft.id)}" type="button">审核</button>
        <button class="ghost-btn" data-action="submit-document" data-id="${escapeAttr(draft.id)}" type="button">归档</button>
        <button class="primary-btn" data-action="save-document" type="button">保存文书</button>
      </div>
    </div>
    <div class="facts">
      ${renderFact("文书 ID", draft.id)}
      ${renderFact("患者 ID", draft.patient_id)}
      ${renderFact("状态", draft.status)}
      ${renderFact("来源", draft.source_type)}
      ${renderFact("创建人", draft.created_by || "-")}
      ${renderFact("更新时间", formatDateTime(draft.updated_at))}
    </div>
    <input id="doc-id" type="hidden" value="${escapeAttr(draft.id)}" />
    <div class="form-grid" style="margin-top:16px">
      ${renderTextarea("正文内容", "doc-text", draft.draft_text, { full: true })}
      ${renderTextarea("结构化字段 JSON", "doc-structured", draft.structured_text, { full: true })}
    </div>
  `;
}

function renderTemplateEditor(draft) {
  return `
    <div class="panel-head">
      <div><div class="topbar-kicker">模板编辑</div><h3>${escapeHtml(draft.name || "新建模板")}</h3></div>
      <div class="panel-actions">
        <button class="primary-btn" data-action="save-template" type="button">${draft.id ? "保存模板" : "导入模板"}</button>
      </div>
    </div>
    <input id="template-id" type="hidden" value="${escapeAttr(draft.id)}" />
    <div class="facts">
      ${renderFact("模板 ID", draft.id || "新建")}
      ${renderFact("来源", draft.source_type || "import")}
      ${renderFact("更新时间", draft.updated_at ? formatDateTime(draft.updated_at) : "-")}
    </div>
    <div class="form-grid" style="margin-top:16px">
      ${renderInput("模板名称", "template-name", draft.name)}
      ${renderInput("文书类型", "template-document-type", draft.document_type)}
      ${renderTextarea("触发关键词", "template-keywords", draft.trigger_keywords_text, { full: true })}
      ${renderTextarea("来源说明", "template-sources", draft.source_refs_text, { full: true })}
      ${renderTextarea("模板正文", "template-text", draft.template_text, { full: true })}
    </div>
  `;
}

function renderDirectSessionDetail(detail) {
  return `
    <div class="panel-head">
      <div><div class="topbar-kicker">会话详情</div><h3>${escapeHtml(renderDirectSessionTitle(detail.session))}</h3></div>
    </div>
    <div class="facts">
      ${renderFact("会话 ID", detail.session.id)}
      ${renderFact("患者 ID", detail.session.patient_id || "-")}
      ${renderFact("发起账号", lookupAccountLabel(detail.session.user_id))}
      ${renderFact("对方账号", lookupAccountLabel(detail.session.contact_user_id))}
    </div>
    <div class="message-thread" style="margin-top:16px">
      ${detail.messages.length ? detail.messages.map((item) => renderMessageBubble(item)).join("") : renderEmpty("当前会话还没有消息。")}
    </div>
    <div class="form-grid" style="margin-top:16px">
      ${renderInput("会话 ID", "session-id", detail.session.id, { readonly: true })}
      ${renderSelect("发送身份", "session-sender-id", pickDefaultSender(detail.session), buildSessionSenderOptions(detail.session))}
      ${renderTextarea("回复内容", "session-message-body", "", { full: true })}
    </div>
    <div class="panel-actions" style="margin-top:16px">
      <button class="primary-btn" data-action="send-session-message" type="button">发送消息</button>
    </div>
  `;
}

function renderCaseRow(item) {
  const active = item.patient_id === state.selectedCaseId ? " active" : "";
  return `
    <button class="record-button${active}" data-action="select-case" data-id="${escapeAttr(item.patient_id)}" type="button">
      <div class="record-title"><span>${escapeHtml(`${item.bed_no || "-"}床`)}</span><span>${escapeHtml(item.full_name || "未命名患者")}</span></div>
      <div class="record-meta">${escapeHtml(`${item.gender || "-"} · ${item.age ?? "-"} 岁 · ${item.mrn || "未填 MRN"}`)}</div>
      <div class="record-subline">${escapeHtml((item.pending_tasks || []).join("；") || item.latest_observation || "暂无待办")}</div>
      <div class="tag-row">
        ${renderTag(caseStatusLabel(item.current_status), "neutral")}
        ${renderTag(`风险 ${(item.risk_tags || []).length}`, (item.risk_tags || []).length ? "warn" : "good")}
      </div>
    </button>
  `;
}

function renderAccountRow(item) {
  const active = item.username === state.selectedAccountUsername ? " active" : "";
  return `
    <button class="record-button${active}" data-action="select-account" data-username="${escapeAttr(item.username)}" type="button">
      <div class="record-title"><span>${escapeHtml(item.full_name || item.username)}</span>${item.username === state.cfg.operatorUsername ? renderTag("当前操作账号", "neutral") : ""}</div>
      <div class="record-meta">${escapeHtml(`${item.username} · ${roleLabel(item.role_code)}`)}</div>
      <div class="record-subline">${escapeHtml(item.department || "未填写科室")} · ${escapeHtml(item.title || "未填写岗位")}</div>
      <div class="tag-row">${renderTag(accountStatusLabel(item.status), accountStatusTone(item.status))}</div>
    </button>
  `;
}

function renderDocumentRow(item) {
  const active = item.id === state.selectedDocumentId ? " active" : "";
  const patient = lookupCase(item.patient_id);
  return `
    <button class="record-button${active}" data-action="select-document" data-id="${escapeAttr(item.id)}" type="button">
      <div class="record-title"><span>${escapeHtml(item.document_type || "文书")}</span>${renderTag(item.status || "draft", documentStatusTone(item.status))}</div>
      <div class="record-meta">${escapeHtml(`${patient?.bed_no || "-"}床 · ${patient?.full_name || item.patient_id || "未命名患者"}`)}</div>
      <div class="record-subline">${escapeHtml(compactText(item.draft_text || "", 88))}</div>
    </button>
  `;
}

function renderTemplateRow(item) {
  const active = item.id === state.selectedTemplateId ? " active" : "";
  return `
    <button class="record-button${active}" data-action="select-template" data-id="${escapeAttr(item.id)}" type="button">
      <div class="record-title"><span>${escapeHtml(item.name || "未命名模板")}</span>${renderTag(item.source_type || "import", item.source_type === "system" ? "neutral" : "good")}</div>
      <div class="record-meta">${escapeHtml(item.document_type || "nursing_note")}</div>
      <div class="record-subline">${escapeHtml(compactText(item.template_text || "", 88))}</div>
    </button>
  `;
}

function renderDirectSessionRow(item) {
  const active = item.id === state.selectedDirectSessionId ? " active" : "";
  return `
    <button class="record-button${active}" data-action="select-session" data-id="${escapeAttr(item.id)}" type="button">
      <div class="record-title"><span>${escapeHtml(renderDirectSessionTitle(item))}</span>${renderTag(item.status || "open", "neutral")}</div>
      <div class="record-meta">${escapeHtml(`发起：${lookupAccountLabel(item.user_id)} · 对方：${lookupAccountLabel(item.contact_user_id)}`)}</div>
      <div class="record-subline">${escapeHtml(compactText(item.latest_message?.content || "暂无消息", 96))}</div>
    </button>
  `;
}

function renderMessageBubble(item) {
  const self = item.sender_id === currentOperatorId() ? " self" : "";
  return `
    <div class="message-bubble${self}">
      <div class="message-head"><span>${escapeHtml(lookupAccountLabel(item.sender_id) || item.sender_id || "未知发送者")}</span><span>${escapeHtml(formatDateTime(item.created_at))}</span></div>
      <div class="message-body">${escapeHtml(item.content || "")}</div>
    </div>
  `;
}

function buildUnifiedHistory() {
  const workflowRows = state.workflowHistory.map((item) => ({
    id: `wf-${item.id}`,
    title: `${item.workflow_type || "AI流程"} · ${lookupAccountLabel(item.requested_by) || item.requested_by || "未知账号"}`,
    subtitle: compactText(item.summary || item.user_input || "", 180),
    meta: `${formatDateTime(item.created_at)} · 患者 ${item.patient_id || "-"}`,
    updatedAt: item.created_at,
  }));

  const threadRows = state.threadHistory.map((item) => ({
    id: `th-${item.thread?.id}`,
    title: `${item.thread?.title || "协作线程"} · 患者 ${item.thread?.patient_id || "-"}`,
    subtitle: compactText(item.latest_message?.content || "暂无最新消息", 180),
    meta: `${formatDateTime(item.latest_message?.created_at || item.thread?.updated_at)} · ${item.message_count || 0} 条消息`,
    updatedAt: item.latest_message?.created_at || item.thread?.updated_at,
  }));

  return [...workflowRows, ...threadRows]
    .filter((item) => matchSearch(`${item.title} ${item.subtitle} ${item.meta}`))
    .sort((a, b) => compareByUpdatedAt(a.updatedAt, b.updatedAt));
}

function renderHistoryItem(item) {
  return `
    <div class="timeline-item">
      <strong>${escapeHtml(item.title)}</strong>
      <div class="record-meta">${escapeHtml(item.meta)}</div>
      <div class="record-subline">${escapeHtml(item.subtitle)}</div>
    </div>
  `;
}

async function api(path, options = {}) {
  const base = String(state.cfg.apiBase || DEFAULT_CFG.apiBase || "").trim() || DEFAULT_CFG.apiBase;
  const url = new URL(path, base.endsWith("/") ? base : `${base}/`);
  Object.entries(options.params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    url.searchParams.set(key, String(value));
  });

  const response = await fetch(url.toString(), {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const raw = await response.text();
  const data = raw ? tryParseJson(raw) : null;
  if (!response.ok) {
    const detail =
      (data && typeof data === "object" && (data.detail || data.message || data.error)) ||
      raw ||
      `HTTP ${response.status}`;
    throw new Error(String(detail));
  }
  return data;
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const runtimeApiBase = runtimeApiBaseOverride();
    if (!raw) {
      return runtimeApiBase ? { ...DEFAULT_CFG, apiBase: runtimeApiBase } : { ...DEFAULT_CFG };
    }
    const saved = JSON.parse(raw);
    const merged = { ...DEFAULT_CFG, ...(saved || {}) };
    return runtimeApiBase ? { ...merged, apiBase: runtimeApiBase } : merged;
  } catch {
    const runtimeApiBase = runtimeApiBaseOverride();
    return runtimeApiBase ? { ...DEFAULT_CFG, apiBase: runtimeApiBase } : { ...DEFAULT_CFG };
  }
}

function saveConfig(next) {
  state.cfg = { ...DEFAULT_CFG, ...(next || {}) };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.cfg));
}

function gatewayStatusInfo() {
  const health = state.gatewayHealth || {};
  if (String(health.status || "").toLowerCase() === "ok") {
    return {
      tone: "good",
      label: "网关正常",
      short: "正常",
      detail: `${health.service || "api-gateway"} 已连通`,
    };
  }
  if (String(health.status || "").toLowerCase() === "error") {
    return {
      tone: "bad",
      label: "网关异常",
      short: "异常",
      detail: compactText(String(health.detail || "请求失败"), 60),
    };
  }
  return {
    tone: "warn",
    label: "网关待检查",
    short: "待检查",
    detail: "尚未完成健康检查",
  };
}

function lookupCase(patientId) {
  if (!patientId) return null;
  return state.cases.find((item) => String(item.patient_id) === String(patientId)) || null;
}

function lookupAccountLabel(id) {
  if (!id) return "";
  const fromAccounts = state.accounts.find((item) => item.id === id || item.username === id || item.account === id);
  if (fromAccounts) {
    return operatorLabel(fromAccounts);
  }
  for (const session of state.directSessions) {
    if (session.contact && (session.contact.id === id || session.contact.account === id)) {
      return operatorLabel(normalizeAdminAccount({ ...session.contact, username: session.contact.account }));
    }
  }
  return String(id);
}

function renderDirectSessionTitle(session) {
  if (!session) return "直接会话";
  const userLabel = lookupAccountLabel(session.user_id);
  const contactLabel = session.contact?.full_name || lookupAccountLabel(session.contact_user_id);
  return `${contactLabel || session.contact_user_id || "未命名联系人"} · ${userLabel || session.user_id || "未知发起人"}`;
}

function buildSessionSenderOptions(session) {
  if (!session) return [];
  const rows = [
    { value: String(session.user_id || ""), label: lookupAccountLabel(session.user_id) || String(session.user_id || "") },
    { value: String(session.contact_user_id || ""), label: lookupAccountLabel(session.contact_user_id) || String(session.contact_user_id || "") },
  ].filter((item) => item.value);
  const deduped = new Map();
  rows.forEach((item) => deduped.set(item.value, item));
  return Array.from(deduped.values());
}

function pickDefaultSender(session) {
  const current = currentOperatorId();
  const options = buildSessionSenderOptions(session);
  return options.some((item) => item.value === current) ? current : options[0]?.value || "";
}

function filteredDocuments() {
  return [...state.documents]
    .filter((item) => {
      if (!matchSearch(`${item.document_type || ""} ${item.status || ""} ${item.draft_text || ""}`)) return false;
      const patient = lookupCase(item.patient_id);
      return matchSearch(`${patient?.full_name || ""} ${patient?.bed_no || ""}`);
    })
    .sort(compareByUpdatedAt);
}

function filteredTemplates() {
  return [...state.templates]
    .filter((item) => matchSearch(`${item.name || ""} ${item.document_type || ""} ${item.template_text || ""}`))
    .sort(compareByUpdatedAt);
}

function matchSearch(text) {
  const keyword = String(state.search || "").trim().toLowerCase();
  if (!keyword) return true;
  return String(text || "").toLowerCase().includes(keyword);
}

function operatorLabel(operator) {
  if (!operator) return "";
  const name = operator.full_name || operator.username || operator.account || "";
  const role = roleLabel(operator.role_code);
  return [name, role].filter(Boolean).join(" · ");
}

function roleLabel(roleCode) {
  const hit = ROLE_OPTIONS.find((item) => item.value === roleCode);
  return hit?.label || roleCode || "未定义角色";
}

function caseStatusLabel(status) {
  const hit = CASE_STATUS_OPTIONS.find((item) => item.value === status);
  return hit?.label || status || "未知";
}

function accountStatusLabel(status) {
  const hit = ACCOUNT_STATUS_OPTIONS.find((item) => item.value === status);
  return hit?.label || status || "未知";
}

function accountStatusTone(status) {
  if (status === "active") return "good";
  if (status === "inactive") return "warn";
  if (status === "locked") return "bad";
  return "neutral";
}

function documentStatusTone(status) {
  if (status === "submitted") return "good";
  if (status === "reviewed") return "neutral";
  if (status === "draft") return "warn";
  return "neutral";
}

function compareByBed(a, b) {
  const normalize = (value) => {
    const raw = String(value || "").trim();
    return raw && /^\d+$/.test(raw) ? [0, String(Number(raw)).padStart(4, "0")] : [1, raw];
  };
  const [aRank, aValue] = normalize(a);
  const [bRank, bValue] = normalize(b);
  return aRank - bRank || aValue.localeCompare(bValue, "zh-CN");
}

function compareByUpdatedAt(a, b) {
  const at = Date.parse(String(a?.updated_at || a?.created_at || a || "")) || 0;
  const bt = Date.parse(String(b?.updated_at || b?.created_at || b || "")) || 0;
  return bt - at;
}

function compareText(a, b) {
  return String(a || "").localeCompare(String(b || ""), "zh-CN");
}

function safePrettyJson(value) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function parseJsonTextarea(value) {
  const text = String(value || "").trim();
  if (!text) return {};
  const parsed = tryParseJson(text);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("结构化 JSON 格式不正确");
  }
  return parsed;
}

function normalizeArray(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

function listToText(value) {
  return normalizeArray(value).map((item) => String(item || "").trim()).filter(Boolean).join("\n");
}

function parseTextList(value) {
  return String(value || "")
    .split(/\r?\n|[；;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function compactText(value, limit = 120) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(
    date.getHours(),
  ).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function emptyToNull(value) {
  const text = String(value ?? "").trim();
  return text ? text : null;
}

function numberOrNull(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const num = Number(text);
  return Number.isFinite(num) ? num : null;
}

function valueOf(id) {
  return String(document.getElementById(id)?.value || "");
}

function tryParseJson(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/\n/g, "&#10;");
}

function errorText(error) {
  if (!error) return "未知错误";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message || "请求失败";
  if (typeof error === "object") {
    return String(error.detail || error.message || error.error || "请求失败");
  }
  return String(error);
}

function handleError(error) {
  console.error(error);
  toast("操作失败", errorText(error), "err");
}

function toast(title, copy, tone = "ok") {
  const node = document.createElement("div");
  node.className = `toast ${tone === "err" ? "err" : "ok"}`;
  node.innerHTML = `
    <p class="toast-title">${escapeHtml(title || "提示")}</p>
    <p class="toast-copy">${escapeHtml(copy || "")}</p>
  `;
  els["toast-stack"].appendChild(node);
  window.setTimeout(() => {
    node.remove();
  }, 3200);
}

function renderSystemPill(label, value, meta) {
  return `
    <div class="system-pill">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(meta)}</span>
    </div>
  `;
}

function renderTag(label, tone = "neutral") {
  return `<span class="tag ${escapeAttr(tone)}">${escapeHtml(label)}</span>`;
}

function renderFact(label, value) {
  return `
    <div class="metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "-")}</strong>
    </div>
  `;
}

function renderInput(label, id, value, options = {}) {
  return `
    <label class="field" style="${options.full ? "grid-column: 1 / -1;" : ""}">
      <span>${escapeHtml(label)}</span>
      <input id="${escapeAttr(id)}" type="${escapeAttr(options.type || "text")}" value="${escapeAttr(value ?? "")}" ${options.readonly ? "readonly" : ""} />
    </label>
  `;
}

function renderTextarea(label, id, value, options = {}) {
  return `
    <label class="field" style="${options.full ? "grid-column: 1 / -1;" : ""}">
      <span>${escapeHtml(label)}</span>
      <textarea id="${escapeAttr(id)}">${escapeHtml(value ?? "")}</textarea>
    </label>
  `;
}

function renderSelect(label, id, value, options = []) {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <select id="${escapeAttr(id)}">
        ${normalizeArray(options).map((item) => `<option value="${escapeAttr(item.value)}" ${String(item.value) === String(value) ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderInlineInput(label, field, value) {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <input data-field="${escapeAttr(field)}" type="text" value="${escapeAttr(value ?? "")}" />
    </label>
  `;
}

function renderInlineSelect(label, field, value, options = []) {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <select data-field="${escapeAttr(field)}">
        ${normalizeArray(options).map((item) => `<option value="${escapeAttr(item.value)}" ${String(item.value) === String(value) ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderEmpty(copy) {
  return `
    <div class="empty-state">
      <div class="empty-glyph">暂无</div>
      <p>${escapeHtml(copy)}</p>
    </div>
  `;
}
