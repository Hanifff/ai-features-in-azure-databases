// One handler for every panel. Each button names the endpoint it calls and the
// output block it writes to, so adding a panel is markup only.

const TICKET_COLUMNS = [
  ["rank", "Rank"],
  ["ticket_id", "Ticket"],
  ["domain", "Domain"],
  ["asset", "Asset"],
  ["error_code", "Code"],
  ["severity", "Severity"],
  ["title", "Title"],
  ["score", "Distance"],
  ["distance", "Distance"],
  ["rrf", "RRF"],
];

function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function table(rows) {
  if (!rows.length) {
    return '<p class="empty">No rows. That is the result, not a failure.</p>';
  }
  const keys = Object.keys(rows[0]);
  const isTicket = keys.includes("ticket_id");

  let columns;
  if (isTicket) {
    columns = TICKET_COLUMNS.filter(([k]) => keys.includes(k));
  } else {
    columns = keys.map(k => [k, k.replace(/_/g, " ")]);
  }

  let html = "<table class='rows'><tr>" + columns.map(([, h]) => `<th>${esc(h)}</th>`).join("") + "</tr>";
  for (const row of rows) {
    html += "<tr>" + columns.map(([k]) => {
      const cls = (k === "ticket_id" || k === "error_code") ? " class='mono'" : "";
      let v = row[k];
      if (typeof v === "number" && !Number.isInteger(v)) v = v.toFixed(4);
      return `<td${cls}>${esc(v)}</td>`;
    }).join("") + "</tr>";
    if (isTicket && row.description) {
      html += `<tr class="detail"><td colspan="${columns.length}"><i>${esc(row.description)}</i>`;
      if (row.resolution) html += `<br><b>Fixed by:</b> ${esc(row.resolution)}`;
      html += "</td></tr>";
    }
  }
  return html + "</table>";
}

function meta(data) {
  const bits = [];
  if (data.total_matches !== undefined && data.total_matches !== data.count) {
    bits.push(`${data.total_matches} tickets match, showing ${data.count}`);
  } else {
    bits.push(`${data.count} rows`);
  }
  if (data.ms !== undefined) bits.push(`${data.ms} ms`);
  return `<div class="meta">${bits.join(" &middot; ")}</div>`;
}

function sqlBlock(sql) {
  return `<details open><summary>Query that ran</summary><pre class="sql">${esc(sql)}</pre></details>`;
}

function noteBlock(note) {
  return note ? `<p class="note">${esc(note)}</p>` : "";
}

// The model answers in Markdown. Escape first, then allow back only bold, list
// items and ticket IDs, so nothing from the model can inject markup.
function formatAnswer(text) {
  const lines = esc(text).split("\n");
  let html = "";
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const item = line.match(/^(?:[-*]|\d+\.)\s+(.*)$/);
    if (item) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${item[1]}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (line) html += `<p>${line}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(INC-\d{4}-\d{4,5})/g, '<span class="tid">$1</span>');
}

// Once IDs are chipped inline, listing them again adds nothing. Report the
// verdict instead, and name only the ones that fail.
function citations(list) {
  if (!list.length) return '<p class="cites">No ticket IDs cited.</p>';
  const fake = list.filter(c => !c.exists);
  if (!fake.length) {
    return `<p class="cites"><span class="ok">checked: all ${list.length} cited tickets exist in the database</span></p>`;
  }
  return '<p class="cites"><span class="bad">'
    + fake.map(c => esc(c.ticket_id)).join(", ")
    + ` does not exist</span> <span class="ok">${list.length - fake.length} of ${list.length} verified</span></p>`;
}

function renderGrounded(data) {
  const k = data.keyword, s = data.semantic;
  const found = n => n === 1 ? "1 ticket" : `${n} tickets`;
  return `
    ${noteBlock(data.note)}
    <div class="split">
      <div class="side">
        <h3>Grounded in keyword search &middot; ${found(k.rows.length)}</h3>
        <div class="answer">${formatAnswer(k.answer)}</div>
        ${citations(k.citations)}
      </div>
      <div class="side grounded">
        <h3>Grounded in vector search &middot; ${found(s.rows.length)}</h3>
        <div class="answer">${formatAnswer(s.answer)}</div>
        ${citations(s.citations)}
      </div>
    </div>
    <details><summary>The tickets each search handed to the model</summary>
      <h4>Keyword search returned ${found(k.rows.length)}</h4>${table(k.rows)}${sqlBlock(k.sql)}
      <h4>Vector search returned ${found(s.rows.length)}</h4>${table(s.rows)}${sqlBlock(s.sql)}
    </details>
    <div class="meta">${esc(data.model)} &middot; ${data.ms} ms for both answers</div>`;
}

function renderPgAnswer(data) {
  return `
    <div class="side grounded">
      <h3>Answered by the database</h3>
      <div class="answer">${formatAnswer(data.answer)}</div>
      ${citations(data.citations)}
    </div>
    ${sqlBlock(data.sql)}
    <div class="meta">${esc(data.model)}, called by PostgreSQL &middot; ${data.ms} ms &middot; no application code in the loop</div>`;
}

function renderEmbed(data) {
  return `
    <table class="rows">
      <tr><th>Model</th><th>Dimensions</th><th>Time</th></tr>
      <tr><td class="mono">${esc(data.model)}</td><td>${data.dims}</td><td>${data.ms} ms</td></tr>
    </table>
    <pre class="sql">"${esc(data.text)}"

[${data.head.map(v => v.toFixed(6)).join(", ")}, ... ${data.dims - data.head.length} more]</pre>`;
}

function renderModels(data) {
  return table(data.deployments);
}

// Drawn as plain SVG from a layout the server computed. No drawing library: a
// CDN is a bad dependency for a demo that has to survive a venue network, and a
// fixed layout is steadier on screen than a simulation that settles differently
// every run.
function renderGraph(data) {
  if (!data.layout || !data.assets.length) {
    return '<p class="empty">Nothing to expand from.</p>';
  }
  const L = data.layout;
  let svg = `<svg class="graphviz" viewBox="0 0 ${L.width} ${L.height}" preserveAspectRatio="xMidYMid meet">`;

  const at = id => L.nodes.find(n => n.id === id);
  for (const e of L.edges) {
    const a = at(e.from), b = at(e.to);
    svg += `<line class="edge ${e.kind}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`;
  }
  for (const n of L.nodes) {
    svg += `<g class="node ${n.kind}">`
        +  `<circle cx="${n.x}" cy="${n.y}" r="${n.r}"/>`
        +  `<text x="${n.x}" y="${n.y + (n.kind === "code" ? 5 : -n.r - 10)}">${esc(n.label)}</text>`;
    if (n.tickets !== undefined) {
      svg += `<text class="count" x="${n.x}" y="${n.y + 5}">${n.tickets}</text>`;
    }
    svg += "</g>";
  }
  svg += "</svg>";

  const meaning = (data.meaning_only || []).map(a => a.asset);
  const newOnes = data.new_assets.map(a => a.asset);
  const verdict = meaning.length
    ? `<p class="reveal"><b>${meaning.length} reached only by meaning, over an edge no column could give you:</b> ${meaning.map(esc).join(", ")}</p>`
    : newOnes.length
      ? `<p class="reveal"><b>${newOnes.length} asset${newOnes.length > 1 ? "s" : ""} the search never returned:</b> ${newOnes.map(esc).join(", ")}</p>`
      : `<p class="reveal">The search happened to cover every affected asset this time.</p>`;

  const seeds = `<p class="meta">Seeded from ${data.seeds.length} tickets found by vector search `
    + `(${data.seeds.map(s => esc(s.ticket_id)).join(", ")}), which all carry `
    + `<b>${esc(data.code)}</b>.</p>`;

  let table = "<table class='rows'><tr><th>Asset</th><th>Domain</th><th>Tickets with this code</th><th>Similar tickets</th><th>Avg hours to fix</th><th>Reached by</th></tr>";
  for (const a of data.assets) {
    const hours = a.avg_hours === null ? "<i>still open</i>" : a.avg_hours;
    const how = a.by_meaning_only
      ? "<b class='no'>meaning only</b>"
      : (a.in_search ? "search" : "fault code");
    table += `<tr><td><b>${esc(a.asset)}</b></td><td>${esc(a.domain)}</td>`
          +  `<td>${a.tickets || ""}</td><td>${a.related || ""}</td><td>${hours}</td>`
          +  `<td>${how}</td></tr>`;
  }
  table += "</table>";

  return seeds + svg + verdict + table
    + `<details open><summary>The Cypher that ran, inside PostgreSQL</summary><pre class="sql">${esc(data.cypher)}</pre></details>`
    + `<details><summary>The vector search that seeded it</summary><pre class="sql">${esc(data.seed_sql)}</pre></details>`
    + noteBlock(data.note)
    + `<div class="meta">${data.ms} ms for both</div>`;
}

async function run(button) {
  const endpoint = button.dataset.run;
  const target = button.dataset.target || endpoint;
  const out = document.getElementById("out-" + target);
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Running";
  out.innerHTML = '<p class="working">Working</p>';

  const body = {};
  const picker = document.getElementById("q-" + (button.dataset.picker || target));
  if (picker) body.q = picker.value;
  if (endpoint === "embed") body.text = document.getElementById("embed-text").value;
  if (endpoint === "filtered") {
    body.severity = document.getElementById("f-severity").value;
    body.domain = document.getElementById("f-domain").value;
  }

  try {
    const response = await fetch("/api/" + endpoint, {
      method: endpoint === "models" ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: endpoint === "models" ? undefined : JSON.stringify(body),
    });
    const data = await response.json();

    if (data.error) {
      out.innerHTML = `<p class="failed">${esc(data.error)}</p>
        <p class="hint">Fall back to the matching cell in <code>src/ai-db-demos.ipynb</code>.</p>`;
    } else if (endpoint === "embed") {
      out.innerHTML = renderEmbed(data);
    } else if (endpoint === "grounded") {
      out.innerHTML = renderGrounded(data);
    } else if (endpoint === "pg/answer") {
      out.innerHTML = renderPgAnswer(data);
    } else if (endpoint === "models") {
      out.innerHTML = renderModels(data);
    } else if (endpoint === "graph") {
      out.innerHTML = renderGraph(data);
    } else {
      out.innerHTML = meta(data) + table(data.rows) + sqlBlock(data.sql) + noteBlock(data.note);
    }
  } catch (err) {
    out.innerHTML = `<p class="failed">${esc(err)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

document.querySelectorAll("[data-run]").forEach(b => b.addEventListener("click", () => run(b)));
