"use strict";

const STORAGE_KEY = "ai_nursing_admin_console_v3";

const VIEW_TITLES = {
  overview: "病区总览",
  cases: "病例工作台",
  accounts: "账号中心",
  monitor: "联通监控",
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
  { value: "auditor", label: "审计员" },
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

function detectDefaultApiBase() {
  const isHttp = window.location.protocol === "http:" || window.location.protocol === "https:";
  if (isHttp && (window.location.port === "18000" || window.location.pathname.startsWith("/admin"))) {
    return window.location.origin;
  }
  return "http://127.0.0.1:18000";
}

const DEFAULT_CFG = {
  apiBase: detectDefaultApiBase(),
  departmentId: "",
  caseStatus: "",
  accountStatus: "",
  operatorUsername: "",
};

const state = {
  cfg: loadConfig(),
  view: "overview",
  loading: false,
  search: "",
  lastSyncAt: "",
  searchTimer: null,
  departments: [],
  analytics: null,
  cases: [],
  selectedCaseId: "",
  caseBundle: null,
  caseDraft: null,
  accounts: [],
  selectedAccountUsername: "",
  accountDraft: null,
  gatewayHealth: null,
  liveBeds: [],
  binding: null,
  sessions: [],
};

const els = {};

boot().catch((error) => {
  console.error(error);
  toast("初始化失败", errorText(error), "err");
});

async function boot() {
  cacheEls();
  bindStaticEvents();
  syncConfigInputs();
  syncFilterInputs();
  setView(state.view);
  render();
  await refreshAll({ init: true });
}

function cacheEls() {
  [
    "nav-list",
    "view-root",
    "view-title",
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
    "current-department-name",
    "current-department-meta",
    "operator-name",
    "operator-role",
    "operator-select",
    "system-strip",
    "toast-stack",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindStaticEvents() {
  els["nav-list"].addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    setView(button.dataset.view || "overview");
    render();
  });

  els["refresh-btn"].addEventListener("click", () => {
    refreshAll().catch(handleError);
  });

  els["open-config-btn"].addEventListener("click", () => {
    syncConfigInputs();
    els["config-drawer"].classList.remove("hidden");
  });

  els["config-drawer"].addEventListener("click", (event) => {
    if (event.target === els["config-drawer"]) {
      closeConfigDrawer();
    }
  });

  els["close-config-btn"].addEventListener("click", closeConfigDrawer);
  els["save-config-btn"].addEventListener("click", async () => {
    state.cfg.apiBase = String(els["cfg-api-base"].value || "").trim() || DEFAULT_CFG.apiBase;
    saveConfig(state.cfg);
    closeConfigDrawer();
    await refreshAll();
  });

  els["department-select"].addEventListener("change", async (event) => {
    state.cfg.departmentId = String(event.target.value || "");
    saveConfig(state.cfg);
    await refreshOperationalData({ keepSelection: true });
    render();
  });

  els["case-status-filter"].addEventListener("change", async (event) => {
    state.cfg.caseStatus = String(event.target.value || "");
    saveConfig(state.cfg);
    await Promise.all([refreshCases({ keepSelection: true }), refreshAnalytics()]);
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

    const action = String(target.dataset.action || "");
    try {
      if (action === "new-case") {
        prepareNewCaseDraft();
        render();
        return;
      }
      if (action === "select-case") {
        await selectCase(String(target.dataset.id || ""));
        return;
      }
      if (action === "save-case") {
        await saveCaseFromForm();
        return;
      }
      if (action === "add-observation") {
        state.caseDraft = collectCaseDraftFromDom();
        state.caseDraft.latest_observations.push({ name: "", value: "", abnormal_flag: "normal" });
        render();
        return;
      }
      if (action === "remove-observation") {
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
      if (action === "new-account") {
        prepareNewAccountDraft();
        render();
        return;
      }
      if (action === "select-account") {
        selectAccount(String(target.dataset.username || ""));
        render();
        return;
      }
      if (action === "save-account") {
        await saveAccountFromForm();
        return;
      }
      if (action === "set-operator") {
        setCurrentOperator(String(target.dataset.username || ""));
        return;
      }
      if (action === "clear-search") {
        state.search = "";
        els["global-search"].value = "";
        await Promise.all([refreshCases({ keepSelection: true }), refreshAccounts({ keepSelection: true })]);
        render();
      }
    } catch (error) {
      handleError(error);
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeConfigDrawer();
    }
  });
}

function setView(view) {
  state.view = view;
  els["view-title"].textContent = VIEW_TITLES[view] || "后台管理";
  Array.from(els["nav-list"].querySelectorAll("[data-view]")).forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

async function refreshAll(options = {}) {
  state.loading = true;
  render();
  try {
    await refreshGatewayStatus();
    await refreshDepartments();
    await Promise.all([refreshAccounts({ keepSelection: !options.init }), refreshOperationalData({ keepSelection: !options.init })]);
    ensureCurrentOperator();
    state.lastSyncAt = new Date().toISOString();
  } finally {
    state.loading = false;
    render();
  }
}

async function refreshOperationalData(options = {}) {
  await Promise.all([refreshAnalytics(), refreshCases({ keepSelection: Boolean(options.keepSelection) }), refreshMonitorData()]);
}

async function refreshGatewayStatus() {
  try {
    state.gatewayHealth = await api("/health");
  } catch (error) {
    state.gatewayHealth = { status: "error", detail: errorText(error) };
  }
}

async function refreshDepartments() {
  const departments = normalizeArray(await api("/api/admin/departments"));
  state.departments = departments;
  const validIds = new Set(departments.map((item) => item.id));
  if (!validIds.has(state.cfg.departmentId)) {
    state.cfg.departmentId = pickPreferredDepartment(departments)?.id || "";
    saveConfig(state.cfg);
  }
  syncDepartmentSelect();
}

async function refreshAnalytics() {
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
  );
  state.cases = dedupeCases(rows).sort(compareCaseRows);

  const nextId = options.keepSelection && state.selectedCaseId && state.cases.some((item) => item.patient_id === state.selectedCaseId)
    ? state.selectedCaseId
    : state.cases[0]?.patient_id || "";

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
  );

  state.accounts = rows.sort(compareAccounts);
  ensureCurrentOperator();
  syncOperatorSelect();

  const nextUsername =
    options.keepSelection && state.selectedAccountUsername && state.accounts.some((item) => item.username === state.selectedAccountUsername)
      ? state.selectedAccountUsername
      : state.cfg.operatorUsername || state.accounts[0]?.username || "";

  if (nextUsername) {
    selectAccount(nextUsername);
  } else {
    prepareNewAccountDraft();
  }
}

async function refreshMonitorData() {
  if (!state.cfg.departmentId) {
    state.liveBeds = [];
    return;
  }

  const [beds, binding, sessions] = await Promise.allSettled([
    api(`/api/wards/${encodeURIComponent(state.cfg.departmentId)}/beds`),
    api("/api/device/binding"),
    api("/api/device/sessions"),
  ]);

  state.liveBeds = beds.status === "fulfilled" ? normalizeArray(beds.value) : [];
  state.binding = binding.status === "fulfilled" ? binding.value : { detail: errorText(binding.reason) };
  state.sessions = sessions.status === "fulfilled" ? normalizeArray(sessions.value) : [];
}

async function selectCase(patientId, options = {}) {
  if (!patientId) {
    prepareNewCaseDraft();
    render();
    return;
  }

  state.selectedCaseId = patientId;
  state.caseBundle = await api(`/api/admin/patient-cases/${encodeURIComponent(patientId)}`);
  state.caseDraft = bundleToCaseDraft(state.caseBundle);
  if (!options.silent) {
    render();
  }
}

function selectAccount(username) {
  if (!username) {
    prepareNewAccountDraft();
    return;
  }

  const account = state.accounts.find((item) => item.username === username);
  if (!account) return;
  state.selectedAccountUsername = username;
  state.accountDraft = accountToDraft(account);
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

async function saveCaseFromForm() {
  const draft = collectCaseDraftFromDom();
  if (!draft.full_name.trim()) {
    toast("无法保存病例", "请先填写患者姓名。", "err");
    return;
  }
  if (!draft.bed_no.trim()) {
    toast("无法保存病例", "请先填写床位号。", "err");
    return;
  }

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

  const bundle = await api("/api/admin/patient-cases", {
    method: "POST",
    body: payload,
  });

  state.caseBundle = bundle;
  state.caseDraft = bundleToCaseDraft(bundle);
  state.selectedCaseId = bundle?.patient?.id || state.selectedCaseId;
  toast("病例已保存", "病例资料已写入系统，软件端会读取同一份数据。", "ok");

  await Promise.all([refreshCases({ keepSelection: true }), refreshAnalytics(), refreshMonitorData()]);
  render();
}

async function saveAccountFromForm() {
  const draft = collectAccountDraftFromDom();
  if (!draft.username.trim()) {
    toast("无法保存账号", "请先填写账号名。", "err");
    return;
  }
  if (!draft.full_name.trim()) {
    toast("无法保存账号", "请先填写显示姓名。", "err");
    return;
  }

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

  const saved = await api("/api/admin/accounts/upsert", {
    method: "POST",
    body: payload,
  });

  if (!state.cfg.operatorUsername || state.cfg.operatorUsername === payload.username) {
    state.cfg.operatorUsername = payload.username;
    saveConfig(state.cfg);
  }

  toast("账号已保存", "账号信息已同步到系统登录账号和协同账号。", "ok");
  await refreshAccounts({ keepSelection: true });
  selectAccount(String(saved.username || payload.username));
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

function scheduleSearchRefresh() {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => {
    Promise.all([refreshCases({ keepSelection: true }), refreshAccounts({ keepSelection: true })])
      .then(() => render())
      .catch(handleError);
  }, 260);
}

function ensureCurrentOperator() {
  if (!state.accounts.length) {
    state.cfg.operatorUsername = "";
    saveConfig(state.cfg);
    return;
  }

  const hasSelected = state.accounts.some((item) => item.username === state.cfg.operatorUsername);
  if (!hasSelected) {
    state.cfg.operatorUsername = state.accounts.find((item) => item.status === "active")?.username || state.accounts[0].username;
    saveConfig(state.cfg);
  }
}

function setCurrentOperator(username) {
  if (!username) return;
  state.cfg.operatorUsername = username;
  saveConfig(state.cfg);
  syncOperatorSelect();
  render();
  toast("已切换当前操作账号", `${operatorLabel(getCurrentOperator())}`, "ok");
}

function syncDepartmentSelect() {
  const options = state.departments
    .map((item) => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.name)}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</option>`)
    .join("");
  els["department-select"].innerHTML = options;
  els["department-select"].value = state.cfg.departmentId || "";
}

function syncOperatorSelect() {
  const options = state.accounts
    .map((item) => {
      const suffix = item.status && item.status !== "active" ? ` · ${accountStatusLabel(item.status)}` : "";
      return `<option value="${escapeAttr(item.username)}">${escapeHtml(operatorLabel(item))}${suffix}</option>`;
    })
    .join("");
  els["operator-select"].innerHTML = options || `<option value="">暂无可切换账号</option>`;
  els["operator-select"].value = state.cfg.operatorUsername || "";
}

function syncConfigInputs() {
  els["cfg-api-base"].value = state.cfg.apiBase || DEFAULT_CFG.apiBase;
}

function syncFilterInputs() {
  els["global-search"].value = state.search;
  els["case-status-filter"].value = state.cfg.caseStatus || "";
  els["account-status-filter"].value = state.cfg.accountStatus || "";
}

function updateHeaderMeta() {
  const department = currentDepartment();
  els["current-department-name"].textContent = department?.name || "未选择病区";
  els["current-department-meta"].textContent = department
    ? `${department.code} · ${department.location || "未记录位置"}`
    : "请先选择需要管理的病区";

  const operator = getCurrentOperator();
  els["operator-name"].textContent = operator ? operator.full_name || operator.username : "未选择";
  els["operator-role"].textContent = operator
    ? `${roleLabel(operator.role_code)} · ${operator.department || "未填写科室"}`
    : "请在顶部切换当前操作账号";

  const status = gatewayStatusInfo();
  els["gateway-status"].textContent = status.label;
  els["gateway-status"].className = `status-chip ${status.tone}`;
}

function render() {
  syncFilterInputs();
  syncOperatorSelect();
  updateHeaderMeta();
  renderSystemStrip();

  if (state.loading && !state.departments.length && !state.accounts.length) {
    els["view-root"].innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>正在加载后台管理数据，请稍候...</p>
      </div>
    `;
    return;
  }

  if (state.view === "overview") {
    els["view-root"].innerHTML = renderOverviewView();
    return;
  }
  if (state.view === "cases") {
    els["view-root"].innerHTML = renderCasesView();
    return;
  }
  if (state.view === "accounts") {
    els["view-root"].innerHTML = renderAccountsView();
    return;
  }
  els["view-root"].innerHTML = renderMonitorView();
}

function renderSystemStrip() {
  const department = currentDepartment();
  const operator = getCurrentOperator();
  const caseCount = state.cases.length;
  const accountCount = state.accounts.length;
  const syncLabel = state.lastSyncAt ? formatDateTime(state.lastSyncAt) : "尚未同步";
  const health = gatewayStatusInfo();

  els["system-strip"].innerHTML = [
    renderSystemPill("当前病区", department?.name || "未选择", department?.location || "请先选择病区"),
    renderSystemPill("当前操作账号", operator?.full_name || "未选择", operator ? `${roleLabel(operator.role_code)} · ${operator.username}` : "可在顶部随时切换"),
    renderSystemPill("已载入病例", String(caseCount), caseCount ? "左侧列表与编辑区保持同一数据源" : "当前病区暂无病例"),
    renderSystemPill("可管理账号", String(accountCount), accountCount ? "账号编辑后会同步到软件账户数据" : "暂无账号数据"),
    renderSystemPill("网关状态", health.short, health.detail),
    renderSystemPill("最近同步", syncLabel, "点击右上角刷新可重新拉取最新状态"),
  ].join("");
}

function renderSystemPill(label, value, meta) {
  return `
    <article class="system-pill">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(meta)}</span>
    </article>
  `;
}

function renderOverviewView() {
  const analytics = state.analytics;
  const kpis = analytics?.kpis || [];
  const hotspots = analytics?.hotspots || [];
  const beds = state.liveBeds.slice(0, 12);

  return `
    <section class="dashboard-grid">
      <article class="panel panel-span-8">
        <div class="panel-header">
          <div>
            <h3>病区运行概况</h3>
            <p>用更接近护理站后台的方式看病区容量、待办压力和重点床位。</p>
          </div>
        </div>
        ${kpis.length ? `
          <div class="kpi-grid">
            ${kpis.map((item) => `
              <section class="kpi-card">
                <div class="kpi-label">${escapeHtml(item.label || item.key)}</div>
                <div class="kpi-value">${escapeHtml(String(item.value ?? 0))}</div>
                <div class="kpi-hint">${escapeHtml(item.hint || "—")}</div>
              </section>
            `).join("")}
          </div>
        ` : renderInlineEmpty("当前病区暂无总览统计。")}
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>当前工作环境</h3>
            <p>固定显示当前病区、操作账号和后台联通状态。</p>
          </div>
        </div>
        <div class="fact-list">
          ${renderFactRow("病区", currentDepartment()?.name || "未选择")}
          ${renderFactRow("位置", currentDepartment()?.location || "未记录")}
          ${renderFactRow("操作账号", operatorLabel(getCurrentOperator()) || "未选择")}
          ${renderFactRow("账号角色", roleLabel(getCurrentOperator()?.role_code))}
          ${renderFactRow("最近同步", state.lastSyncAt ? formatDateTime(state.lastSyncAt) : "尚未同步")}
          ${renderFactRow("设备网关", monitorStateLabel(state.binding))}
        </div>
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>患者状态分布</h3>
            <p>一眼看清在院、转科、出院结构。</p>
          </div>
        </div>
        ${renderDistributionList(analytics?.status_distribution || [])}
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>风险标签分布</h3>
            <p>用于判断当前病区是否存在集中预警。</p>
          </div>
        </div>
        ${renderDistributionList(analytics?.risk_distribution || [])}
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>待办任务分布</h3>
            <p>把处理压力和待办量压缩成易读的条目。</p>
          </div>
        </div>
        ${renderDistributionList(analytics?.task_distribution || [])}
      </article>

      <article class="panel panel-span-7">
        <div class="panel-header">
          <div>
            <h3>重点床位</h3>
            <p>按待办数和异常观测排序，便于班次交接时快速扫读。</p>
          </div>
        </div>
        ${hotspots.length ? `
          <div class="data-table hotspot-table">
            <div class="table-head">
              <div>床位</div>
              <div>患者</div>
              <div>分值</div>
              <div>提醒原因</div>
            </div>
            ${hotspots.map((item) => `
              <div class="table-row">
                <div class="mini-stack">
                  <strong>${escapeHtml(item.bed_no || "—")}</strong>
                  <span class="tiny-text">${escapeHtml(observationLevelLabel(item.latest_observation))}</span>
                </div>
                <div class="mini-stack">
                  <strong>${escapeHtml(item.patient_name || "未绑定患者")}</strong>
                  <span class="tiny-text">${escapeHtml(item.latest_observation || "暂无最新观察")}</span>
                </div>
                <div><span class="row-flag ${toneClassByScore(item.score)}">${escapeHtml(String(item.score ?? 0))}</span></div>
                <div>${escapeHtml((item.reasons || []).join("；") || "暂无原因")}</div>
              </div>
            `).join("")}
          </div>
        ` : renderInlineEmpty("当前病区暂无重点床位。")}
      </article>

      <article class="panel panel-span-5">
        <div class="panel-header">
          <div>
            <h3>床位占用快照</h3>
            <p>保留一页能扫完的床位视图，不再堆很多卡片。</p>
          </div>
        </div>
        ${beds.length ? `
          <div class="data-table bed-table">
            <div class="table-head">
              <div>床位</div>
              <div>患者</div>
              <div>状态</div>
              <div>待办</div>
            </div>
            ${beds.map((bed) => `
              <div class="table-row">
                <div class="mini-stack">
                  <strong>${escapeHtml(bed.bed_no || "—")}</strong>
                  <span class="tiny-text">${escapeHtml(bed.room_no || "—")} 房</span>
                </div>
                <div>${escapeHtml(bed.patient_name || "空床")}</div>
                <div><span class="row-flag ${bed.status === "occupied" ? "is-good" : "is-neutral"}">${escapeHtml(bedStatusLabel(bed.status))}</span></div>
                <div>${escapeHtml((bed.pending_tasks || []).slice(0, 2).join("；") || "无")}</div>
              </div>
            `).join("")}
          </div>
        ` : renderInlineEmpty("当前病区暂无床位数据。")}
      </article>
    </section>
  `;
}

function renderCasesView() {
  const draft = state.caseDraft || {};
  const cases = state.cases;
  const inHospital = cases.filter((item) => item.current_status === "admitted").length;
  const pendingCount = cases.filter((item) => (item.pending_tasks || []).length > 0).length;

  return `
    <section class="workspace-shell">
      <aside class="workspace-sidebar">
        <div class="sidebar-head">
          <div class="sidebar-head-row">
            <div>
              <h3 class="sidebar-title">病例列表</h3>
              <p class="sidebar-subtitle">左边只保留扫描、选择和新建，右边专心编辑，不再把一堆分析卡片塞进同一页。</p>
            </div>
            <button class="action-btn" data-action="new-case">新建病例</button>
          </div>
          <div class="sidebar-metrics">
            <span class="metric-chip is-neutral">共 ${cases.length} 例</span>
            <span class="metric-chip is-good">在院 ${inHospital} 例</span>
            <span class="metric-chip ${pendingCount ? "is-warn" : "is-good"}">有待办 ${pendingCount} 例</span>
            ${state.search ? `<button class="mini-btn" data-action="clear-search">清空检索</button>` : ""}
          </div>
        </div>

        <div class="record-list">
          ${cases.length ? cases.map((item) => renderCaseRow(item)).join("") : `
            <div class="empty-state">
              <div>当前筛选条件下没有病例。</div>
              <div class="empty-hint">可以切换病区、调整检索条件，或直接新建病例。</div>
            </div>
          `}
        </div>
      </aside>

      <article class="editor-shell">
        <div class="editor-topbar">
          <div class="editor-head-row">
            <div>
              <div class="section-kicker">病例编辑</div>
              <h3 class="editor-title">${escapeHtml(draft.full_name || "新建病例")}</h3>
              <p class="editor-subtitle">修改后的病例会直接写回系统病例库，软件端读取同一患者数据时会同步看到变化。</p>
            </div>
            <div class="editor-actions">
              <div class="operator-hint">当前操作账号：${escapeHtml(operatorLabel(getCurrentOperator()) || "未选择")}</div>
              <button class="action-btn" data-action="save-case">保存病例</button>
            </div>
          </div>
        </div>

        <div class="editor-form">
          <section class="form-section">
            <div class="form-section-header">
              <div>
                <h4>住院基本信息</h4>
                <div class="section-help">把基础识别信息放在一组里，避免左右来回找字段。</div>
              </div>
            </div>
            <div class="form-grid">
              ${renderField("病例 ID", "case-patient-id", draft.patient_id, { readonly: true })}
              ${renderField("就诊 ID", "case-encounter-id", draft.encounter_id)}
              ${renderField("床位号", "case-bed-no", draft.bed_no)}
              ${renderField("房间号", "case-room-no", draft.room_no)}
              ${renderField("姓名", "case-full-name", draft.full_name)}
              ${renderField("病历号 MRN", "case-mrn", draft.mrn)}
              ${renderField("住院号", "case-inpatient-no", draft.inpatient_no)}
              ${renderField("性别", "case-gender", draft.gender)}
              ${renderField("年龄", "case-age", draft.age, { type: "number" })}
              ${renderField("血型", "case-blood-type", draft.blood_type)}
              ${renderSelectField("当前状态", "case-current-status", draft.current_status, CASE_STATUS_OPTIONS)}
              ${renderField("当前病区", "case-department", currentDepartment()?.name || "未选择病区", { readonly: true })}
              ${renderTextareaField("过敏信息", "case-allergy-info", draft.allergy_info, { full: true, placeholder: "如：头孢过敏、青霉素过敏" })}
            </div>
          </section>

          <section class="form-section">
            <div class="form-section-header">
              <div>
                <h4>诊断、风险与待办</h4>
                <div class="section-help">统一用可编辑文本区承载结构化内容，支持按行维护。</div>
              </div>
            </div>
            <div class="form-grid">
              ${renderTextareaField("诊断列表", "case-diagnoses", draft.diagnosesText, { placeholder: "每行一条诊断" })}
              ${renderTextareaField("风险标签", "case-risk-tags", draft.riskTagsText, { placeholder: "每行一条风险标签" })}
              ${renderTextareaField("待办任务", "case-pending-tasks", draft.pendingTasksText, { full: true, placeholder: "每行一条待办任务" })}
            </div>
          </section>

          <section class="form-section">
            <div class="form-section-header">
              <div>
                <h4>最新观察</h4>
                <div class="section-help">保留最常用的三列：指标、结果、异常级别。</div>
              </div>
              <button class="action-btn-secondary" data-action="add-observation">新增观察</button>
            </div>
            <div class="observation-table">
              <div class="observation-head">
                <div>观察项</div>
                <div>结果</div>
                <div>异常级别</div>
                <div>操作</div>
              </div>
              ${(draft.latest_observations || []).map((item, index) => `
                <div class="observation-row" data-observation-row="${index}">
                  <input data-field="name" value="${escapeAttr(item.name || "")}" placeholder="如：血糖" />
                  <input data-field="value" value="${escapeAttr(item.value || "")}" placeholder="如：16.2 mmol/L" />
                  <select data-field="flag">
                    ${OBSERVATION_FLAGS.map((flag) => `<option value="${flag.value}" ${flag.value === (item.abnormal_flag || "normal") ? "selected" : ""}>${flag.label}</option>`).join("")}
                  </select>
                  <button class="mini-btn" data-action="remove-observation" data-index="${index}">移除</button>
                </div>
              `).join("")}
            </div>
          </section>
        </div>
      </article>
    </section>
  `;
}

function renderAccountsView() {
  const draft = state.accountDraft || {};
  const activeCount = state.accounts.filter((item) => item.status === "active").length;
  const operator = getCurrentOperator();

  return `
    <section class="workspace-shell">
      <aside class="workspace-sidebar">
        <div class="sidebar-head">
          <div class="sidebar-head-row">
            <div>
              <h3 class="sidebar-title">账号列表</h3>
              <p class="sidebar-subtitle">账号编辑和当前操作账号切换拆开处理，避免“我到底是在改账号，还是在切换视角”这种混乱。</p>
            </div>
            <button class="action-btn" data-action="new-account">新建账号</button>
          </div>
          <div class="sidebar-metrics">
            <span class="metric-chip is-neutral">共 ${state.accounts.length} 个</span>
            <span class="metric-chip is-good">启用 ${activeCount} 个</span>
            <span class="metric-chip ${operator ? "is-good" : "is-warn"}">当前 ${escapeHtml(operator?.username || "未选择")}</span>
          </div>
        </div>
        <div class="record-list">
          ${state.accounts.length ? state.accounts.map((item) => renderAccountRow(item)).join("") : `
            <div class="empty-state">
              <div>当前没有账号数据。</div>
              <div class="empty-hint">可以先新建账号，再设为当前操作账号。</div>
            </div>
          `}
        </div>
      </aside>

      <article class="editor-shell">
        <div class="editor-topbar">
          <div class="editor-head-row">
            <div>
              <div class="section-kicker">账号编辑</div>
              <h3 class="editor-title">${escapeHtml(draft.full_name || "新建账号")}</h3>
              <p class="editor-subtitle">保存后会同时更新系统登录账号和协同账号信息，软件端登录同一账号时会读取同一份资料。</p>
            </div>
            <div class="editor-actions">
              ${draft.username ? `<button class="action-btn-secondary" data-action="set-operator" data-username="${escapeAttr(draft.username)}">设为当前操作账号</button>` : ""}
              <button class="action-btn" data-action="save-account">保存账号</button>
            </div>
          </div>
        </div>

        <div class="editor-form">
          <section class="form-section">
            <div class="form-section-header">
              <div>
                <h4>账号基本信息</h4>
                <div class="section-help">先保证账号识别、角色和组织归属是清晰稳定的。</div>
              </div>
            </div>
            <div class="form-grid">
              ${renderField("内部 ID", "account-id", draft.id, { readonly: true })}
              ${renderField("账号名", "account-username", draft.username)}
              ${renderField("显示姓名", "account-full-name", draft.full_name)}
              ${renderSelectField("角色", "account-role", draft.role_code, ROLE_OPTIONS)}
              ${renderField("所属科室", "account-department", draft.department)}
              ${renderField("岗位/职称", "account-title", draft.title)}
              ${renderSelectField("账号状态", "account-status", draft.status, ACCOUNT_STATUS_OPTIONS)}
              ${renderField("重置密码", "account-password", draft.password, { placeholder: "留空则不修改密码" })}
            </div>
          </section>

          <section class="form-section">
            <div class="form-section-header">
              <div>
                <h4>联系方式</h4>
                <div class="section-help">联系方式独立一组，避免和权限字段混在一起。</div>
              </div>
            </div>
            <div class="form-grid">
              ${renderField("手机号", "account-phone", draft.phone)}
              ${renderField("邮箱", "account-email", draft.email)}
            </div>
          </section>
        </div>
      </article>
    </section>
  `;
}

function renderMonitorView() {
  const sessions = state.sessions;
  const beds = state.liveBeds;

  return `
    <section class="monitor-grid">
      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>网关健康</h3>
            <p>用于确认后台入口和微服务是否在线。</p>
          </div>
        </div>
        <div class="fact-list">
          ${renderFactRow("API 网关", gatewayStatusInfo().label)}
          ${renderFactRow("设备绑定", monitorStateLabel(state.binding))}
          ${renderFactRow("会话数量", String(sessions.length))}
          ${renderFactRow("床位快照", `${beds.length} 条`)}
        </div>
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>设备绑定状态</h3>
            <p>如果设备网关未联通，这里会明确提示，不再用复杂卡片绕弯。</p>
          </div>
        </div>
        ${renderMonitorBinding()}
      </article>

      <article class="panel panel-span-4">
        <div class="panel-header">
          <div>
            <h3>活跃会话</h3>
            <p>用于查看设备接入链路当前是否有正在执行的会话。</p>
          </div>
        </div>
        ${sessions.length ? `
          <div class="status-list">
            ${sessions.map((item) => `
              <div class="status-row">
                <span class="status-label">${escapeHtml(item.session_id || item.id || "会话")}</span>
                <span class="status-value">${escapeHtml(item.status || "unknown")}</span>
              </div>
            `).join("")}
          </div>
        ` : renderInlineEmpty("当前没有活跃设备会话。")}
      </article>

      <article class="panel panel-span-12">
        <div class="panel-header">
          <div>
            <h3>床位状态快照</h3>
            <p>保持成规则表格，适合排班和后台巡视时快速扫读。</p>
          </div>
        </div>
        ${beds.length ? `
          <div class="data-table bed-table">
            <div class="table-head">
              <div>床位</div>
              <div>患者</div>
              <div>状态</div>
              <div>待办</div>
            </div>
            ${beds.map((bed) => `
              <div class="table-row">
                <div class="mini-stack">
                  <strong>${escapeHtml(bed.bed_no || "—")}</strong>
                  <span class="tiny-text">${escapeHtml(bed.room_no || "—")} 房</span>
                </div>
                <div>${escapeHtml(bed.patient_name || "空床")}</div>
                <div><span class="row-flag ${bed.status === "occupied" ? "is-good" : "is-neutral"}">${escapeHtml(bedStatusLabel(bed.status))}</span></div>
                <div>${escapeHtml((bed.pending_tasks || []).slice(0, 2).join("；") || "无")}</div>
              </div>
            `).join("")}
          </div>
        ` : renderInlineEmpty("当前病区暂无床位快照。")}
      </article>
    </section>
  `;
}

function renderCaseRow(item) {
  const active = item.patient_id === state.selectedCaseId ? "active" : "";
  const taskCount = (item.pending_tasks || []).length;
  const riskCount = (item.risk_tags || []).length;
  const tone = toneClassByObservation(item.latest_observation);
  const time = formatShortTime(item.updated_at);

  return `
    <button class="record-row ${active}" data-action="select-case" data-id="${escapeAttr(item.patient_id)}">
      <div class="record-row-top">
        <div class="record-primary">
          <div class="record-title-line">
            <span class="tag is-neutral">${escapeHtml(item.bed_no || "未分床")}${item.bed_no ? " 床" : ""}</span>
            <strong class="record-title">${escapeHtml(item.full_name || "未命名患者")}</strong>
            <span class="tiny-text">${escapeHtml(`${item.gender || "未知"} · ${item.age ?? "—"} 岁 · ${item.mrn || "未填 MRN"}`)}</span>
          </div>
          <div class="record-meta">${escapeHtml(`${item.room_no || "—"} 房 · ${caseStatusLabel(item.current_status)} · ${item.department_name || "未归属病区"}`)}</div>
          <div class="record-subline">${escapeHtml(item.latest_observation || "暂无最新观察")}</div>
          <div class="record-tags">
            <span class="tag ${taskCount ? "is-warn" : "is-good"}">待办 ${taskCount} 项</span>
            <span class="tag ${riskCount ? "is-bad" : "is-good"}">风险 ${riskCount} 项</span>
            <span class="tag ${tone}">${escapeHtml(time)}</span>
          </div>
        </div>
      </div>
    </button>
  `;
}

function renderAccountRow(item) {
  const active = item.username === state.selectedAccountUsername ? "active" : "";
  const isOperator = item.username === state.cfg.operatorUsername;

  return `
    <button class="record-row ${active}" data-action="select-account" data-username="${escapeAttr(item.username || "")}">
      <div class="record-row-top">
        <div class="record-primary">
          <div class="record-title-line">
            <strong class="record-title">${escapeHtml(item.full_name || item.username || "未命名账号")}</strong>
            ${isOperator ? `<span class="tag is-neutral">当前操作账号</span>` : ""}
          </div>
          <div class="record-meta">${escapeHtml(`${item.username || "—"} · ${roleLabel(item.role_code)} · ${item.department || "未填写科室"}`)}</div>
          <div class="record-subline">${escapeHtml(item.title || "未填写岗位")}</div>
          <div class="record-tags">
            <span class="tag ${accountStatusTone(item.status)}">${escapeHtml(accountStatusLabel(item.status))}</span>
            <span class="tag is-neutral">${escapeHtml(item.email || item.phone || "未填写联系方式")}</span>
          </div>
        </div>
      </div>
    </button>
  `;
}

function renderDistributionList(items) {
  if (!items.length) {
    return renderInlineEmpty("当前病区暂无统计条目。");
  }

  const max = Math.max(...items.map((item) => Number(item.value || 0)), 1);
  return `
    <div class="distribution-list">
      ${items.map((item) => `
        <div class="distribution-item">
          <div class="distribution-meta">
            <span class="distribution-label">${escapeHtml(item.label || "未命名")}</span>
            <span class="distribution-value">${escapeHtml(String(item.value || 0))}</span>
          </div>
          <div class="distribution-bar">
            <span style="width:${Math.max(8, (Number(item.value || 0) / max) * 100)}%"></span>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderMonitorBinding() {
  if (!state.binding) {
    return renderInlineEmpty("尚未获取设备绑定状态。");
  }
  if (state.binding.detail) {
    return renderInlineEmpty(`设备网关当前不可用：${state.binding.detail}`);
  }

  const entries = Object.entries(state.binding);
  return entries.length ? `
    <div class="status-list">
      ${entries.map(([key, value]) => `
        <div class="status-row">
          <span class="status-label">${escapeHtml(key)}</span>
          <span class="status-value">${escapeHtml(stringifyValue(value))}</span>
        </div>
      `).join("")}
    </div>
  ` : renderInlineEmpty("当前没有设备绑定数据。");
}

function renderField(label, id, value, options = {}) {
  const type = options.type || "text";
  const readonly = options.readonly ? "readonly" : "";
  const fieldClass = options.readonly ? "field field-readonly" : "field";
  const full = options.full ? " field-full" : "";
  return `
    <label class="${fieldClass}${full}">
      <span>${escapeHtml(label)}</span>
      <input id="${escapeAttr(id)}" type="${escapeAttr(type)}" value="${escapeAttr(value ?? "")}" placeholder="${escapeAttr(options.placeholder || "")}" ${readonly} />
    </label>
  `;
}

function renderTextareaField(label, id, value, options = {}) {
  const full = options.full ? " field-full" : "";
  return `
    <label class="field${full}">
      <span>${escapeHtml(label)}</span>
      <textarea id="${escapeAttr(id)}" class="textarea-compact" placeholder="${escapeAttr(options.placeholder || "")}">${escapeHtml(value ?? "")}</textarea>
    </label>
  `;
}

function renderSelectField(label, id, value, options) {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <select id="${escapeAttr(id)}">
        ${options.map((item) => `
          <option value="${escapeAttr(item.value)}" ${item.value === value ? "selected" : ""}>${escapeHtml(item.label)}</option>
        `).join("")}
      </select>
    </label>
  `;
}

function renderFactRow(label, value) {
  return `
    <div class="fact-row">
      <span class="fact-label">${escapeHtml(label)}</span>
      <span class="fact-value">${escapeHtml(value || "—")}</span>
    </div>
  `;
}

function renderInlineEmpty(text) {
  return `<div class="empty-state"><div>${escapeHtml(text)}</div></div>`;
}

async function api(path, options = {}) {
  const url = new URL(path, ensureApiBase());
  const params = options.params || {};
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    url.searchParams.set(key, String(value));
  });

  const requestInit = {
    method: options.method || "GET",
    headers: {},
    cache: "no-store",
  };

  if (options.body !== undefined) {
    requestInit.headers["Content-Type"] = "application/json";
    requestInit.body = JSON.stringify(options.body);
  }

  const response = await fetch(url.toString(), requestInit);
  const raw = await response.text();
  const data = raw ? tryParseJson(raw) : null;

  if (!response.ok) {
    const detail = data?.detail || data?.message || raw || `${response.status} ${response.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}

function ensureApiBase() {
  return state.cfg.apiBase || DEFAULT_CFG.apiBase;
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_CFG };
    return { ...DEFAULT_CFG, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CFG };
  }
}

function saveConfig(cfg) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

function closeConfigDrawer() {
  els["config-drawer"].classList.add("hidden");
}

function currentDepartment() {
  return state.departments.find((item) => item.id === state.cfg.departmentId) || null;
}

function getCurrentOperator() {
  return state.accounts.find((item) => item.username === state.cfg.operatorUsername) || null;
}

function gatewayStatusInfo() {
  if (state.gatewayHealth?.status === "ok") {
    return {
      label: "网关在线",
      short: "在线",
      detail: "后台 API 网关可正常访问",
      tone: "is-good",
    };
  }
  if (state.gatewayHealth?.detail) {
    return {
      label: "网关异常",
      short: "异常",
      detail: String(state.gatewayHealth.detail),
      tone: "is-bad",
    };
  }
  return {
    label: "网关待检测",
    short: "待检测",
    detail: "尚未完成网关状态检查",
    tone: "is-neutral",
  };
}

function pickPreferredDepartment(departments) {
  if (!departments.length) return null;
  return (
    departments.find((item) => item.id === "11111111-1111-1111-1111-111111111001") ||
    departments.find((item) => String(item.name || "").includes("护理单元")) ||
    departments.find((item) => String(item.code || "").includes("CARD")) ||
    departments[0]
  );
}

function compareCaseRows(a, b) {
  const bedA = Number.parseInt(String(a.bed_no || "9999"), 10);
  const bedB = Number.parseInt(String(b.bed_no || "9999"), 10);
  if (Number.isFinite(bedA) && Number.isFinite(bedB) && bedA !== bedB) {
    return bedA - bedB;
  }
  return String(a.full_name || "").localeCompare(String(b.full_name || ""), "zh-CN");
}

function compareAccounts(a, b) {
  if (a.status !== b.status) {
    return a.status === "active" ? -1 : 1;
  }
  return String(a.full_name || a.username || "").localeCompare(String(b.full_name || b.username || ""), "zh-CN");
}

function dedupeCases(rows) {
  const map = new Map();
  rows.forEach((item) => {
    const key = String(item.patient_id || "");
    if (!key) return;
    const current = map.get(key);
    if (!current) {
      map.set(key, item);
      return;
    }
    const currentTime = new Date(current.updated_at || 0).getTime();
    const nextTime = new Date(item.updated_at || 0).getTime();
    if (nextTime >= currentTime) {
      map.set(key, item);
    }
  });
  return Array.from(map.values());
}

function normalizeArray(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.value)) return data.value;
  return [];
}

function listToText(items) {
  return normalizeArray(items).map((item) => String(item || "").trim()).filter(Boolean).join("\n");
}

function parseTextList(text) {
  return String(text || "")
    .split(/\r?\n|,|，|；|;/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function monitorStateLabel(binding) {
  if (!binding) return "未检测";
  if (binding.detail) return "不可用";
  return "在线";
}

function operatorLabel(operator) {
  if (!operator) return "";
  return `${operator.full_name || operator.username}${operator.username ? `（${operator.username}）` : ""}`;
}

function roleLabel(roleCode) {
  return ROLE_OPTIONS.find((item) => item.value === roleCode)?.label || roleCode || "未设定角色";
}

function caseStatusLabel(status) {
  return CASE_STATUS_OPTIONS.find((item) => item.value === status)?.label || status || "未设定";
}

function accountStatusLabel(status) {
  return ACCOUNT_STATUS_OPTIONS.find((item) => item.value === status)?.label || status || "未设定";
}

function accountStatusTone(status) {
  if (status === "active") return "is-good";
  if (status === "inactive") return "is-neutral";
  return "is-bad";
}

function bedStatusLabel(status) {
  if (status === "occupied") return "已占用";
  if (status === "free") return "空闲";
  return status || "未知";
}

function observationLevelLabel(text) {
  const lower = String(text || "").toLowerCase();
  if (lower.includes("critical")) return "危急观察";
  if (lower.includes("high")) return "偏高观察";
  if (lower.includes("low")) return "偏低观察";
  return "常规观察";
}

function toneClassByObservation(text) {
  const lower = String(text || "").toLowerCase();
  if (lower.includes("critical")) return "is-bad";
  if (lower.includes("high")) return "is-warn";
  if (lower.includes("low")) return "is-neutral";
  return "is-good";
}

function toneClassByScore(score) {
  const value = Number(score || 0);
  if (value >= 3) return "is-bad";
  if (value >= 1) return "is-warn";
  return "is-good";
}

function formatShortTime(value) {
  if (!value) return "未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未同步";
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function emptyToNull(value) {
  const text = String(value || "").trim();
  return text ? text : null;
}

function numberOrNull(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function valueOf(id) {
  return String(document.getElementById(id)?.value || "");
}

function stringifyValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function tryParseJson(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function errorText(error) {
  if (!error) return "未知错误";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message || error.name;
  try {
    return JSON.stringify(error);
  } catch {
    return "未知错误";
  }
}

function handleError(error) {
  console.error(error);
  toast("操作失败", errorText(error), "err");
}

function toast(title, copy, tone = "ok") {
  const node = document.createElement("div");
  node.className = `toast is-${tone}`;
  node.innerHTML = `
    <p class="toast-title">${escapeHtml(title)}</p>
    <p class="toast-copy">${escapeHtml(copy)}</p>
  `;
  els["toast-stack"].appendChild(node);
  setTimeout(() => {
    node.remove();
  }, 3600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", "&#10;");
}
