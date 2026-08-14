/* token-usage dashboard: fetches the committed data files and renders
 * one card per provider. No frameworks, no CDN — pure vanilla. */
const DATA_FILES = ["data/usage.json", "data/cursor.json", "data/opencode.json"];

const $ = (sel) => document.querySelector(sel);

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtMoney(v, cur) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const code = (cur || "USD").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: code, maximumFractionDigits: 2,
    }).format(v);
  } catch {
    return `${Number(v).toFixed(2)} ${cur || ""}`.trim();
  }
}

function fmtTokens(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function sparkline(values) {
  if (!values.length) return "";
  const w = 220, h = 40, pad = 4;
  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const pts = values.map((v, i) => {
    const x = values.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (values.length - 1);
    const y = h - pad - ((v - min) / (max - min)) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = pts[pts.length - 1].split(",");
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="trend over snapshots">` +
    `<polyline class="line" points="${pts.join(" ")}"/>` +
    `<circle class="dot" cx="${last[0]}" cy="${last[1]}" r="2.5"/></svg>`;
}

const chipOk = () => '<span class="chip ok">ok</span>';
const chipErr = () => '<span class="chip err">error</span>';
const chipMuted = (t) => `<span class="chip muted">${esc(t)}</span>`;

function card(title, chipHtml, big, rows, spark, date) {
  const rowsHtml = (rows || []).map(([k, v]) =>
    `<div class="row"><span class="k">${esc(k)}</span><span class="v">${v}</span></div>`
  ).join("");
  const dateHtml = date
    ? `<div class="row"><span class="k">snapshot</span><span class="v">${esc(date)}</span></div>`
    : "";
  return `<article class="card"><h2>${esc(title)}${chipHtml}</h2>` +
    `<div class="big">${big}</div><div class="rows">${rowsHtml}${dateHtml}</div>` +
    (spark ? `<div class="spark">${spark}</div>` : "") + `</article>`;
}

function renderOpenRouter(usage) {
  const snaps = usage?.snapshots || [];
  const latest = snaps[snaps.length - 1];
  if (!latest?.openrouter) {
    return card("OpenRouter", chipMuted("no data yet"), "—",
      [["setup", "add <code>OPENROUTER_API_KEY</code> secret, run workflow"]], "");
  }
  const o = latest.openrouter;
  if (!o.ok) {
    return card("OpenRouter", chipErr(), "—", [["error", esc(o.error || "unknown")]], "", latest.date);
  }
  const rows = [
    ["total credits", fmtMoney(o.total_credits)],
    ["used", fmtMoney(o.total_usage)],
  ];
  if (o.limit_remaining !== undefined) rows.push(["key limit left", fmtMoney(o.limit_remaining)]);
  if (o.key_label) rows.push(["key", esc(o.key_label)]);
  const series = snaps
    .filter((s) => s.openrouter?.ok && typeof s.openrouter.remaining === "number")
    .map((s) => s.openrouter.remaining);
  return card("OpenRouter", chipOk(), `${fmtMoney(o.remaining)} <small>credits left</small>`,
    rows, sparkline(series), latest.date);
}

function renderDeepSeek(usage) {
  const snaps = usage?.snapshots || [];
  const latest = snaps[snaps.length - 1];
  if (!latest?.deepseek) {
    return card("DeepSeek", chipMuted("no data yet"), "—",
      [["setup", "add <code>DEEPSEEK_API_KEY</code> secret, run workflow"]], "");
  }
  const d = latest.deepseek;
  const cur = d.balances?.[0]?.currency || "CNY";
  const sum = (b) => (d.balances || []).reduce((a, x) => a + parseFloat(x[b] || 0), 0);
  if (!d.ok) {
    return card("DeepSeek", chipErr(), "—", [["error", esc(d.error || "unknown")]], "", latest.date);
  }
  const rows = (d.balances || []).map((b) =>
    [`${esc(b.currency)} total`, fmtMoney(parseFloat(b.total_balance || 0), b.currency)]);
  rows.push(["granted", fmtMoney(sum("granted_balance"), cur)]);
  rows.push(["topped-up", fmtMoney(sum("topped_up_balance"), cur)]);
  const series = snaps
    .filter((s) => s.deepseek?.ok)
    .map((s) => (s.deepseek.balances || []).reduce((a, b) => a + parseFloat(b.total_balance || 0), 0));
  return card("DeepSeek", chipOk(), `${fmtMoney(sum("total_balance"), cur)} <small>balance</small>`,
    rows, sparkline(series), latest.date);
}

function renderCursor(cursor) {
  const snaps = cursor?.snapshots || [];
  const latest = snaps[snaps.length - 1];
  if (!latest) {
    return card("Cursor", chipMuted("no data yet"), "—",
      [["setup", "run <code>./scripts/token_usage.sh install cursor</code> on this Mac"]], "");
  }
  if (!latest.ok) {
    return card("Cursor", chipErr(), "—",
      [["error", esc(latest.error || "unknown")]], "", latest.date);
  }
  const plan = latest.plan || {};
  const onDemand = latest.onDemand || {};
  const cycle = latest.billingCycleStart || latest.startOfMonth || "—";
  const rows = [
    ["plan", esc(latest.membershipType || "—")],
    ["period start", esc(cycle)],
  ];
  if (typeof onDemand.used === "number") {
    rows.push(["on-demand", onDemand.enabled ? String(onDemand.used) : "off"]);
  }
  let big = `<small>usage data</small>`;
  if (typeof plan.used === "number" && typeof plan.limit === "number") {
    big = `${plan.used} <small>/ ${plan.limit}</small>`;
    if (typeof plan.remaining === "number") rows.push(["remaining", plan.remaining]);
    if (typeof plan.totalPercentUsed === "number") {
      rows.push(["used", `${plan.totalPercentUsed.toFixed(1)}%`]);
    }
  } else {
    const u = latest.usage || {};
    const ks = Object.keys(u).filter((k) => k !== "startOfMonth").slice(0, 3);
    rows.push(["models", esc(ks.join(", ") || "—")]);
  }
  const series = snaps
    .filter((s) => s.ok && typeof s.plan?.used === "number")
    .map((s) => s.plan.used);
  return card("Cursor", chipOk(), big, rows, sparkline(series), latest.date);
}

function renderOpenCode(oc) {
  const snaps = oc?.snapshots || [];
  const latest = snaps[snaps.length - 1];
  if (!latest) {
    return card("OpenCode (local)", chipMuted("no data yet"), "—",
      [["setup", "run <code>./scripts/token_usage.sh push opencode</code> on this machine"]], "");
  }
  const t = latest.totals || {};
  const rows = [
    ["calls", fmtTokens(t.n)],
    ["input tokens", fmtTokens(t.input)],
    ["output tokens", fmtTokens(t.output)],
    ["cache read", fmtTokens(t.cache_read)],
    ["24h cost", fmtMoney(latest.delta24h?.cost, "USD")],
  ];
  const series = snaps.filter((s) => typeof s.totals?.cost === "number").map((s) => s.totals.cost);
  return card("OpenCode (local)", chipOk(), `${fmtMoney(t.cost, "USD")} <small>total cost</small>`,
    rows, sparkline(series), latest.date);
}

async function fetchJson(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function buildStatus(usage, cursor, oc) {
  const warnings = [];
  let anyErr = false;
  const latest = (data, key) => (data?.snapshots || []).slice(-1)[0]?.[key];
  const check = (data, key, label) => {
    const b = latest(data, key);
    if (b && !b.ok) {
      anyErr = true;
      const d = data.snapshots.slice(-1)[0];
      warnings.push(`${label} error (${esc(d.date)}): ${esc(b.error || "unknown")}`);
    }
  };
  check(usage, "openrouter", "OpenRouter");
  check(usage, "deepseek", "DeepSeek");
  const cursorLatest = (cursor?.snapshots || []).slice(-1)[0];
  if (cursorLatest && cursorLatest.ok === false) {
    anyErr = true;
    warnings.push(`Cursor error (${esc(cursorLatest.date)}): ${esc(cursorLatest.error || "unknown")}`);
  }
  if (usage && (usage.snapshots || []).length === 0) {
    warnings.push("OpenRouter/DeepSeek: no snapshots yet — add the two secrets in repo Settings → Actions and run the workflow.");
  }
  if (!cursor || !(cursor.snapshots || []).length) {
    warnings.push("Cursor: no snapshots yet — run ./scripts/token_usage.sh push cursor on this Mac.");
  }
  if (!oc) warnings.push("OpenCode: no data file yet — run ./scripts/token_usage.sh push opencode on this machine.");
  return { warnings, anyErr };
}

function lastDate(data) {
  const s = data?.snapshots || [];
  return s.length ? s[s.length - 1].date : null;
}

async function main() {
  const [usage, cursor, oc] = await Promise.all(DATA_FILES.map(fetchJson));
  const cards = [
    renderOpenRouter(usage),
    renderDeepSeek(usage),
    renderCursor(cursor),
    renderOpenCode(oc),
  ];
  $("#cards").innerHTML = cards.join("");

  const { warnings, anyErr } = buildStatus(usage, cursor, oc);
  const statusEl = $("#status");
  if (warnings.length) {
    statusEl.hidden = false;
    statusEl.className = "status" + (anyErr ? " err" : "");
    statusEl.innerHTML = warnings.map((w) => `<div>⚠ ${w}</div>`).join("");
  }

  const dates = [
    ["OpenRouter", lastDate(usage)],
    ["DeepSeek", lastDate(usage)],
    ["Cursor", lastDate(cursor)],
    ["OpenCode", lastDate(oc)],
  ].filter(([, d]) => d).map(([n, d]) => `${n} ${d}`).join(" · ");
  $("#updated").textContent = dates
    ? `Last snapshots: ${dates} · page rendered ${new Date().toLocaleString()}`
    : `Page rendered ${new Date().toLocaleString()} — no snapshots collected yet`;
}

main();
