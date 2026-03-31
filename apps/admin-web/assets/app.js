"use strict";

const STORAGE_KEY = "medical_ai_admin_config_v3";
const DEFAULT_CFG = {
  apiBase: "http://127.0.0.1:8000",
  departmentId: "dep-card-01",
  bedStart: 1,
  bedEnd: 40,
  defaultAccountId: "",
};

const state = {
  cfg: loadConfig(),
  activeView: "accounts",
  search: "",
  loading: false,
  accounts: [],
  account: null,
  beds: [],
  documents: [],
  handovers: [],
  recommendations: [],
  audits: [],
  workflows: [],
  binding: null,
  sessions: [],
  runtime: null,
  gatewayHealth: null,
  monitorLogs: [],
  lastE2E: null,
};

const els = {};

boot().catch((err) => {
  console.error(err);
  toast(`初始化失败: ${errorText(err)}`, "err");
});

async function boot() {
  cacheEls();
  bindStaticEvents();
  syncConfigInputs();
  setView(state.activeView);
  await loadAccounts();
  pickInitialAccount();
  await refreshData();
  render();
}

function cacheEls() {
  [
    "nav-list",
    "view-root",
    "global-search",
    "account-select",
    "switch-account-btn",
    "gateway-status",
    "e2e-check-btn",
    "refresh-btn",
    "open-config-btn",
    "config-modal",
    "close-config-btn",
    "cfg-api-base",
    "cfg-department",
    "cfg-bed-start",
    "cfg-bed-end",
    "save-config-btn",
    "bind-device-btn",
    "owner-avatar",
    "owner-name",
    "owner-id",
    "toast-stack",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindStaticEvents() {
  els["nav-list"].addEventListener("click", (event) => {
    const btn = event.target.closest(".nav-item");
    if (!btn) return;
    setView(btn.dataset.view || "accounts");
    render();
  });

  els["global-search"].addEventListener("input", (event) => {
    state.search = String(event.target.value || "").trim().toLowerCase();
    render();
  });

  els["switch-account-btn"].addEventListener("click", () => {
    const selectedId = String(els["account-select"].value || "");
    const account = state.accounts.find((item) => item.id === selectedId);
    if (!account) {
      toast("请选择一个账号", "warn");
      return;
    }
    setAccount(account);
    refreshData().then(render).catch(handleFatalError);
  });

  els["refresh-btn"].addEventListener("click", () => {
    refreshData().then(render).catch(handleFatalError);
  });

  els["e2e-check-btn"].addEventListener("click", () => {
    runE2E().catch((err) => {
      addMonitorLog("联调失败", errorText(err), "err");
      toast(`联调失败: ${errorText(err)}`, "err");
      render();
    });
  });

  els["open-config-btn"].addEventListener("click", () => {
    syncConfigInputs();
    els["config-modal"].classList.remove("hidden");
  });
  els["close-config-btn"].addEventListener("click", () => els["config-modal"].classList.add("hidden"));

  els["save-config-btn"].addEventListener("click", async () => {
    const cfg = {
      apiBase: String(els["cfg-api-base"].value || "").trim() || DEFAULT_CFG.apiBase,
      departmentId: String(els["cfg-department"].value || "").trim() || DEFAULT_CFG.departmentId,
      bedStart: Number(els["cfg-bed-start"].value || DEFAULT_CFG.bedStart) || DEFAULT_CFG.bedStart,
      bedEnd: Number(els["cfg-bed-end"].value || DEFAULT_CFG.bedEnd) || DEFAULT_CFG.bedEnd,
      defaultAccountId: state.account?.id || "",
    };
    state.cfg = cfg;
    saveConfig(cfg);
    els["config-modal"].classList.add("hidden");
    toast("配置已保存", "ok");
    await refreshData();
    render();
  });

  els["bind-device-btn"].addEventListener("click", () => {
    bindDeviceToCurrentAccount().then(render).catch(handleFatalError);
  });

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action || "";
    const id = target.dataset.id || "";
    if (action === "select-account") {
      const account = state.accounts.find((item) => item.id === id);
      if (!account) return;
      setAccount(account);
      refreshData().then(render).catch(handleFatalError);
      return;
    }
    if (action === "copy-text") {
      const text = target.dataset.text || "";
      navigator.clipboard.writeText(text).then(
        () => toast("已复制", "ok"),
        () => toast("复制失败", "warn"),
      );
      return;
    }
    if (action === "submit-draft") {
      submitDocumentDraft(id).catch(handleFatalError);
      return;
    }
    if (action === "review-handover") {
      reviewHandover(id).catch(handleFatalError);
    }
  });
}

function setView(view) {
  state.activeView = view;
  const buttons = Array.from(els["nav-list"].querySelectorAll(".nav-item"));
  buttons.forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
  });
}

function setAccount(account) {
  state.account = account;
  state.cfg.defaultAccountId = account.id;
  saveConfig(state.cfg);
  updateOwnerCard();
  syncAccountSelector();
  toast(`已切换账号: ${account.account}`, "ok");
}

function pickInitialAccount() {
  if (!state.accounts.length) return;
  const preferred =
    state.accounts.find((item) => item.id === state.cfg.defaultAccountId) ||
    state.accounts.find((item) => item.account === "linmeili") ||
    state.accounts[0];
  if (preferred) {
    state.account = preferred;
  }
  updateOwnerCard();
  syncAccountSelector();
}

async function loadAccounts() {
  const data = await api(`/api/collab/accounts?query=${encodeURIComponent("")}`);
  state.accounts = Array.isArray(data) ? data : [];
  if (!state.accounts.length) {
    toast("未获取到账号列表，请检查 collaboration-service", "warn");
  }
  syncAccountSelector();
}

async function refreshData() {
  state.loading = true;
  render();
  await Promise.allSettled([
    fetchGatewayHealth(),
    fetchRuntime(),
    fetchDeviceBinding(),
    fetchDeviceSessions(),
    fetchBeds(),
    fetchAudit(),
    fetchWorkflows(),
    fetchDraftBuckets(),
  ]);
  state.loading = false;
  updateGatewayChip();
}

async function fetchGatewayHealth() {
  const data = await api("/health");
  state.gatewayHealth = data || null;
}

async function fetchRuntime() {
  const data = await api("/api/ai/runtime");
  state.runtime = data || null;
}

async function fetchDeviceBinding() {
  const data = await api("/api/device/binding");
  state.binding = data || null;
}

async function fetchDeviceSessions() {
  const data = await api("/api/device/sessions");
  state.sessions = Array.isArray(data?.sessions) ? data.sessions : [];
}

async function fetchBeds() {
  const data = await api(`/api/wards/${encodeURIComponent(state.cfg.departmentId)}/beds`);
  state.beds = Array.isArray(data) ? data : [];
}

async function fetchAudit() {
  if (!state.account) {
    state.audits = [];
    return;
  }
  const data = await api(
    `/api/audit/history?requested_by=${encodeURIComponent(state.account.id)}&limit=200`,
  );
  state.audits = Array.isArray(data) ? data : [];
}

async function fetchWorkflows() {
  if (!state.account) {
    state.workflows = [];
    return;
  }
  const data = await api(
    `/api/workflow/history?requested_by=${encodeURIComponent(state.account.id)}&limit=120`,
  );
  state.workflows = Array.isArray(data) ? data : [];
}

async function fetchDraftBuckets() {
  if (!state.account) {
    state.documents = [];
    state.handovers = [];
    state.recommendations = [];
    return;
  }
  const userId = encodeURIComponent(state.account.id);
  const [docs, hands, recs] = await Promise.all([
    api(`/api/document/inbox/${userId}?limit=120`),
    api(`/api/handover/inbox/${userId}?limit=120`),
    api(`/api/recommendation/inbox/${userId}?limit=120`),
  ]);
  state.documents = Array.isArray(docs) ? docs : [];
  state.handovers = Array.isArray(hands) ? hands : [];
  state.recommendations = Array.isArray(recs) ? recs : [];
}

function render() {
  if (state.loading) {
    els["view-root"].innerHTML = `
      <div class="loading-wrap">
        <div class="spinner"></div>
        <p>正在同步管理数据...</p>
      </div>
    `;
    return;
  }
  if (state.activeView === "accounts") {
    els["view-root"].innerHTML = renderAccountsView();
    return;
  }
  if (!state.account) {
    els["view-root"].innerHTML = `<div class="empty-state">请先在“账号中心”选择账号。</div>`;
    return;
  }
  if (state.activeView === "dashboard") {
    els["view-root"].innerHTML = renderDashboardView();
  } else if (state.activeView === "patients") {
    els["view-root"].innerHTML = renderPatientsView();
  } else if (state.activeView === "drafts") {
    els["view-root"].innerHTML = renderDraftsView();
  } else if (state.activeView === "audit") {
    els["view-root"].innerHTML = renderAuditView();
  } else if (state.activeView === "monitor") {
    els["view-root"].innerHTML = renderMonitorView();
    const btn = document.getElementById("monitor-run-btn");
    if (btn) {
      btn.onclick = () => runE2E().catch(handleFatalError);
    }
  }
}

function renderAccountsView() {
  const list = filterBySearch(state.accounts, (acc) => [acc.account, acc.full_name, acc.id, acc.department]);
  const cards = list
    .map((acc) => {
      const selected = state.account?.id === acc.id;
      return `
        <article class="account-card">
          <div class="account-head">
            <div>
              <div class="account-title">${escapeHtml(repairText(acc.full_name || acc.account || "未命名"))}</div>
              <div class="account-meta">@${escapeHtml(acc.account || "-")}</div>
            </div>
            ${selected ? `<span class="selected-mark">已选中</span>` : ""}
          </div>
          <div class="account-meta">
            <div>用户ID: <span class="mono">${escapeHtml(acc.id || "-")}</span></div>
            <div>角色: ${escapeHtml(repairText(acc.role_code || "-"))}</div>
            <div>科室: ${escapeHtml(repairText(acc.department || "-"))}</div>
          </div>
          <div class="actions">
            <button class="mini-btn primary" data-action="select-account" data-id="${escapeHtml(acc.id)}">进入账号</button>
          </div>
        </article>
      `;
    })
    .join("");
  return `
    <section class="stack">
      <div class="hero">
        <div>
          <h2>账号中心</h2>
          <p>管理员先选择账号，再查看该账号下患者、草稿、审计和设备绑定状态。</p>
        </div>
        <span class="chip">${list.length} 个账号</span>
      </div>
      ${cards ? `<div class="accounts-grid">${cards}</div>` : `<div class="empty-state">未匹配到账号</div>`}
    </section>
  `;
}

function renderDashboardView() {
  const bedCoverage = getBedCoverage();
  const boundOk = state.binding && state.account && state.binding.owner_user_id === state.account.id;
  const kpis = [
    { label: "在床患者", value: state.beds.filter((b) => b.current_patient_id).length, desc: `总床位 ${state.beds.length}` },
    { label: "文书草稿", value: state.documents.length, desc: "document_drafts" },
    { label: "交班草稿", value: state.handovers.length, desc: "handover_records" },
    { label: "推荐结果", value: state.recommendations.length, desc: "ai_recommendations" },
  ];

  const workflowRows = state.workflows.slice(0, 10).map((item) => {
    return `
      <tr>
        <td>${fmtTime(item.created_at)}</td>
        <td>${escapeHtml(repairText(item.workflow_type || "-"))}</td>
        <td>${patientLabel(item.patient_id)}</td>
        <td class="line-clamp">${escapeHtml(repairText(item.summary || "-"))}</td>
        <td>${percent(item.confidence)}</td>
      </tr>
    `;
  });

  return `
    <section class="stack">
      <div class="hero">
        <div>
          <h2>系统总览</h2>
          <p>账号 ${escapeHtml(state.account?.account || "-")} 的患者、工作流、草稿和设备联通状态。</p>
        </div>
        <span class="chip ${bedCoverage.ok ? "ok" : "warn"}">床位覆盖 ${bedCoverage.covered}/${bedCoverage.expected}</span>
      </div>
      <div class="kpi-grid">
        ${kpis
          .map(
            (kpi) => `
          <article class="kpi">
            <div class="label">${kpi.label}</div>
            <div class="value">${kpi.value}</div>
            <div class="desc">${kpi.desc}</div>
          </article>
        `,
          )
          .join("")}
      </div>
      <div class="split">
        <article class="card">
          <h3>病区床位</h3>
          ${renderBedsTable(state.beds.slice(0, 20))}
        </article>
        <article class="card">
          <h3>运行与绑定</h3>
          <div class="status-grid">
            <div class="status-block">
              <div class="status-row"><span>网关</span><span class="chip ${state.gatewayHealth ? "ok" : "err"}">${state.gatewayHealth ? "在线" : "离线"}</span></div>
              <div class="subtle">${escapeHtml(state.cfg.apiBase)}</div>
            </div>
            <div class="status-block">
              <div class="status-row"><span>单片机绑定</span><span class="chip ${boundOk ? "ok" : "warn"}">${boundOk ? "已绑定当前账号" : "未绑定当前账号"}</span></div>
              <div class="subtle">${escapeHtml(state.binding?.owner_username || "-")}</div>
            </div>
            <div class="status-block">
              <div class="status-row"><span>在线会话</span><span class="chip ${state.sessions.length > 0 ? "ok" : "warn"}">${state.sessions.length}</span></div>
              <div class="subtle">MCU WebSocket 连接数</div>
            </div>
          </div>
          <div class="subtle" style="margin-top:10px;">
            引擎: ${escapeHtml(state.runtime?.active_engine || "-")} / 配置: ${escapeHtml(state.runtime?.configured_engine || "-")}
          </div>
        </article>
      </div>
      <article class="card">
        <h3>工作流最近记录</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>时间</th><th>类型</th><th>患者</th><th>摘要</th><th>置信度</th></tr>
            </thead>
            <tbody>
              ${workflowRows.join("") || `<tr><td colspan="5" class="muted">暂无记录</td></tr>`}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  `;
}

function renderPatientsView() {
  return `
    <section class="stack">
      <div class="hero">
        <div><h2>患者床位</h2><p>按病区查看每个床位对应患者，支持全库映射检查。</p></div>
        <span class="chip">${state.beds.length} 床位</span>
      </div>
      <article class="card">
        ${renderBedsTable(filterBySearch(state.beds, (row) => [row.bed_no, row.patient_name, row.current_patient_id]))}
      </article>
    </section>
  `;
}

function renderDraftsView() {
  const docs = filterBySearch(state.documents, (row) => [row.id, row.patient_id, row.document_type, row.status]);
  const handovers = filterBySearch(state.handovers, (row) => [row.id, row.patient_id, row.shift_type, row.summary]);
  const recs = filterBySearch(state.recommendations, (row) => [row.id, row.patient_id, row.summary]);

  return `
    <section class="stack">
      <div class="hero">
        <div><h2>草稿与结果</h2><p>文书、交班、推荐均与账号 ${escapeHtml(state.account?.account || "-")} 关联。</p></div>
      </div>
      <article class="card">
        <h3>文书草稿</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>患者</th><th>类型</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
            <tbody>
              ${
                docs
                  .map(
                    (doc) => `
                <tr>
                  <td><span class="id-chip mono" title="${escapeHtml(doc.id)}">${escapeHtml(shortId(doc.id))}</span></td>
                  <td>${patientLabel(doc.patient_id)}</td>
                  <td>${escapeHtml(repairText(doc.document_type || "-"))}</td>
                  <td>${escapeHtml(repairText(doc.status || "-"))}</td>
                  <td>${fmtTime(doc.updated_at || doc.created_at)}</td>
                  <td>
                    <div class="actions">
                      <button class="mini-btn" data-action="copy-text" data-text="${escapeAttr(doc.draft_text || "")}">复制</button>
                      <button class="mini-btn primary" data-action="submit-draft" data-id="${escapeHtml(doc.id)}">提交</button>
                    </div>
                  </td>
                </tr>`,
                  )
                  .join("") || `<tr><td colspan="6" class="muted">暂无文书草稿</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </article>

      <article class="card">
        <h3>交班草稿</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>患者</th><th>班次</th><th>摘要</th><th>时间</th><th>操作</th></tr></thead>
            <tbody>
              ${
                handovers
                  .map(
                    (item) => `
                <tr>
                  <td><span class="id-chip mono" title="${escapeHtml(item.id)}">${escapeHtml(shortId(item.id))}</span></td>
                  <td>${patientLabel(item.patient_id)}</td>
                  <td>${escapeHtml(repairText(item.shift_type || "-"))}</td>
                  <td class="line-clamp">${escapeHtml(repairText(item.summary || "-"))}</td>
                  <td>${fmtTime(item.created_at)}</td>
                  <td>
                    <div class="actions">
                      <button class="mini-btn" data-action="copy-text" data-text="${escapeAttr(item.summary || "")}">复制</button>
                      <button class="mini-btn primary" data-action="review-handover" data-id="${escapeHtml(item.id)}">复核</button>
                    </div>
                  </td>
                </tr>`,
                  )
                  .join("") || `<tr><td colspan="6" class="muted">暂无交班草稿</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </article>

      <article class="card">
        <h3>推荐结果</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>患者</th><th>摘要</th><th>置信度</th><th>需复核</th><th>时间</th></tr></thead>
            <tbody>
              ${
                recs
                  .map(
                    (rec) => `
                <tr>
                  <td><span class="id-chip mono" title="${escapeHtml(rec.id)}">${escapeHtml(shortId(rec.id))}</span></td>
                  <td>${patientLabel(rec.patient_id)}</td>
                  <td class="line-clamp">${escapeHtml(repairText(rec.summary || "-"))}</td>
                  <td>${percent(rec.confidence)}</td>
                  <td>${yesNo(rec.review_required)}</td>
                  <td>${fmtTime(rec.created_at)}</td>
                </tr>`,
                  )
                  .join("") || `<tr><td colspan="6" class="muted">暂无推荐结果</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </article>
    </section>
  `;
}

function renderAuditView() {
  const logs = filterBySearch(state.audits, (item) => [item.action, item.resource_type, item.resource_id, item.user_id]);
  return `
    <section class="stack">
      <div class="hero">
        <div><h2>审计日志</h2><p>按当前账号过滤，可追踪工作流触发与草稿提交行为。</p></div>
        <span class="chip">${logs.length} 条</span>
      </div>
      <article class="card">
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>动作</th><th>资源</th><th>资源ID</th><th>用户</th><th>详情</th></tr></thead>
            <tbody>
              ${
                logs
                  .map(
                    (item) => `
                <tr>
                  <td>${fmtTime(item.created_at)}</td>
                  <td>${escapeHtml(repairText(item.action || "-"))}</td>
                  <td>${escapeHtml(repairText(item.resource_type || "-"))}</td>
                  <td><span class="id-chip mono" title="${escapeHtml(item.resource_id || "")}">${escapeHtml(shortId(item.resource_id || ""))}</span></td>
                  <td>${escapeHtml(repairText(item.user_id || "-"))}</td>
                  <td class="line-clamp">${escapeHtml(repairText(JSON.stringify(item.detail || {})))}</td>
                </tr>`,
                  )
                  .join("") || `<tr><td colspan="6" class="muted">暂无审计日志</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </article>
    </section>
  `;
}

function renderMonitorView() {
  const now = Date.now();
  const recentWorkflow = state.workflows.some((item) => now - Date.parse(item.created_at || 0) < 20 * 60 * 1000);
  const appSignal = recentWorkflow || state.audits.some((item) => /app|mobile/i.test(String(item.action || "")));
  const mcuOnline = state.sessions.length > 0;
  const boundCurrent = state.binding && state.account && state.binding.owner_user_id === state.account.id;
  const logs = state.monitorLogs
    .slice(0, 20)
    .map(
      (log) => `
    <div class="log-item">
      <div class="log-time">${fmtTime(log.at)}</div>
      <div class="log-title">${escapeHtml(log.title)}</div>
      <div class="log-desc">${escapeHtml(log.detail || "")}</div>
    </div>`,
    )
    .join("");

  return `
    <section class="stack">
      <div class="hero">
        <div>
          <h2>三端联通监控</h2>
          <p>验证 管理系统(Web) ↔ API 网关 ↔ App/单片机 的实时链路状态。</p>
        </div>
        <button class="btn btn-primary" id="monitor-run-btn">执行联调测试</button>
      </div>

      <div class="status-grid">
        <article class="status-block">
          <div class="status-row"><strong>管理系统 ↔ 网关</strong><span class="chip ${state.gatewayHealth ? "ok" : "err"}">${state.gatewayHealth ? "在线" : "离线"}</span></div>
          <div class="subtle">${escapeHtml(state.cfg.apiBase)}</div>
        </article>
        <article class="status-block">
          <div class="status-row"><strong>App ↔ 工作流</strong><span class="chip ${appSignal ? "ok" : "warn"}">${appSignal ? "有信号" : "最近无信号"}</span></div>
          <div class="subtle">依据最近工作流/审计记录判定</div>
        </article>
        <article class="status-block">
          <div class="status-row"><strong>单片机 ↔ 网关</strong><span class="chip ${mcuOnline ? "ok" : "warn"}">${mcuOnline ? "在线会话" : "离线"}</span></div>
          <div class="subtle">绑定:${boundCurrent ? "当前账号" : "非当前账号"} / 会话:${state.sessions.length}</div>
        </article>
      </div>

      <div class="split">
        <article class="card">
          <h3>联调日志</h3>
          <div class="log-box">${logs || `<div class="muted">暂无联调日志</div>`}</div>
          ${
            state.lastE2E
              ? `<div class="subtle" style="margin-top:8px;">最近联调: ${fmtTime(state.lastE2E.at)} / session: ${escapeHtml(shortId(state.lastE2E.session_id || ""))}</div>`
              : ""
          }
        </article>
        <article class="card">
          <h3>设备在线会话</h3>
          <div class="table-wrap">
            <table>
              <thead><tr><th>会话ID</th><th>客户端</th><th>连接时间</th><th>最近活跃</th></tr></thead>
              <tbody>
                ${
                  state.sessions
                    .map(
                      (s) => `
                  <tr>
                    <td><span class="id-chip mono" title="${escapeHtml(s.connection_id || s.id || "")}">${escapeHtml(shortId(s.connection_id || s.id || ""))}</span></td>
                    <td>${escapeHtml(repairText(s.client || s.peer || s.remote_addr || "-"))}</td>
                    <td>${fmtTime(s.connected_at || s.created_at)}</td>
                    <td>${fmtTime(s.last_seen_at || s.updated_at)}</td>
                  </tr>`,
                    )
                    .join("") || `<tr><td colspan="4" class="muted">暂无在线会话</td></tr>`
                }
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </section>
  `;
}

async function runE2E() {
  if (!state.account) {
    toast("请先选择账号", "warn");
    return;
  }
  addMonitorLog("开始联调", `账号 ${state.account.account}`);
  await bindDeviceToCurrentAccount();
  const bed = state.beds.find((item) => item.current_patient_id) || state.beds[0];
  const text = bed ? `帮我看一下${bed.bed_no}床的情况` : "帮我看一下12床的情况";
  const queryResp = await api("/api/device/query", {
    method: "POST",
    body: {
      device_id: state.binding?.device_id || "dev-115200",
      session_id: "",
      text,
      mode: "patient_query",
      requested_by: state.account.id,
      department_id: state.cfg.departmentId,
    },
  });
  const sessionId = queryResp?.session_id;
  if (!sessionId) throw new Error("未拿到 session_id");
  addMonitorLog("会话已创建", `session=${sessionId}`);

  let finalResult = null;
  for (let i = 0; i < 36; i += 1) {
    await sleep(1200);
    const result = await api(`/api/device/result/${encodeURIComponent(sessionId)}`);
    if (i % 4 === 0) {
      addMonitorLog("轮询结果", `status=${result.status || "unknown"}`);
    }
    if (result.status === "completed" || result.status === "failed") {
      finalResult = result;
      break;
    }
  }

  if (!finalResult) {
    addMonitorLog("联调超时", "设备会话未在预期时间完成", "warn");
    toast("联调超时，请检查设备是否在线", "warn");
    return;
  }

  state.lastE2E = { at: new Date().toISOString(), session_id: sessionId };
  if (finalResult.status === "completed") {
    addMonitorLog("联调成功", repairText(finalResult.summary || "(无摘要)"), "ok");
    toast("联调成功：管理端已打通到设备工作流", "ok");
  } else {
    addMonitorLog("联调失败", repairText(finalResult.error || finalResult.summary || "unknown"), "err");
    toast(`联调失败: ${errorText(finalResult.error || "unknown")}`, "err");
  }
  await refreshData();
  render();
}

async function bindDeviceToCurrentAccount() {
  if (!state.account) {
    toast("请先选择账号", "warn");
    return;
  }
  const data = await api("/api/device/bind", {
    method: "POST",
    body: {
      user_id: state.account.id,
      username: state.account.account,
    },
  });
  state.binding = data || null;
  addMonitorLog("设备绑定", `owner=${state.binding?.owner_username || "-"}`);
  toast("设备已绑定到当前账号", "ok");
}

async function submitDocumentDraft(draftId) {
  if (!state.account) return;
  await api(`/api/document/${encodeURIComponent(draftId)}/submit`, {
    method: "POST",
    body: { submitted_by: state.account.id },
  });
  toast("文书已提交", "ok");
  await fetchDraftBuckets();
  await fetchAudit();
  render();
}

async function reviewHandover(recordId) {
  if (!state.account) return;
  await api(`/api/handover/${encodeURIComponent(recordId)}/review`, {
    method: "POST",
    body: { reviewed_by: state.account.id, review_note: "admin_review" },
  });
  toast("交班已复核", "ok");
  await fetchDraftBuckets();
  await fetchAudit();
  render();
}

function renderBedsTable(rows) {
  const list = filterBySearch(rows, (row) => [row.bed_no, row.patient_name, row.current_patient_id, row.pending_tasks?.join(" ")]);
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>床位</th><th>患者</th><th>患者ID</th><th>风险</th><th>待办</th><th>状态</th></tr>
        </thead>
        <tbody>
          ${
            list
              .map(
                (row) => `
            <tr>
              <td>${escapeHtml(row.bed_no || "-")}</td>
              <td>${escapeHtml(repairText(row.patient_name || "-"))}</td>
              <td><span class="id-chip mono" title="${escapeHtml(row.current_patient_id || "")}">${escapeHtml(shortId(row.current_patient_id || ""))}</span></td>
              <td>${renderTags(row.risk_tags)}</td>
              <td>${renderTags(row.pending_tasks)}</td>
              <td>${escapeHtml(repairText(row.status || "-"))}</td>
            </tr>`,
              )
              .join("") || `<tr><td colspan="6" class="muted">暂无床位数据</td></tr>`
          }
        </tbody>
      </table>
    </div>
  `;
}

function renderTags(items) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!list.length) return "<span class='muted'>-</span>";
  return `<div class="tag-list">${list.map((x) => `<span class="tag">${escapeHtml(repairText(String(x)))}</span>`).join("")}</div>`;
}

function getBedCoverage() {
  const start = Number(state.cfg.bedStart || 1);
  const end = Number(state.cfg.bedEnd || 40);
  const expected = Math.max(0, end - start + 1);
  const set = new Set(state.beds.map((item) => Number(item.bed_no)));
  let covered = 0;
  for (let i = start; i <= end; i += 1) {
    if (set.has(i)) covered += 1;
  }
  return { expected, covered, ok: covered === expected };
}

function patientLabel(patientId) {
  const bed = state.beds.find((item) => item.current_patient_id === patientId);
  if (bed) {
    return `${escapeHtml(repairText(bed.patient_name || "未命名"))} (${escapeHtml(bed.bed_no || "-")}床)`;
  }
  return patientId ? `<span class="id-chip mono" title="${escapeHtml(patientId)}">${escapeHtml(shortId(patientId))}</span>` : "-";
}

function addMonitorLog(title, detail, level = "ok") {
  state.monitorLogs.unshift({ at: new Date().toISOString(), title, detail, level });
  state.monitorLogs = state.monitorLogs.slice(0, 60);
}

function updateOwnerCard() {
  const account = state.account;
  if (!account) {
    els["owner-avatar"].textContent = "?";
    els["owner-name"].textContent = "未选择账号";
    els["owner-id"].textContent = "-";
    return;
  }
  els["owner-avatar"].textContent = String(account.account || "?").slice(0, 1).toUpperCase();
  els["owner-name"].textContent = `${account.full_name || account.account}`;
  els["owner-id"].textContent = account.id || "-";
}

function syncAccountSelector() {
  const options = state.accounts
    .map(
      (acc) => `<option value="${escapeHtml(acc.id)}">${escapeHtml(repairText(acc.full_name || acc.account))} (@${escapeHtml(acc.account || "")})</option>`,
    )
    .join("");
  els["account-select"].innerHTML = options;
  if (state.account) {
    els["account-select"].value = state.account.id;
  }
}

function syncConfigInputs() {
  els["cfg-api-base"].value = state.cfg.apiBase;
  els["cfg-department"].value = state.cfg.departmentId;
  els["cfg-bed-start"].value = String(state.cfg.bedStart);
  els["cfg-bed-end"].value = String(state.cfg.bedEnd);
}

function updateGatewayChip() {
  const chip = els["gateway-status"];
  chip.classList.remove("ok", "warn", "err");
  if (state.gatewayHealth?.status === "ok") {
    chip.textContent = "网关在线";
    chip.classList.add("ok");
  } else {
    chip.textContent = "网关离线";
    chip.classList.add("err");
  }
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  const init = { method, headers };
  if (options.body !== undefined) {
    if (options.body instanceof FormData || typeof options.body === "string" || options.body instanceof Blob) {
      init.body = options.body;
    } else {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
  }
  const base = String(state.cfg.apiBase || DEFAULT_CFG.apiBase).replace(/\/+$/, "");
  const res = await fetch(`${base}${path}`, init);
  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await res.json().catch(() => ({})) : await res.text();
  if (!res.ok) {
    const detail = isJson ? payload?.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return payload;
}

function filterBySearch(list, pickFields) {
  if (!state.search) return list;
  return (list || []).filter((item) => {
    const text = pickFields(item).filter(Boolean).join(" ").toLowerCase();
    return text.includes(state.search);
  });
}

function shortId(id) {
  const text = String(id || "");
  if (!text) return "-";
  if (text.length <= 12) return text;
  return `${text.slice(0, 6)}...${text.slice(-4)}`;
}

function fmtTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function percent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${Math.round(n * 100)}%`;
}

function yesNo(flag) {
  return flag ? "是" : "否";
}

function repairText(text) {
  const raw = String(text ?? "");
  if (!raw) return "";
  if (/[\uFFFD]/.test(raw) || /[ÃÂåæçèéêìíîïðñòóôõöøùúûüý]/.test(raw)) {
    try {
      const fixed = decodeURIComponent(escape(raw));
      if (fixed) return fixed;
    } catch (_err) {
      return raw;
    }
  }
  return raw;
}

function escapeHtml(input) {
  return String(input ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(input) {
  return escapeHtml(String(input ?? "")).replace(/`/g, "&#96;");
}

function toast(message, level = "ok") {
  const node = document.createElement("div");
  node.className = `toast ${level}`;
  node.textContent = message;
  els["toast-stack"].appendChild(node);
  setTimeout(() => node.remove(), 3200);
}

function handleFatalError(err) {
  console.error(err);
  toast(errorText(err), "err");
}

function errorText(err) {
  if (!err) return "未知错误";
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message || "发生异常";
  return String(err);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_CFG };
    const parsed = JSON.parse(raw);
    return {
      apiBase: parsed.apiBase || DEFAULT_CFG.apiBase,
      departmentId: parsed.departmentId || DEFAULT_CFG.departmentId,
      bedStart: Number(parsed.bedStart || DEFAULT_CFG.bedStart),
      bedEnd: Number(parsed.bedEnd || DEFAULT_CFG.bedEnd),
      defaultAccountId: parsed.defaultAccountId || "",
    };
  } catch (_err) {
    return { ...DEFAULT_CFG };
  }
}

function saveConfig(cfg) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}
