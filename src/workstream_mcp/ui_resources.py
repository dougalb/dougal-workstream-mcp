from __future__ import annotations


def _base_html(title: str, body: str, script: str) -> str:
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #ffffff;
      --surface: #f6f8fa;
      --surface-strong: #eef2f6;
      --border: #d0d7de;
      --text: #24292f;
      --muted: #57606a;
      --accent: #0969da;
      --warning: #9a6700;
      --safe-inline: 20px;
      --safe-block-start: 24px;
      --safe-block-end: 20px;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0d1117;
        --surface: #161b22;
        --surface-strong: #1c2128;
        --border: #30363d;
        --text: #e6edf3;
        --muted: #8b949e;
        --accent: #58a6ff;
        --warning: #d29922;
      }}
    }}
    * {{ box-sizing: border-box; }}
    html {{ margin: 0; min-width: 0; background: var(--bg); }}
    body {{
      margin: 0;
      min-width: 0;
      overflow-x: hidden;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .workstreams-ui {{
      width: 100%;
      min-width: 0;
      padding: var(--safe-block-start) var(--safe-inline) var(--safe-block-end);
      background: var(--bg);
    }}
    .app-frame {{
      width: 100%;
      min-width: 0;
      padding: 0;
      display: grid;
      gap: 14px;
      overflow: hidden;
    }}
    .app-header {{ display: grid; gap: 8px; min-width: 0; }}
    .eyebrow {{
      margin: 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 0; color: var(--text); font-size: 18px; line-height: 1.25; overflow-wrap: anywhere; }}
    .summary-bar {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-width: 0; }}
    .summary-chip {{
      max-width: 100%;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--muted);
      background: var(--surface);
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .summary-chip strong {{ color: var(--text); font-weight: 650; }}
    .group-section {{
      min-width: 0;
      display: grid;
      gap: 8px;
      border-top: 1px solid var(--border);
      padding-top: 12px;
    }}
    .section-heading {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }}
    .section-title {{ margin: 0; color: var(--muted); font-size: 13px; font-weight: 750; line-height: 1.25; }}
    .section-count {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .section-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); }}
    .result-list, .compact-list {{ display: grid; gap: 8px; min-width: 0; }}
    .result-row {{
      min-width: 0;
      display: grid;
      gap: 7px;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
    }}
    .result-topline {{ min-width: 0; display: flex; flex-wrap: wrap; gap: 7px; align-items: baseline; }}
    .badge {{
      flex: 0 0 auto;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 1px 7px;
      color: var(--muted);
      background: var(--surface-strong);
      font-size: 12px;
      line-height: 1.45;
    }}
    .result-title {{ min-width: 0; color: var(--text); font-weight: 700; overflow-wrap: anywhere; }}
    .snippet, .snippet-preview {{ margin: 0; min-width: 0; color: var(--text); overflow-wrap: anywhere; }}
    .snippet-collapse {{ min-width: 0; }}
    .snippet-collapse summary {{
      cursor: pointer;
      color: var(--accent);
      font-size: 12px;
      font-weight: 650;
      list-style-position: inside;
    }}
    .snippet-collapse p {{ margin: 6px 0 0; color: var(--text); overflow-wrap: anywhere; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 4px 10px; min-width: 0; color: var(--muted); font-size: 12px; }}
    .meta-token {{ min-width: 0; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .compact-row {{
      min-width: 0;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      padding: 8px 0;
      border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
    }}
    .compact-row:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .compact-body {{ min-width: 0; display: grid; gap: 2px; }}
    .compact-title {{ font-weight: 650; overflow-wrap: anywhere; }}
    .compact-meta {{ color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
    .empty {{ margin: 0; color: var(--muted); font-style: italic; }}
    .warning-row {{ border-color: var(--warning); background: color-mix(in srgb, var(--warning) 12%, var(--surface)); }}
    @media (max-width: 560px) {{
      :root {{ --safe-inline: 18px; --safe-block-start: 30px; --safe-block-end: 20px; }}
      body {{ font-size: 14px; }}
      .app-frame {{ gap: 12px; }}
      h1 {{ font-size: 17px; }}
      .summary-chip {{ font-size: 11px; }}
      .result-row {{ padding: 10px; }}
      .section-grid {{ grid-template-columns: 1fr; }}
      .compact-row {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
{body}
<script>
{script}
</script>
</body>
</html>
""".strip()


COMMON_SCRIPT = r"""
const state = { result: null };
const KIND_LABELS = {
  event: "Events",
  task: "Tasks",
  decision: "Decisions",
  blocker: "Blockers",
  reference: "References",
  codex_session: "Codex sessions",
  session: "Sessions",
  handoff: "Handoffs"
};
const KIND_BADGES = {
  event: "event",
  task: "task",
  decision: "decision",
  blocker: "blocker",
  reference: "reference",
  codex_session: "session",
  session: "session",
  handoff: "handoff"
};

function text(value, fallback = "") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function escapeHtml(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function rows(value) {
  return Array.isArray(value) ? value : [];
}

function groupLabel(kind) {
  const key = text(kind, "result");
  return KIND_LABELS[key] || key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function badgeLabel(kind) {
  const key = text(kind, "result");
  return KIND_BADGES[key] || key.replaceAll("_", " ");
}

function countLabel(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function chip(label, value) {
  const body = text(value);
  if (!body) return "";
  return `<span class="summary-chip"><strong>${escapeHtml(label)}</strong> ${escapeHtml(body)}</span>`;
}

function emptyState(message = "None recorded.") {
  return `<p class="empty">${escapeHtml(message)}</p>`;
}

function formatTimestamp(value) {
  return text(value).replace("T", " ").replace("Z", " UTC");
}

function metaRow(parts) {
  const filtered = parts.filter((part) => text(part));
  if (!filtered.length) return "";
  return `<div class="meta-row">${filtered.map((part) => `<span class="meta-token">${escapeHtml(part)}</span>`).join("")}</div>`;
}

function snippetBlock(value, limit = 220) {
  const body = text(value);
  if (!body) return "";
  if (body.length <= limit) return `<p class="snippet">${escapeHtml(body)}</p>`;
  const preview = `${body.slice(0, limit).trim()}...`;
  return `
    <p class="snippet-preview">${escapeHtml(preview)}</p>
    <details class="snippet-collapse">
      <summary>Show full snippet</summary>
      <p>${escapeHtml(body)}</p>
    </details>
  `;
}

function compactRows(items, kind, emptyMessage = "None recorded.") {
  const list = rows(items);
  if (!list.length) return emptyState(emptyMessage);
  return `<div class="compact-list">${list.map((row) => `
    <div class="compact-row">
      <span class="badge">${escapeHtml(badgeLabel(kind))}</span>
      <div class="compact-body">
        <div class="compact-title">${escapeHtml(row.title || row.goal || row.uri || row.label || "Untitled")}</div>
        <div class="compact-meta">${escapeHtml([row.id ? `${badgeLabel(kind)}:${row.id}` : "", formatTimestamp(row.created_at)].filter(Boolean).join(" | "))}</div>
      </div>
    </div>
  `).join("")}</div>`;
}

function section(title, count, body) {
  return `
    <section class="group-section">
      <div class="section-heading">
        <h2 class="section-title">${escapeHtml(title)}</h2>
        ${Number.isFinite(count) ? `<span class="section-count">${escapeHtml(String(count))}</span>` : ""}
      </div>
      ${body}
    </section>
  `;
}

function latestResultFromOpenAI() {
  const bridge = window.openai;
  if (!bridge) return null;
  const meta = bridge.toolResponseMetadata;
  if (meta?.mcp_tool_result) return meta.mcp_tool_result;
  if (meta?.call_tool_result) return meta.call_tool_result;
  if (bridge.toolOutput) return { structuredContent: bridge.toolOutput, _meta: meta || {} };
  return null;
}

function resultFromGlobals(globals) {
  if (!globals) return null;
  const meta = globals.toolResponseMetadata;
  if (meta?.mcp_tool_result) return meta.mcp_tool_result;
  if (meta?.call_tool_result) return meta.call_tool_result;
  if (globals.toolOutput) return { structuredContent: globals.toolOutput, _meta: meta || {} };
  return latestResultFromOpenAI();
}

function acceptResult(result) {
  if (!result) return;
  state.result = result;
  render(result);
}

window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  const message = event.data;
  if (message?.method === "ui/notifications/tool-result") acceptResult(message.params);
}, { passive: true });

window.addEventListener("openai:set_globals", (event) => {
  acceptResult(resultFromGlobals(event.detail?.globals));
}, { passive: true });

acceptResult(latestResultFromOpenAI());
setTimeout(() => acceptResult(latestResultFromOpenAI()), 50);
setTimeout(() => acceptResult(latestResultFromOpenAI()), 500);
"""


def project_brief_html() -> str:
    body = """
<main class="workstreams-ui workstreams-project-brief">
  <div id="root" class="app-frame"><p class="empty">Loading project brief...</p></div>
</main>
""".strip()
    script = (
        COMMON_SCRIPT
        + r"""
function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  if (data.error) {
    root.innerHTML = `<header class="app-header"><p class="eyebrow">Project brief</p><h1>Project not found</h1><div class="summary-bar">${chip("Query", data.project)}</div></header>`;
    return;
  }
  const project = data.project || {};
  const brief = data.project_brief || {};
  const openTasks = rows(data.open_tasks);
  const blockers = rows(data.open_blockers);
  const decisions = rows(data.decisions);
  const references = rows(data.references);
  const sessions = rows(data.codex_sessions);
  const events = rows(data.recent_events);
  root.innerHTML = `
    <header class="app-header">
      <p class="eyebrow">Project brief</p>
      <h1>${escapeHtml(project.name || "Workstream project")}</h1>
      <div class="summary-bar">
        ${chip("Slug", project.slug)}
        ${chip("Status", brief.status || project.status)}
        ${chip("Tasks", String(openTasks.length))}
        ${chip("Blockers", String(blockers.length))}
      </div>
    </header>
    ${section("Overview", null, `<p class="snippet">${escapeHtml(brief.summary || "No project summary recorded yet.")}</p>`)}
    ${section("Current state", null, `<p class="snippet">${escapeHtml(brief.current_state || "No current state recorded.")}</p>`)}
    <div class="section-grid">
      ${section("Open tasks", openTasks.length, compactRows(openTasks, "task"))}
      ${section("Decisions", decisions.length, compactRows(decisions, "decision"))}
      ${section("Blockers", blockers.length, compactRows(blockers, "blocker"))}
      ${section("References", references.length, compactRows(references, "reference"))}
    </div>
    ${section("Recent sessions and handoffs", sessions.length, compactRows(sessions, "codex_session"))}
    ${section("Recent events", events.length, compactRows(events, "event"))}
    ${section("Next steps", rows(brief.next_steps).length, compactRows(rows(brief.next_steps).map((title) => ({ title })), "task", "No next steps recorded."))}
    ${section("Risks", rows(brief.risks).length, compactRows(rows(brief.risks).map((title) => ({ title })), "blocker", "No risks recorded."))}
  `;
}
"""
    )
    return _base_html("Workstreams project brief", body, script)


def search_results_html() -> str:
    body = """
<main class="workstreams-ui workstreams-search-results">
  <div id="root" class="app-frame"><p class="empty">Loading search results...</p></div>
</main>
""".strip()
    script = (
        COMMON_SCRIPT
        + r"""
const SEARCH_KIND_ORDER = ["event", "task", "decision", "blocker", "reference", "codex_session"];

function firstText(row, keys) {
  for (const key of keys) {
    const value = text(row?.[key]);
    if (value) return value;
  }
  return "";
}

function projectName(row, fallback = "") {
  return firstText(row, ["project", "project_slug", "project_name"]) || fallback;
}

function normalizeResult(row, kind, fallbackProject = "") {
  const normalizedKind = firstText(row, ["kind", "event_type"]) || kind || "result";
  const id = row?.id;
  const stableId = firstText(row, ["stable_id"]) || (id === undefined || id === null ? "" : `${normalizedKind}:${id}`);
  return {
    kind: normalizedKind,
    id,
    stable_id: stableId,
    project: projectName(row, fallbackProject),
    title: firstText(row, ["title", "goal", "label", "uri"]) || "Untitled result",
    snippet: firstText(row, ["snippet", "summary", "description", "body", "rationale", "tests_summary"]),
    created_at: firstText(row, ["created_at", "updated_at"])
  };
}

function normalizeSearchRows(data) {
  const fallbackProject = text(data.project);
  const normalized = [];
  rows(data.results).forEach((row) => normalized.push(normalizeResult(row, row.kind, fallbackProject)));
  rows(data.events).forEach((row) => normalized.push(normalizeResult(row, "event", fallbackProject)));
  rows(data.unconsumed_events).forEach((row) => normalized.push(normalizeResult(row, "event", fallbackProject)));
  rows(data.tasks).forEach((row) => normalized.push(normalizeResult(row, "task", fallbackProject)));
  rows(data.assigned_open_tasks).forEach((row) => normalized.push(normalizeResult(row, "task", fallbackProject)));
  rows(data.requested_followups).forEach((row) => normalized.push(normalizeResult(row, "task", fallbackProject)));
  rows(data.stale_items).forEach((row) => normalized.push(normalizeResult(row, "task", fallbackProject)));
  rows(data.open_blockers).forEach((row) => normalized.push(normalizeResult(row, "blocker", fallbackProject)));
  rows(data.recent_decisions).forEach((row) => normalized.push(normalizeResult(row, "decision", fallbackProject)));
  return normalized;
}

function inferredQuery(data) {
  if (text(data.query)) return data.query;
  if (text(data.agent)) return `Digest for ${data.agent}`;
  if (data.events) return "Recent changes";
  if (data.tasks) return "Open tasks";
  return "Workstream results";
}

function groupByKind(results) {
  return results.reduce((groups, row) => {
    const kind = row.kind || "result";
    groups[kind] = groups[kind] || [];
    groups[kind].push(row);
    return groups;
  }, {});
}

function orderedGroups(groups) {
  return Object.entries(groups).sort(([left], [right]) => {
    const leftIndex = SEARCH_KIND_ORDER.indexOf(left);
    const rightIndex = SEARCH_KIND_ORDER.indexOf(right);
    if (leftIndex !== -1 || rightIndex !== -1) return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex);
    return left.localeCompare(right);
  });
}

function resultRow(row) {
  const stableId = row.stable_id || `${row.kind}:${row.id}`;
  return `
    <article class="result-row">
      <div class="result-topline">
        <span class="badge">${escapeHtml(badgeLabel(row.kind))}</span>
        <div class="result-title">${escapeHtml(row.title || "Untitled result")}</div>
      </div>
      ${snippetBlock(row.snippet)}
      ${metaRow([stableId, row.project, formatTimestamp(row.created_at)])}
    </article>
  `;
}

function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  const results = normalizeSearchRows(data);
  const groups = orderedGroups(groupByKind(results));
  root.innerHTML = `
    <header class="app-header">
      <p class="eyebrow">Workstreams search</p>
      <h1>Search results</h1>
      <div class="summary-bar">
        ${chip("Results", String(results.length))}
        ${chip("Query", inferredQuery(data))}
        ${chip("Project", data.project || "All projects")}
      </div>
    </header>
    ${groups.map(([kind, groupedRows]) => section(groupLabel(kind), groupedRows.length, `<div class="result-list">${groupedRows.map(resultRow).join("")}</div>`)).join("") || emptyState("No matching workstream entries.")}
  `;
}
"""
    )
    return _base_html("Workstreams search results", body, script)


def write_review_html() -> str:
    body = """
<main class="workstreams-ui workstreams-write-review">
  <div id="root" class="app-frame"><p class="empty">Waiting for semantic write result...</p></div>
</main>
""".strip()
    script = (
        COMMON_SCRIPT
        + r"""
function looksRaw(value) {
  const raw = text(value).toLowerCase();
  return raw.length > 4000 || raw.includes("bearer ") || raw.includes("-----begin ") || raw.includes("raw email");
}

function idRows(data) {
  return Object.entries(data)
    .filter(([key]) => key.endsWith("_id") || key.endsWith("_ids"))
    .map(([key, value]) => ({ title: `${key}: ${Array.isArray(value) ? value.join(", ") : value}` }));
}

function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  const summary = data.summary || data.title || "Write completed.";
  const ids = idRows(data);
  const warning = looksRaw(JSON.stringify(data))
    ? section("Review sensitivity", null, `<article class="result-row warning-row"><p class="snippet">This result looks unusually large or secret-like. Workstreams should store semantic coordination records, not raw private bodies or secrets.</p></article>`)
    : "";
  root.innerHTML = `
    <header class="app-header">
      <p class="eyebrow">Workstreams write</p>
      <h1>Semantic capture recorded</h1>
      <div class="summary-bar">
        ${chip("Project", data.project_slug || data.project || "workstream")}
        ${chip("Event", data.event_id)}
        ${chip("Created", data.created === undefined ? "" : String(Boolean(data.created)))}
      </div>
    </header>
    ${section("Summary", null, `<p class="snippet">${escapeHtml(summary)}</p>`)}
    ${section("Record IDs", ids.length, compactRows(ids, "reference", "No linked IDs returned."))}
    ${warning}
  `;
}
"""
    )
    return _base_html("Workstreams write review", body, script)
