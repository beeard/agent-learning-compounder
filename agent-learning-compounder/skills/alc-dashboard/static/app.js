const DATA_ELEMENT = document.getElementById("dashboard-data");
const DATA = DATA_ELEMENT ? JSON.parse(DATA_ELEMENT.textContent || "{}") : {};

const HTML_ESCAPE_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
  "`": "&#96;",
};

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"'`]/g, (c) => HTML_ESCAPE_MAP[c]);
}

// safeText returns HTML-escaped text suitable for direct inclusion in template
// literals that get assigned to innerHTML. Event names, actor names, recommendation
// text, etc. originate from hooks/transcripts/MCP callers — treat all of it as
// untrusted. Callers that need raw values should access the data dict directly
// and never inject into HTML.
function safeText(value) {
  return escapeHtml(value);
}

const fallbackMessage = (title) => `<article class="section-card score-mid"><strong>${safeText(title)}</strong><p>No records yet.</p></article>`;

function riskClass(score) {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return "score-mid";
  }
  if (score >= 0.67) return "score-high";
  if (score >= 0.34) return "score-mid";
  return "score-low";
}

function scoreBadge(score) {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return "<span class=\"badge warn\">no score</span>";
  }
  if (score >= 0.67) return "<span class=\"badge ok\">high</span>";
  if (score >= 0.34) return "<span class=\"badge warn\">medium</span>";
  return "<span class=\"badge critical\">low</span>";
}

function toRows(items, title, keyText = "item") {
  if (!Array.isArray(items) || items.length === 0) {
    return fallbackMessage(title);
  }

  return items.map((row) => {
    const score = Number(row.score ?? row.confidence ?? row.likelihood ?? 0);
    const text = safeText(row.title || row.summary || row.name || `${keyText} event`);
    const kind = safeText(row.kind || row.type || "");
    const id = safeText(row.recommendation_id || row.patch_id || row.event_id || "");
    return `<article class="section-card ${riskClass(score)}"><strong>${text}</strong> ${scoreBadge(score)}<div class="preset">` +
      `Kind: ${kind}\nID: ${id}<\/div><div>${safeText(row.reason || row.description || "")}</div></article>`;
  }).join("\n");
}

function renderSuggestions(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return fallbackMessage("Suggestions");
  }

  return items.map((item) => {
    const title = safeText(item.title || item.kind || "workflow suggestion");
    const copyPayload = JSON.stringify(item, null, 2);
    const command = safeText(item.copy_to_clipboard || item.copy_command || `printf '%s' ${JSON.stringify(copyPayload)}`);
    const detail = safeText(item.detail || item.summary || "Workflow chain suggestion");
    return `<article class="section-card score-high"><strong>${title}</strong><p>${detail}</p>` +
      `<div class="command" id="copy-${safeText(item.recommendation_id || item.id || "")}">${command}<\/div>` +
      `<button class="copy-btn" data-copy-target="copy-${safeText(item.recommendation_id || item.id || "")}">Copy command</button>` +
      `<span class="copy-success" aria-live="polite" hidden>Copied</span>` +
      `<\/article>`;
  }).join("\n");
}

function renderPatches(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return fallbackMessage("Pending patches");
  }

  return items.map((item) => {
    const patch = safeText(item.patch_id || item.id || "") || "unknown";
    const command = `bin/alc_apply --patch ${patch} --write`;
    const deferred = `bin/alc_apply --mark-deferred ${patch}`;
    const rejected = `bin/alc_apply --mark-rejected ${patch}`;
    return `<article class="section-card score-mid"><strong>Patch ${patch}</strong>` +
      `<p>${safeText(item.title || item.description || "")}</p>` +
      `<p>Mark as:</p>` +
      `<ul><li><div class="command">${deferred}</div></li><li><div class="command">${rejected}</div></li></ul>` +
      `<p>Run in terminal:</p><div class="command">${command}</div>` +
      `<\/article>`;
  }).join("\n");
}

function renderApplyLog(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return fallbackMessage("Apply log");
  }

  return items.map((row) => {
    const event = safeText(row.event || row.event_id || "event");
    const ts = safeText(row.ts || "");
    const actor = `${safeText(row.actor_kind)}:${safeText(row.actor_name)}`;
    return `<article class="section-card score-mid"><strong>${event}</strong><p>${ts}</p><p>${actor}</p><\/article>`;
  }).join("\n");
}

function scopeBadge(scope) {
  if (scope === "user") return `<span class="badge ok">user</span>`;
  if (scope === "project") return `<span class="badge warn">project</span>`;
  return "";
}

function renderGatesList(payload) {
  const rows = Array.isArray((payload || {}).gates_rows) ? payload.gates_rows : [];
  if (rows.length === 0) {
    const fallback = safeText((payload || {}).gates_markdown || "No gates snapshot available.");
    return `<div class="preset">${fallback}</div>`;
  }

  const summary = (payload && payload.gates_summary) || { total: rows.length, user: 0, project: 0 };
  const header = `<p class="gates-summary">` +
    `<strong>${safeText(summary.total)}</strong> gates · ` +
    `<strong>${safeText(summary.user)}</strong> user · ` +
    `<strong>${safeText(summary.project)}</strong> project` +
    `</p>`;

  const items = rows.map((row) => {
    const scope = scopeBadge(row && row._source_scope);
    const domain = safeText((row && row.domain) || "");
    const category = safeText((row && row.category) || "");
    const gateId = safeText((row && row.gate_id) || "");
    const gate = safeText((row && row.gate) || "");
    return `<article class="section-card score-high">` +
      `<strong>${domain}</strong> ${scope} ` +
      `<span class="badge">${category}</span>` +
      `<p>${gate}</p>` +
      `<div class="preset">gate_id: ${gateId}</div>` +
      `</article>`;
  }).join("\n");

  return header + items;
}

function renderGatesAndInsights(payload) {
  const insights = safeText((payload || {}).insights_markdown || "No insight snapshot available.");
  // JSON.stringify escapes " and \\ but NOT < or > — actor names from MCP callers
  // can still inject <script> into innerHTML without an additional escape.
  const summary = safeText(JSON.stringify((payload && payload.actor_summary) || {}));
  return `<article class="section-card score-high"><strong>Gates</strong>${renderGatesList(payload)}</article>` +
    `<article class="section-card score-mid"><strong>Insights</strong><div class="preset">${insights}</div></article>` +
    `<article class="section-card score-low"><strong>Actor summary</strong><div class="preset">${summary}</div></article>`;
}

function renderById(id, html) {
  const node = document.getElementById(id);
  if (node) {
    node.innerHTML = html;
  }
}

function setPanel(tab, targetId) {
  const tabs = document.querySelectorAll('[role="tab"]');
  const panels = document.querySelectorAll('[role="tabpanel"]');
  for (const el of tabs) {
    el.setAttribute("aria-selected", String(el === tab));
  }
  for (const panel of panels) {
    panel.classList.toggle("hidden", panel.id !== targetId);
  }
}

function onTabKeyboard(event) {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const index = tabs.indexOf(event.currentTarget);
  if (index === -1) return;

  let next = index;
  if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
  if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
  if (next === index) return;

  event.preventDefault();
  const nextTab = tabs[next];
  nextTab.focus();
  setPanel(nextTab, nextTab.getAttribute("aria-controls") || "");
}

function bindTabs() {
  const tabs = document.querySelectorAll('[role="tab"]');
  for (const tab of tabs) {
    const target = tab.getAttribute("aria-controls");
    tab.addEventListener("click", () => setPanel(tab, target));
    tab.addEventListener("keydown", onTabKeyboard);
  }

  document.querySelectorAll("[role='tabpanel']").forEach((panel) => {
    panel.addEventListener("click", (event) => {
      if (!(event.target instanceof HTMLElement)) return;
      if (!event.target.classList.contains("copy-btn")) return;
      const id = event.target.getAttribute("data-copy-target");
      const src = document.getElementById(id);
      if (!src) return;
      navigator.clipboard?.writeText(src.textContent || "").then(() => {
        const status = event.target.nextElementSibling;
        if (status) {
          status.hidden = false;
          window.setTimeout(() => {
            status.hidden = true;
          }, 1000);
        }
      }).catch(() => {
        // no-op if clipboard not available in this context
      });
    });
  });
}

function renderDashboard(data) {
  renderById("panel-recommendations", toRows(data.recommendations || [], "Recommendations"));
  renderById("panel-pending", renderPatches(data.pending_patches || []));
  renderById("panel-anomalies", toRows(data.anomalies || [], "Anomalies"));
  renderById("panel-patterns", toRows(data.patterns || [], "Patterns"));
  renderById("panel-correlations", toRows(data.correlations || [], "Correlations"));
  renderById("panel-apply", renderApplyLog(data.apply_log || []));
  renderById("panel-gates", renderGatesAndInsights(data.gates_and_insights || {}));
  renderById("panel-suggestions", renderSuggestions(data.suggestions || []));

  const defaultTab = document.getElementById("tab-recommendations");
  setPanel(defaultTab, defaultTab.getAttribute("aria-controls"));
}

bindTabs();
renderDashboard(DATA);
