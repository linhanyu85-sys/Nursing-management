"use strict";

const STORAGE_KEY = "ai_nursing_admin_console_v2";

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
};

const state = {
  cfg: loadConfig(),
  view: "overview",
  loading: false,
  search: "",
  departments: [],
  analytics: null,
  cases: [],
  caseBundle: null,
  caseDraft: null,
  caseActivity: { documents: [], recommendations: [], handovers: [] },
  accounts: [],
  accountDraft: null,
  gatewayHealth: null,
  runtime: null,
  binding: null,
  sessions: [],
  liveBeds: [],
  wardSocket: null,
  softRefreshTimer: null,
  lastSyncAt: null,
  monitorLogs: [],
};

const els = {};

const ROLE_OPTIONS = [
  "nurse",
  "senior_nurse",
  "charge_nurse",
  "resident_doctor",
  "attending_doctor",
  "consultant",
  "admin",
  "auditor",
];

boot().catch((error) => {
  console.error(error);
  toast(`初始化失败：${errorText(error)}`, "err");
});

async function boot() {
  cacheEls();
  bindStaticEvents();
  syncConfigInputs();
  syncFilterInputs();
  setView(state.view);
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
    "owner-avatar",
    "owner-name",
    "owner-id",
    "status-ribbon",
    "toast-stack",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindStaticEvents() {
  els["nav-list"].addEventListener("click", (event) => {
    const target = event.target.closest("[data-view]");
    if (!target) return;
    setView(target.dataset.view || "overview");
    render();
  });

  els["refresh-btn"].addEventListener("click", () => {
    refreshAll().catch(handleError);
  });

  els["open-config-btn"].addEventListener("click", () => {
    syncConfigInputs();
    els["config-drawer"].classList.remove("hidden");
  });
  els["close-config-btn"].addEventListener("click", closeConfigDrawer);
  els["save-config-btn"].addEventListener("click", async () => {
    state.cfg.apiBase = String(els["cfg-api-base"].value || "").trim() || DEFAULT_CFG.apiBase;
    saveConfig(state.cfg);
    closeConfigDrawer();
    await refreshAll();
  });

  els["global-search"].addEventListener("input", (event) => {
    state.search = String(event.target.value || "").trim().toLowerCase();
    render();
  });

  els["department-select"].addEventListener("change", async (event) => {
    state.cfg.departmentId = String(event.target.value || "");
    saveConfig(state.cfg);
    connectWardSocket();
    await refreshOperationalData({ keepSelection: true });
  });

  els["case-status-filter"].addEventListener("change", async (event) => {
    state.cfg.caseStatus = String(event.target.value || "");
    saveConfig(state.cfg);
    await refreshCases({ keepSelection: true });
    if (state.view === "overview") {
      await refreshAnalytics();
    }
    render();
  });

  els["account-status-filter"].addEventListener("change", async (event) => {
    state.cfg.accountStatus = String(event.target.value || "");
    saveConfig(state.cfg);
    await refreshAccounts({ keepSelection: true });
    render();
  });

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action || "";
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
      state.caseDraft.latest_observations.push({ name: "", value: "", abnormal_flag: "" });
      render();
      return;
    }
    if (action === "remove-observation") {
      const index = Number(target.dataset.index || -1);
      if (index >= 0) {
        state.caseDraft = collectCaseDraftFromDom();
        state.caseDraft.latest_observations.splice(index, 1);
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
    }
  });
}

function setView(view) {
  state.view = view;
  const titleMap = {
    overview: "病区总览",
    cases: "病例工作台",
    accounts: "账号中心",
    monitor: "联通监控",
  };
  els["view-title"].textContent = titleMap[view] || "护理后台";
  for (const button of Array.from(els["nav-list"].querySelectorAll("[data-view]"))) {
    button.classList.toggle("active", button.dataset.view === view);
  }
}

async function refreshAll(options = {}) {
  state.loading = true;
  render();
  await Promise.all([
    refreshGatewayStatus(),
    refreshDepartments({ init: Boolean(options.init) }),
    refreshOperationalData({ keepSelection: true }),
    refreshAccounts({ keepSelection: true }),
  ]);
  state.loading = false;
  state.lastSyncAt = new Date().toISOString();
  render();
}

async function refreshOperationalData(options = {}) {
  await Promise.all([
    refreshAnalytics(),
    refreshCases({ keepSelection: Boolean(options.keepSelection) }),
    refreshMonitorData(),
  ]);
}

async function refreshGatewayStatus() {
  const [health, runtime] = await Promise.allSettled([api("/health"), api("/api/ai/runtime")]);
  state.gatewayHealth = health.status === "fulfilled" ? health.value : null;
  state.runtime = runtime.status === "fulfilled" ? runtime.value : null;
  updateGatewayChip();
}

async function refreshDepartments(options = {}) {
  const departments = await api("/api/admin/departments");
  state.departments = Array.isArray(departments) ? departments : [];
  if (!state.cfg.departmentId && state.departments.length) {
    state.cfg.departmentId = state.departments[0].id || state.departments[0].code || "";
  }
  if (options.init || !state.cfg.departmentId) {
    saveConfig(state.cfg);
  }
  syncDepartmentSelect();
  updateDepartmentLabel();
  connectWardSocket();
}

async function refreshAnalytics() {
  if (!state.cfg.departmentId && !state.departments.length) {
    state.analytics = null;
    return;
  }
  state.analytics = await api(`/api/admin/ward-analytics?department_id=${encodeURIComponent(state.cfg.departmentId || "")}`);
}

async function refreshCases(options = {}) {
  const previousId = options.keepSelection ? state.caseDraft?.patient_id || state.caseBundle?.patient?.id || "" : "";
  const params = new URLSearchParams();
  if (state.cfg.departmentId) params.set("department_id", state.cfg.departmentId);
  if (state.cfg.caseStatus) params.set("current_status", state.cfg.caseStatus);
  if (state.search) params.set("query", state.search);
  params.set("limit", "240");
  const rows = await api(`/api/admin/patient-cases?${params.toString()}`);
  state.cases = Array.isArray(rows) ? rows : [];
  if (state.cases.length === 0) {
    state.caseBundle = null;
    state.caseDraft = null;
    return;
  }
  const selectedId =
    previousId ||
    state.caseDraft?.patient_id ||
    state.caseBundle?.patient?.id ||
    state.cases[0].patient_id;
  await selectCase(selectedId, { silent: true, allowFallback: true });
}

async function refreshAccounts(options = {}) {
  const previousUsername = options.keepSelection ? state.accountDraft?.username || "" : "";
  const params = new URLSearchParams();
  if (state.search) params.set("query", state.search);
  if (state.cfg.accountStatus) params.set("status_filter", state.cfg.accountStatus);
  const rows = await api(`/api/admin/accounts?${params.toString()}`);
  state.accounts = Array.isArray(rows) ? rows : [];
  if (state.accounts.length === 0) {
    state.accountDraft = null;
    updateOwnerCard();
    return;
  }
  const selected = previousUsername || state.accountDraft?.username || state.accounts[0].username;
  selectAccount(selected || state.accounts[0].username);
}

async function refreshMonitorData() {
  const [bindingResult, sessionsResult] = await Promise.allSettled([
    api("/api/device/binding"),
    api("/api/device/sessions"),
  ]);
  state.binding = bindingResult.status === "fulfilled" ? bindingResult.value : null;
  state.sessions =
    sessionsResult.status === "fulfilled" && Array.isArray(sessionsResult.value?.sessions)
      ? sessionsResult.value.sessions
      : [];
}

async function selectCase(patientId, options = {}) {
  const targetId = String(patientId || "").trim();
  if (!targetId) return;
  let found = state.cases.find((item) => item.patient_id === targetId);
  if (!found && options.allowFallback) {
    found = state.cases[0];
  }
  if (!found) return;

  const bundle = await api(`/api/admin/patient-cases/${encodeURIComponent(found.patient_id)}`);
  state.caseBundle = bundle;
  state.caseDraft = buildCaseDraft(bundle);
  await refreshCaseActivity(found.patient_id);
  render();
  if (!options.silent) {
    toast(`已载入病例：${bundle.patient.full_name}`, "ok");
  }
}

function selectAccount(username) {
  const account = state.accounts.find((item) => item.username === username || item.account === username);
  if (!account) return;
  state.accountDraft = buildAccountDraft(account);
  updateOwnerCard();
}

async function refreshCaseActivity(patientId) {
  const [docs, recs, handovers] = await Promise.allSettled([
    api(`/api/document/history?patient_id=${encodeURIComponent(patientId)}&limit=6`),
    api(`/api/recommendation/${encodeURIComponent(patientId)}/history?limit=6`),
    api(`/api/handover/${encodeURIComponent(patientId)}/history?limit=6`),
  ]);
  state.caseActivity = {
    documents: docs.status === "fulfilled" && Array.isArray(docs.value) ? docs.value : [],
    recommendations: recs.status === "fulfilled" && Array.isArray(recs.value) ? recs.value : [],
    handovers: handovers.status === "fulfilled" && Array.isArray(handovers.value) ? handovers.value : [],
  };
}

function prepareNewCaseDraft() {
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
    diagnoses: [""],
    risk_tags: [],
    pending_tasks: [],
    latest_observations: [{ name: "", value: "", abnormal_flag: "" }],
  };
  state.caseActivity = { documents: [], recommendations: [], handovers: [] };
}

function prepareNewAccountDraft() {
  state.accountDraft = {
    id: "",
    username: "",
    account: "",
    full_name: "",
    role_code: "nurse",
    phone: "",
    email: "",
    department: currentDepartment()?.name || "",
    title: "",
    status: "active",
    password: "",
  };
  updateOwnerCard();
}

function buildCaseDraft(bundle) {
  const patient = bundle?.patient || {};
  const bed = bundle?.bed || {};
  const context = bundle?.context || {};
  return {
    patient_id: patient.id || "",
    encounter_id: context.encounter_id || "",
    bed_no: bed.bed_no || context.bed_no || "",
    room_no: bed.room_no || "",
    full_name: patient.full_name || "",
    mrn: patient.mrn || "",
    inpatient_no: patient.inpatient_no || "",
    gender: patient.gender || "",
    age: patient.age ?? "",
    blood_type: patient.blood_type || "",
    allergy_info: patient.allergy_info || "",
    current_status: patient.current_status || "admitted",
    diagnoses: Array.isArray(context.diagnoses) && context.diagnoses.length ? context.diagnoses : [""],
    risk_tags: Array.isArray(context.risk_tags) ? context.risk_tags : [],
    pending_tasks: Array.isArray(context.pending_tasks) ? context.pending_tasks : [],
    latest_observations:
      Array.isArray(context.latest_observations) && context.latest_observations.length
        ? context.latest_observations.map((item) => ({
            name: item.name || "",
            value: item.value || "",
            abnormal_flag: item.abnormal_flag || "",
          }))
        : [{ name: "", value: "", abnormal_flag: "" }],
  };
}

function buildAccountDraft(account) {
  return {
    id: account.id || "",
    username: account.username || account.account || "",
    account: account.account || account.username || "",
    full_name: account.full_name || "",
    role_code: account.role_code || "nurse",
    phone: account.phone || "",
    email: account.email || "",
    department: account.department || "",
    title: account.title || "",
    status: account.status || "active",
    password: "",
  };
}

function collectCaseDraftFromDom() {
  const draft = {
    patient_id: fieldValue("case-patient-id"),
    encounter_id: fieldValue("case-encounter-id"),
    bed_no: fieldValue("case-bed-no"),
    room_no: fieldValue("case-room-no"),
    full_name: fieldValue("case-full-name"),
    mrn: fieldValue("case-mrn"),
    inpatient_no: fieldValue("case-inpatient-no"),
    gender: fieldValue("case-gender"),
    age: fieldValue("case-age"),
    blood_type: fieldValue("case-blood-type"),
    allergy_info: fieldValue("case-allergy-info"),
    current_status: fieldValue("case-current-status") || "admitted",
    diagnoses: parseLines(fieldValue("case-diagnoses")),
    risk_tags: parseLines(fieldValue("case-risk-tags")),
    pending_tasks: parseLines(fieldValue("case-pending-tasks")),
    latest_observations: [],
  };

  for (const row of Array.from(document.querySelectorAll("[data-observation-row]"))) {
    const name = row.querySelector("[data-observation-name]")?.value || "";
    const value = row.querySelector("[data-observation-value]")?.value || "";
    const abnormalFlag = row.querySelector("[data-observation-flag]")?.value || "";
    if (!name && !value) continue;
    draft.latest_observations.push({ name, value, abnormal_flag: abnormalFlag });
  }
  if (draft.latest_observations.length === 0) {
    draft.latest_observations.push({ name: "", value: "", abnormal_flag: "" });
  }
  return draft;
}

function collectAccountDraftFromDom() {
  return {
    id: fieldValue("account-id"),
    username: fieldValue("account-username"),
    account: fieldValue("account-username"),
    full_name: fieldValue("account-full-name"),
    role_code: fieldValue("account-role-code") || "nurse",
    phone: fieldValue("account-phone"),
    email: fieldValue("account-email"),
    department: fieldValue("account-department"),
    title: fieldValue("account-title"),
    status: fieldValue("account-status") || "active",
    password: fieldValue("account-password"),
  };
}

async function saveCaseFromForm() {
  const draft = collectCaseDraftFromDom();
  if (!draft.full_name || !draft.bed_no) {
    toast("病例至少需要患者姓名和床位号", "warn");
    return;
  }
  await api("/api/admin/patient-cases", {
    method: "POST",
    body: {
      patient_id: draft.patient_id || null,
      encounter_id: draft.encounter_id || null,
      bed_no: draft.bed_no,
      room_no: draft.room_no || null,
      full_name: draft.full_name,
      mrn: draft.mrn || null,
      inpatient_no: draft.inpatient_no || null,
      gender: draft.gender || null,
      age: draft.age === "" ? null : Number(draft.age || 0),
      blood_type: draft.blood_type || null,
      allergy_info: draft.allergy_info || null,
      current_status: draft.current_status || "admitted",
      diagnoses: draft.diagnoses,
      risk_tags: draft.risk_tags,
      pending_tasks: draft.pending_tasks,
      latest_observations: draft.latest_observations.filter((item) => item.name || item.value),
    },
  });
  addMonitorLog("病例保存", `${draft.full_name} / ${draft.bed_no}床`);
  toast("病例已保存到主系统", "ok");
  await refreshOperationalData({ keepSelection: false });
}

async function saveAccountFromForm() {
  const draft = collectAccountDraftFromDom();
  if (!draft.username || !draft.full_name) {
    toast("账号至少需要用户名和姓名", "warn");
    return;
  }
  const result = await api("/api/admin/accounts/upsert", {
    method: "POST",
    body: {
      id: draft.id || null,
      username: draft.username,
      full_name: draft.full_name,
      role_code: draft.role_code,
      phone: draft.phone || null,
      email: draft.email || null,
      department: draft.department || null,
      title: draft.title || null,
      status: draft.status || "active",
      password: draft.password || null,
    },
  });
  addMonitorLog("账号同步", `${draft.username} 已写入登录与协同服务`);
  toast("账号已同步到软件登录与协同侧", "ok");
  await refreshAccounts({ keepSelection: false });
  if (result?.username) {
    selectAccount(result.username);
    render();
  }
}

function render() {
  renderStatusRibbon();
  updateDepartmentLabel();
  updateOwnerCard();
  if (state.loading) {
    els["view-root"].innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>正在同步后台管理数据...</p>
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

function renderOverviewView() {
  const analytics = state.analytics;
  if (!analytics) {
    return `<div class="empty-state"><p>暂无病区分析数据，请先检查病区与网关配置。</p></div>`;
  }
  const kpis = Array.isArray(analytics.kpis) ? analytics.kpis : [];
  const primary = kpis.slice(0, 4);
  return `
    <section class="hero-surface">
      <div class="hero-copy">
        <div class="eyebrow">Ward Intelligence</div>
        <h3>${escapeHtml(analytics.department_name || "病区总览")} 正在以同一套业务数据驱动软件端与后台端</h3>
        <p>后台改病例、改账号、改病区数据后，软件端会直接读取同一套服务数据源。当前总览把病区占床、风险压力、待办负荷和热点床位收拢到一屏完成判断。</p>
        <div class="kpi-strip">
          ${primary.map(renderKpiItem).join("")}
        </div>
      </div>
      <div class="hero-stat-grid">
        ${kpis.slice(0, 4).map(renderHeroStat).join("")}
      </div>
    </section>

    <section class="overview-grid">
      <div class="stack">
        <article class="surface">
          <div class="surface-head">
            <div>
              <div class="eyebrow">Distribution</div>
              <h3>病区状态分布</h3>
              <p>按患者状态、风险观测和任务状态快速判断病区压力结构。</p>
            </div>
          </div>
          <div class="stack">
            ${renderDistributionBlock("患者状态", analytics.status_distribution)}
            ${renderDistributionBlock("异常观测", analytics.risk_distribution)}
            ${renderDistributionBlock("任务队列", analytics.task_distribution)}
          </div>
        </article>

        <article class="surface">
          <div class="surface-head">
            <div>
              <div class="eyebrow">Live Beds</div>
              <h3>当前在床视图</h3>
              <p>这里优先展示当前病区的占床患者，作为病例工作台的入口。</p>
            </div>
          </div>
          <div class="bed-strip">
            ${state.cases.slice(0, 12).map(renderBedTile).join("") || `<div class="empty-copy">当前病区暂无病例。</div>`}
          </div>
        </article>
      </div>

      <article class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Hotspots</div>
            <h3>病区热点床位</h3>
            <p>按异常观测和待办任务叠加排序，优先暴露最需要管理层介入的位置。</p>
          </div>
          <div class="soft-pill ok">${fmtTime(analytics.generated_at)}</div>
        </div>
        <div class="hotspot-list">
          ${(analytics.hotspots || []).map(renderHotspot).join("") || `<div class="empty-copy">暂无热点床位。</div>`}
        </div>
      </article>
    </section>
  `;
}

function renderCasesView() {
  return `
    <section class="cases-layout">
      <aside class="sidebar-surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Patient Cases</div>
            <h3>病例列表</h3>
            <p>选择患者后可直接修改病例、风险标签、待办和观察值。</p>
          </div>
          <button class="secondary-btn" data-action="new-case">
            <span class="material-symbols-outlined">add</span>
            <span>新建病例</span>
          </button>
        </div>
        <div class="sidebar-scroll">
          ${(filteredCases().map(renderCaseRow).join("")) || `<div class="empty-copy">没有匹配到病例。</div>`}
        </div>
      </aside>

      <section class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Case Editor</div>
            <h3>${escapeHtml(state.caseDraft?.full_name || "新建病例")}</h3>
            <p>保存后会直接写入主系统病例库，软件端读取相同数据时会立即看到变化。</p>
          </div>
          <div class="inline-actions">
            <button class="ghost-btn" data-action="new-case">
              <span class="material-symbols-outlined">edit_square</span>
              <span>重置表单</span>
            </button>
            <button class="primary-btn" data-action="save-case">
              <span class="material-symbols-outlined">save</span>
              <span>保存到主系统</span>
            </button>
          </div>
        </div>
        ${renderCaseForm()}
      </section>
    </section>
  `;
}

function renderCaseForm() {
  const draft = state.caseDraft;
  if (!draft) {
    return `<div class="empty-copy">请选择一个病例，或点击“新建病例”。</div>`;
  }
  const observations =
    Array.isArray(draft.latest_observations) && draft.latest_observations.length
      ? draft.latest_observations
      : [{ name: "", value: "", abnormal_flag: "" }];

  return `
    <div class="stack">
      <div class="form-grid">
        <label class="field"><span>患者ID</span><input id="case-patient-id" value="${escapeAttr(draft.patient_id || "")}" placeholder="新建时可留空" /></label>
        <label class="field"><span>就诊ID</span><input id="case-encounter-id" value="${escapeAttr(draft.encounter_id || "")}" placeholder="可留空" /></label>
        <label class="field"><span>床位号</span><input id="case-bed-no" value="${escapeAttr(draft.bed_no || "")}" placeholder="例如 12" /></label>
        <label class="field"><span>房间号</span><input id="case-room-no" value="${escapeAttr(draft.room_no || "")}" placeholder="例如 612" /></label>
        <label class="field"><span>姓名</span><input id="case-full-name" value="${escapeAttr(draft.full_name || "")}" /></label>
        <label class="field"><span>病历号 MRN</span><input id="case-mrn" value="${escapeAttr(draft.mrn || "")}" /></label>
        <label class="field"><span>住院号</span><input id="case-inpatient-no" value="${escapeAttr(draft.inpatient_no || "")}" /></label>
        <label class="field"><span>性别</span><input id="case-gender" value="${escapeAttr(draft.gender || "")}" /></label>
        <label class="field"><span>年龄</span><input id="case-age" type="number" min="0" value="${escapeAttr(draft.age === "" ? "" : String(draft.age || ""))}" /></label>
        <label class="field"><span>血型</span><input id="case-blood-type" value="${escapeAttr(draft.blood_type || "")}" /></label>
        <label class="field"><span>当前状态</span>
          <select id="case-current-status">
            ${["admitted", "transferred", "discharged"].map((item) => `<option value="${item}" ${draft.current_status === item ? "selected" : ""}>${item}</option>`).join("")}
          </select>
        </label>
        <label class="field full"><span>过敏信息</span><textarea id="case-allergy-info" class="compact" placeholder="例如：青霉素过敏">${escapeHtml(draft.allergy_info || "")}</textarea></label>
      </div>

      <div class="section-block">
        <div class="section-title">
          <h4>诊断、风险与待办</h4>
          <div class="helper-text">一行一项，保存时直接写入病例任务和诊断表。</div>
        </div>
        <div class="form-grid">
          <label class="field"><span>诊断列表</span><textarea id="case-diagnoses" class="compact">${escapeHtml(draft.diagnoses.join("\n"))}</textarea></label>
          <label class="field"><span>风险标签</span><textarea id="case-risk-tags" class="compact">${escapeHtml(draft.risk_tags.join("\n"))}</textarea></label>
          <label class="field full"><span>待办任务</span><textarea id="case-pending-tasks" class="compact">${escapeHtml(draft.pending_tasks.join("\n"))}</textarea></label>
        </div>
      </div>

      <div class="section-block">
        <div class="section-title">
          <h4>最新观察值</h4>
          <div class="inline-actions">
            <div class="helper-text">名称 / 数值 / 异常标记</div>
            <button class="secondary-btn" data-action="add-observation">
              <span class="material-symbols-outlined">add</span>
              <span>新增观察</span>
            </button>
          </div>
        </div>
        <div class="obs-grid">
          ${observations.map((item, index) => renderObservationRow(item, index)).join("")}
        </div>
      </div>

      <div class="section-block">
        <div class="section-title">
          <h4>关联业务输出</h4>
          <div class="helper-text">展示与当前病例关联的软件端文书、推荐和交班结果。</div>
        </div>
        <div class="activity-list">
          ${renderActivityCard("文书草稿", state.caseActivity?.documents || [], (item) => item.document_type || "文书")}
          ${renderActivityCard("推荐结果", state.caseActivity?.recommendations || [], (item) => item.summary || "推荐结果")}
          ${renderActivityCard("交班记录", state.caseActivity?.handovers || [], (item) => item.summary || "交班记录")}
        </div>
      </div>
    </div>
  `;
}

function renderObservationRow(item, index) {
  return `
    <div class="obs-row" data-observation-row="${index}">
      <input data-observation-name value="${escapeAttr(item.name || "")}" placeholder="例如 血压" />
      <input data-observation-value value="${escapeAttr(item.value || "")}" placeholder="例如 88/56 mmHg" />
      <select data-observation-flag>
        ${["", "normal", "high", "low", "critical"].map((flag) => `<option value="${flag}" ${String(item.abnormal_flag || "") === flag ? "selected" : ""}>${flag || "无标记"}</option>`).join("")}
      </select>
      <button class="tiny-btn" data-action="remove-observation" data-index="${index}">
        <span class="material-symbols-outlined">delete</span>
      </button>
    </div>
  `;
}

function renderAccountsView() {
  return `
    <section class="accounts-layout">
      <aside class="sidebar-surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Software Accounts</div>
            <h3>软件账号</h3>
            <p>这里管理的是软件登录账号与协同账号的同步视图。</p>
          </div>
          <button class="secondary-btn" data-action="new-account">
            <span class="material-symbols-outlined">person_add</span>
            <span>新建账号</span>
          </button>
        </div>
        <div class="sidebar-scroll">
          ${(filteredAccounts().map(renderAccountRow).join("")) || `<div class="empty-copy">没有匹配到账号。</div>`}
        </div>
      </aside>

      <section class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Account Sync</div>
            <h3>${escapeHtml(state.accountDraft?.username || "新建账号")}</h3>
            <p>保存时会同时写入登录服务与协同服务，确保软件账号、联系人与后台配置同步。</p>
          </div>
          <div class="inline-actions">
            <button class="ghost-btn" data-action="new-account">
              <span class="material-symbols-outlined">restart_alt</span>
              <span>清空表单</span>
            </button>
            <button class="primary-btn" data-action="save-account">
              <span class="material-symbols-outlined">cloud_sync</span>
              <span>同步账号</span>
            </button>
          </div>
        </div>
        ${renderAccountForm()}
      </section>
    </section>
  `;
}

function renderAccountForm() {
  const draft = state.accountDraft;
  if (!draft) {
    return `<div class="empty-copy">请选择一个账号，或点击“新建账号”。</div>`;
  }
  return `
    <div class="stack">
      <div class="form-grid">
        <label class="field"><span>内部 ID</span><input id="account-id" value="${escapeAttr(draft.id || "")}" placeholder="首次创建可留空" /></label>
        <label class="field"><span>用户名</span><input id="account-username" value="${escapeAttr(draft.username || "")}" placeholder="将用于软件登录" /></label>
        <label class="field"><span>姓名</span><input id="account-full-name" value="${escapeAttr(draft.full_name || "")}" /></label>
        <label class="field"><span>角色</span>
          <select id="account-role-code">
            ${ROLE_OPTIONS.map((role) => `<option value="${role}" ${draft.role_code === role ? "selected" : ""}>${role}</option>`).join("")}
          </select>
        </label>
        <label class="field"><span>手机号</span><input id="account-phone" value="${escapeAttr(draft.phone || "")}" /></label>
        <label class="field"><span>邮箱</span><input id="account-email" value="${escapeAttr(draft.email || "")}" /></label>
        <label class="field"><span>所属病区 / 科室</span><input id="account-department" value="${escapeAttr(draft.department || "")}" /></label>
        <label class="field"><span>岗位职称</span><input id="account-title" value="${escapeAttr(draft.title || "")}" /></label>
        <label class="field"><span>账号状态</span>
          <select id="account-status">
            ${["active", "inactive", "locked"].map((item) => `<option value="${item}" ${draft.status === item ? "selected" : ""}>${item}</option>`).join("")}
          </select>
        </label>
        <label class="field"><span>重置密码</span><input id="account-password" type="text" value="" placeholder="${draft.username ? "留空则不修改密码" : "首次创建建议填写"}" /></label>
      </div>
      <div class="hint-box">
        这里改的是软件账号真实配置。账号保存后，软件登录、后台联系人列表和协同搜索会读到同一份同步结果。
      </div>
    </div>
  `;
}

function renderMonitorView() {
  return `
    <section class="monitor-grid">
      <article class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Connectivity</div>
            <h3>系统联通状态</h3>
            <p>确认后台、API 网关、设备链路与 AI 运行时是否处于可操作状态。</p>
          </div>
        </div>
        <div class="kpi-strip">
          ${renderSimpleMetric("网关", state.gatewayHealth?.status === "ok" ? "在线" : "离线", state.gatewayHealth ? "ok" : "err")}
          ${renderSimpleMetric("AI 引擎", state.runtime?.active_engine || "-", state.runtime ? "ok" : "warn")}
          ${renderSimpleMetric("设备会话", String(state.sessions.length || 0), state.sessions.length ? "ok" : "warn")}
          ${renderSimpleMetric("设备绑定", state.binding?.owner_username || "未绑定", state.binding ? "ok" : "warn")}
        </div>
      </article>

      <article class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Sync Log</div>
            <h3>最近操作</h3>
            <p>记录后台保存动作，便于确认刚刚的数据写入是否生效。</p>
          </div>
        </div>
        <div class="stack">
          ${state.monitorLogs.slice(0, 12).map(renderMonitorLog).join("") || `<div class="empty-copy">还没有后台操作日志。</div>`}
        </div>
      </article>

      <article class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Device Sessions</div>
            <h3>在线设备会话</h3>
          </div>
        </div>
        <div class="surface-scroll">
          <table class="table">
            <thead>
              <tr><th>会话 ID</th><th>客户端</th><th>连接时间</th><th>最近活跃</th></tr>
            </thead>
            <tbody>
              ${(state.sessions || []).map((item) => `
                <tr>
                  <td class="mono">${escapeHtml(shortId(item.connection_id || item.id || ""))}</td>
                  <td>${escapeHtml(item.client || item.peer || item.remote_addr || "-")}</td>
                  <td>${escapeHtml(fmtTime(item.connected_at || item.created_at))}</td>
                  <td>${escapeHtml(fmtTime(item.last_seen_at || item.updated_at))}</td>
                </tr>
              `).join("") || `<tr><td colspan="4" class="muted">暂无在线设备</td></tr>`}
            </tbody>
          </table>
        </div>
      </article>

      <article class="surface">
        <div class="surface-head">
          <div>
            <div class="eyebrow">Ward Stream</div>
            <h3>实时床位流</h3>
          </div>
        </div>
        <div class="bed-strip">
          ${(state.liveBeds || []).slice(0, 16).map(renderBedTile).join("") || `<div class="empty-copy">等待病区流数据。</div>`}
        </div>
      </article>
    </section>
  `;
}

function renderKpiItem(item) {
  return `
    <div class="kpi-item">
      <div class="label">${escapeHtml(item.label || item.key || "-")}</div>
      <div class="value">${escapeHtml(String(item.value ?? 0))}</div>
      <div class="helper-text">${escapeHtml(item.hint || "")}</div>
    </div>
  `;
}

function renderHeroStat(item) {
  return `
    <div class="hero-stat">
      <div class="label">${escapeHtml(item.label || item.key || "-")}</div>
      <div class="value">${escapeHtml(String(item.value ?? 0))}</div>
      <div class="helper-text">${escapeHtml(item.hint || "")}</div>
    </div>
  `;
}

function renderDistributionBlock(title, items) {
  const safeItems = Array.isArray(items) ? items : [];
  return `
    <div class="surface" style="padding:18px;">
      <div class="surface-head" style="margin-bottom:12px;">
        <div><h3 style="font-size:18px;">${escapeHtml(title)}</h3></div>
      </div>
      <div class="distribution-list">
        ${renderDistributionRows(safeItems)}
      </div>
    </div>
  `;
}

function renderDistributionRows(items) {
  if (!items.length) return `<div class="empty-copy">暂无分布数据。</div>`;
  const max = Math.max(...items.map((item) => Number(item.value || 0)), 1);
  return items
    .map((item) => `
      <div class="distribution-row">
        <strong>${escapeHtml(item.label || "-")}</strong>
        <div class="distribution-track">
          <span class="distribution-fill" style="width:${Math.max(8, Math.round((Number(item.value || 0) / max) * 100))}%"></span>
        </div>
        <span>${escapeHtml(String(item.value ?? 0))}</span>
      </div>
    `)
    .join("");
}

function renderBedTile(item) {
  const status = item.current_status || item.status || (item.current_patient_id ? "occupied" : "empty");
  const patientName = item.full_name || item.patient_name || "空床";
  const tags = Array.isArray(item.risk_tags) ? item.risk_tags.slice(0, 2) : [];
  const action = item.patient_id || item.current_patient_id ? "select-case" : "";
  const id = item.patient_id || item.current_patient_id || "";
  return `
    <button class="bed-tile" data-action="${action}" data-id="${escapeAttr(id)}">
      <strong>${escapeHtml(String(item.bed_no || "-"))} 床</strong>
      <div>${escapeHtml(patientName)}</div>
      <div class="segment-row" style="margin-top:8px;">
        <span class="soft-pill ${status === "admitted" || status === "occupied" ? "ok" : "warn"}">${escapeHtml(status)}</span>
        ${tags.map((tag) => `<span class="segment-tag">${escapeHtml(tag)}</span>`).join("")}
      </div>
    </button>
  `;
}

function renderHotspot(item) {
  return `
    <div class="hotspot-row">
      <div class="hotspot-head">
        <div>
          <strong>${escapeHtml(item.bed_no || "-")} 床 · ${escapeHtml(item.patient_name || "未命名患者")}</strong>
          <div class="helper-text">${escapeHtml(item.latest_observation || "暂无最新观察")}</div>
        </div>
        <span class="status-pill ${item.score >= 3 ? "warn" : "ok"}">压力分 ${escapeHtml(String(item.score ?? 0))}</span>
      </div>
      <div class="segment-row">
        ${(item.reasons || []).map((reason) => `<span class="segment-tag">${escapeHtml(reason)}</span>`).join("") || `<span class="segment-tag">暂无热点原因</span>`}
      </div>
    </div>
  `;
}

function renderCaseRow(item) {
  const activeId = state.caseDraft?.patient_id || state.caseBundle?.patient?.id || "";
  const isActive = item.patient_id === activeId;
  return `
    <button class="list-row ${isActive ? "active" : ""}" data-action="select-case" data-id="${escapeAttr(item.patient_id)}">
      <div class="list-row-head">
        <div>
          <strong>${escapeHtml(item.full_name || "未命名患者")}</strong>
          <div class="meta">${escapeHtml(item.department_name || "-")} · ${escapeHtml(item.bed_no || "-")} 床</div>
        </div>
        <span class="soft-pill ${item.risk_tags?.length ? "warn" : "ok"}">${item.risk_tags?.length || 0} 风险</span>
      </div>
      <div class="helper-text">${escapeHtml(item.latest_observation || item.mrn || "-")}</div>
      <div class="segment-row">
        ${(item.risk_tags || []).slice(0, 2).map((tag) => `<span class="segment-tag">${escapeHtml(tag)}</span>`).join("")}
        ${(item.pending_tasks || []).slice(0, 1).map((task) => `<span class="segment-tag">${escapeHtml(task)}</span>`).join("")}
      </div>
    </button>
  `;
}

function renderAccountRow(item) {
  const activeUsername = state.accountDraft?.username || "";
  const isActive = item.username === activeUsername || item.account === activeUsername;
  return `
    <button class="list-row ${isActive ? "active" : ""}" data-action="select-account" data-username="${escapeAttr(item.username || item.account || "")}">
      <div class="list-row-head">
        <div>
          <strong>${escapeHtml(item.full_name || item.username || item.account || "-")}</strong>
          <div class="meta">@${escapeHtml(item.username || item.account || "-")} · ${escapeHtml(item.role_code || "-")}</div>
        </div>
        <span class="soft-pill ${item.status === "active" ? "ok" : "warn"}">${escapeHtml(item.status || "active")}</span>
      </div>
      <div class="helper-text">${escapeHtml(item.department || "未分配病区")} · ${escapeHtml(item.title || "未设置职称")}</div>
    </button>
  `;
}

function renderActivityCard(title, rows, labelPicker) {
  const safeRows = Array.isArray(rows) ? rows.slice(0, 3) : [];
  return `
    <article class="activity-card">
      <div class="eyebrow">${escapeHtml(title)}</div>
      ${safeRows.map((item) => `
        <div style="margin-top:12px;">
          <div class="headline">${escapeHtml(labelPicker(item))}</div>
          <div class="activity-time">${escapeHtml(fmtTime(item.updated_at || item.created_at))}</div>
        </div>
      `).join("") || `<p>暂无关联数据。</p>`}
    </article>
  `;
}

function renderSimpleMetric(label, value, tone) {
  return `
    <div class="kpi-item">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${escapeHtml(value)}</div>
      <span class="soft-pill ${tone}">${escapeHtml(tone)}</span>
    </div>
  `;
}

function renderMonitorLog(item) {
  return `
    <div class="activity-row">
      <strong>${escapeHtml(item.title || "-")}</strong>
      <div>${escapeHtml(item.detail || "")}</div>
      <div class="activity-time">${escapeHtml(fmtTime(item.at))}</div>
    </div>
  `;
}

function renderStatusRibbon() {
  const pills = [];
  pills.push(`<span class="status-pill ${state.gatewayHealth?.status === "ok" ? "ok" : "err"}">API 网关 ${escapeHtml(state.gatewayHealth?.status || "offline")}</span>`);
  pills.push(`<span class="status-pill ${state.runtime ? "ok" : "warn"}">AI ${escapeHtml(state.runtime?.active_engine || "-")}</span>`);
  pills.push(`<span class="status-pill ${state.sessions.length ? "ok" : "warn"}">设备会话 ${escapeHtml(String(state.sessions.length || 0))}</span>`);
  pills.push(`<span class="status-pill ${state.caseDraft?.patient_id ? "ok" : "warn"}">当前病例 ${escapeHtml(state.caseDraft?.full_name || "未选择")}</span>`);
  pills.push(`<span class="status-pill ${state.accountDraft?.username ? "ok" : "warn"}">当前账号 ${escapeHtml(state.accountDraft?.username || "未选择")}</span>`);
  if (state.lastSyncAt) {
    pills.push(`<span class="status-pill ok">最近同步 ${escapeHtml(fmtTime(state.lastSyncAt))}</span>`);
  }
  els["status-ribbon"].innerHTML = pills.join("");
}

function filteredCases() {
  return state.cases.filter((item) => {
    if (!state.search) return true;
    const joined = [
      item.full_name,
      item.mrn,
      item.inpatient_no,
      item.bed_no,
      item.department_name,
      ...(item.risk_tags || []),
      ...(item.pending_tasks || []),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return joined.includes(state.search);
  });
}

function filteredAccounts() {
  return state.accounts.filter((item) => {
    if (!state.search) return true;
    const joined = [
      item.username,
      item.account,
      item.full_name,
      item.role_code,
      item.department,
      item.title,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return joined.includes(state.search);
  });
}

function currentDepartment() {
  return state.departments.find((item) => item.id === state.cfg.departmentId || item.code === state.cfg.departmentId) || null;
}

function syncConfigInputs() {
  els["cfg-api-base"].value = state.cfg.apiBase;
}

function syncFilterInputs() {
  els["case-status-filter"].value = state.cfg.caseStatus || "";
  els["account-status-filter"].value = state.cfg.accountStatus || "";
}

function syncDepartmentSelect() {
  els["department-select"].innerHTML = state.departments
    .map((item) => `<option value="${escapeAttr(item.id || item.code || "")}">${escapeHtml(item.name || item.code || "-")}</option>`)
    .join("");
  if (state.cfg.departmentId) {
    els["department-select"].value = state.cfg.departmentId;
  }
}

function updateDepartmentLabel() {
  const department = currentDepartment();
  els["current-department-name"].textContent = department?.name || "未选择病区";
  const meta = state.analytics
    ? `生成于 ${fmtTime(state.analytics.generated_at)}`
    : department?.location || "等待分析数据";
  els["current-department-meta"].textContent = meta;
}

function updateOwnerCard() {
  const draft = state.accountDraft;
  const name = draft?.full_name || state.caseDraft?.full_name || "未选择";
  const identity = draft?.username || draft?.id || "-";
  els["owner-avatar"].textContent = String(name || "?").slice(0, 1).toUpperCase();
  els["owner-name"].textContent = name;
  els["owner-id"].textContent = identity;
}

function updateGatewayChip() {
  const chip = els["gateway-status"];
  chip.className = "status-pill";
  if (state.gatewayHealth?.status === "ok") {
    chip.textContent = "网关在线";
    chip.classList.add("ok");
  } else {
    chip.textContent = "网关离线";
    chip.classList.add("err");
  }
}

function addMonitorLog(title, detail) {
  state.monitorLogs.unshift({
    at: new Date().toISOString(),
    title,
    detail,
  });
  state.monitorLogs = state.monitorLogs.slice(0, 30);
}

function closeConfigDrawer() {
  els["config-drawer"].classList.add("hidden");
}

function fieldValue(id) {
  return String(document.getElementById(id)?.value || "").trim();
}

function parseLines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function api(path, options = {}) {
  const base = String(state.cfg.apiBase || DEFAULT_CFG.apiBase).replace(/\/+$/, "");
  const headers = { ...(options.headers || {}) };
  const init = { method: options.method || "GET", headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(`${base}${path}`, init);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function connectWardSocket() {
  if (state.wardSocket) {
    state.wardSocket.close();
    state.wardSocket = null;
  }
  const departmentId = state.cfg.departmentId;
  if (!departmentId) return;
  try {
    const base = new URL(state.cfg.apiBase);
    const protocol = base.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${base.host}/ws/ward-beds/${encodeURIComponent(departmentId)}`;
    const socket = new WebSocket(url);
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "ward_beds_update" && Array.isArray(payload.data)) {
          state.liveBeds = payload.data;
          queueSoftRefresh();
        }
      } catch (_error) {
        // ignore malformed messages
      }
    };
    socket.onopen = () => addMonitorLog("病区流连接", `已连接 ${departmentId}`);
    socket.onerror = () => addMonitorLog("病区流异常", "实时连接出现异常");
    state.wardSocket = socket;
  } catch (_error) {
    // ignore ws failures on local static preview
  }
}

function queueSoftRefresh() {
  if (state.softRefreshTimer) {
    window.clearTimeout(state.softRefreshTimer);
  }
  state.softRefreshTimer = window.setTimeout(() => {
    refreshAnalytics().then(render).catch(handleError);
    refreshCases({ keepSelection: true }).then(render).catch(handleError);
  }, 600);
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_CFG };
    const parsed = JSON.parse(raw);
    return {
      apiBase: parsed.apiBase || DEFAULT_CFG.apiBase,
      departmentId: parsed.departmentId || DEFAULT_CFG.departmentId,
      caseStatus: parsed.caseStatus || DEFAULT_CFG.caseStatus,
      accountStatus: parsed.accountStatus || DEFAULT_CFG.accountStatus,
    };
  } catch (_error) {
    return { ...DEFAULT_CFG };
  }
}

function saveConfig(cfg) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

function handleError(error) {
  console.error(error);
  toast(errorText(error), "err");
}

function errorText(error) {
  if (!error) return "未知错误";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message || "发生异常";
  return String(error);
}

function fmtTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 12) return text || "-";
  return `${text.slice(0, 6)}...${text.slice(-4)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function toast(message, tone = "ok") {
  const node = document.createElement("div");
  node.className = `toast ${tone}`;
  node.textContent = message;
  els["toast-stack"].appendChild(node);
  window.setTimeout(() => node.remove(), 3200);
}
