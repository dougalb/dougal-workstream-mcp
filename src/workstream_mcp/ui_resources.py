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
    :root {{ color-scheme: light dark; --border: #d0d7de; --muted: #57606a; --bg: #ffffff; --soft: #f6f8fa; --text: #24292f; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --border: #30363d; --muted: #8b949e; --bg: #0d1117; --soft: #161b22; --text: #e6edf3; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 14px; display: grid; gap: 12px; }}
    header {{ display: grid; gap: 4px; }}
    h1 {{ font-size: 18px; margin: 0; line-height: 1.25; }}
    h2 {{ font-size: 13px; margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0; color: var(--muted); }}
    section {{ border-top: 1px solid var(--border); padding-top: 10px; min-width: 0; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 4px 0; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }}
    .pill {{ display: inline-block; border: 1px solid var(--border); border-radius: 999px; padding: 1px 7px; font-size: 12px; color: var(--muted); }}
    .item {{ padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--soft); }}
    .item-title {{ font-weight: 600; overflow-wrap: anywhere; }}
    .item-meta {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    .warning {{ border-color: #bf8700; background: color-mix(in srgb, #bf8700 12%, var(--soft)); }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
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

function items(rows, renderer) {
  if (!Array.isArray(rows) || rows.length === 0) return '<p class="empty">None recorded.</p>';
  return `<ul>${rows.map(renderer).join("")}</ul>`;
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
    body = '<main id="root"><p class="empty">Loading project brief...</p></main>'
    script = (
        COMMON_SCRIPT
        + r"""
function listWithMeta(rows, kind) {
  return items(rows, (row) => `<li><span class="item-title">${escapeHtml(row.title || row.goal || row.uri || row.label)}</span><div class="item-meta">${escapeHtml(kind)} #${escapeHtml(row.id)} ${escapeHtml(row.created_at || "")}</div></li>`);
}

function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  if (data.error) {
    root.innerHTML = `<header><h1>Project not found</h1><div class="muted">${escapeHtml(data.project)}</div></header>`;
    return;
  }
  const project = data.project || {};
  const brief = data.project_brief || {};
  root.innerHTML = `
    <header>
      <h1>${escapeHtml(project.name || "Workstream project")}</h1>
      <div class="muted"><code>${escapeHtml(project.slug)}</code> ${brief.status ? `<span class="pill">${escapeHtml(brief.status)}</span>` : ""}</div>
    </header>
    <section><h2>Overview</h2><p>${escapeHtml(brief.summary || "No project summary recorded yet.")}</p></section>
    <section><h2>Current State</h2><p>${escapeHtml(brief.current_state || "No current state recorded.")}</p></section>
    <div class="grid">
      <section><h2>Open Tasks</h2>${listWithMeta(data.open_tasks, "task")}</section>
      <section><h2>Decisions</h2>${listWithMeta(data.decisions, "decision")}</section>
      <section><h2>Blockers</h2>${listWithMeta(data.open_blockers, "blocker")}</section>
      <section><h2>References</h2>${listWithMeta(data.references, "reference")}</section>
    </div>
    <section><h2>Recent Sessions / Handoffs</h2>${listWithMeta(data.codex_sessions, "session")}</section>
    <section><h2>Recent Events</h2>${listWithMeta(data.recent_events, "event")}</section>
    <section><h2>Next Steps</h2>${items(brief.next_steps, (step) => `<li>${escapeHtml(step)}</li>`)}</section>
    <section><h2>Risks</h2>${items(brief.risks, (risk) => `<li>${escapeHtml(risk)}</li>`)}</section>
  `;
}
"""
    )
    return _base_html("Workstreams project brief", body, script)


def search_results_html() -> str:
    body = '<main id="root"><p class="empty">Loading search results...</p></main>'
    script = (
        COMMON_SCRIPT
        + r"""
function groupByKind(results) {
  return results.reduce((groups, row) => {
    const kind = row.kind || "result";
    groups[kind] = groups[kind] || [];
    groups[kind].push(row);
    return groups;
  }, {});
}

function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  const results = Array.isArray(data.results) ? data.results : [];
  const groups = groupByKind(results);
  root.innerHTML = `
    <header>
      <h1>Search results</h1>
      <div class="muted">${results.length} result(s) for <code>${escapeHtml(data.query || "")}</code>${data.project ? ` in <code>${escapeHtml(data.project)}</code>` : ""}</div>
    </header>
    ${Object.entries(groups).map(([kind, rows]) => `
      <section>
        <h2>${escapeHtml(kind)}</h2>
        ${items(rows, (row) => `
          <li class="item">
            <span class="pill">${escapeHtml(row.kind)}</span>
            <span class="item-title">${escapeHtml(row.title)}</span>
            <div>${escapeHtml(row.snippet || "")}</div>
            <div class="item-meta"><code>${escapeHtml(row.stable_id || `${row.kind}:${row.id}`)}</code> ${escapeHtml(row.project || "")} ${escapeHtml(row.created_at || "")}</div>
          </li>`)}
      </section>`).join("") || '<p class="empty">No matching workstream entries.</p>'}
  `;
}
"""
    )
    return _base_html("Workstreams search results", body, script)


def write_review_html() -> str:
    body = '<main id="root"><p class="empty">Waiting for semantic write result...</p></main>'
    script = (
        COMMON_SCRIPT
        + r"""
function looksRaw(value) {
  const raw = text(value).toLowerCase();
  return raw.length > 4000 || raw.includes("bearer ") || raw.includes("-----begin ") || raw.includes("raw email");
}

function render(result) {
  const data = result.structuredContent || {};
  const root = document.getElementById("root");
  const summary = data.summary || data.title || "Write completed.";
  const ids = Object.entries(data).filter(([key, value]) => key.endsWith("_id") || key.endsWith("_ids")).map(([key, value]) => `<li><code>${escapeHtml(key)}</code>: ${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</li>`).join("");
  const warning = looksRaw(JSON.stringify(data)) ? '<section class="item warning"><h2>Review sensitivity</h2><p>This result looks unusually large or secret-like. Workstreams should store semantic coordination records, not raw private bodies or secrets.</p></section>' : "";
  root.innerHTML = `
    <header>
      <h1>Semantic capture recorded</h1>
      <div class="muted">${escapeHtml(data.project_slug || data.project || "workstream")}</div>
    </header>
    <section><h2>Summary</h2><p>${escapeHtml(summary)}</p></section>
    <section><h2>Record IDs</h2>${ids ? `<ul>${ids}</ul>` : '<p class="empty">No linked IDs returned.</p>'}</section>
    ${warning}
  `;
}
"""
    )
    return _base_html("Workstreams write review", body, script)
