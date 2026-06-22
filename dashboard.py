#!/usr/bin/env python3
"""
AI Lawsuit Monitor — Web Dashboard
실행: python dashboard.py  →  http://localhost:5000
"""

import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "lawsuits.db")

app = Flask(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 학습데이터 소송 모니터</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+KR:wght@300;400;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0e17;
    --surface: #111827;
    --border: #1e2d40;
    --accent: #00d4ff;
    --red: #ff4757;
    --yellow: #ffd32a;
    --green: #2ed573;
    --text: #e2e8f0;
    --muted: #64748b;
    --font-mono: 'IBM Plex Mono', monospace;
    --font-sans: 'Noto Sans KR', sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font-sans); min-height: 100vh; }

  /* ── Header ── */
  header {
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
    display: flex; align-items: center; gap: 16px;
    background: linear-gradient(90deg, #0a0e17 0%, #0f172a 100%);
  }
  header .logo {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--accent);
    letter-spacing: .15em;
    text-transform: uppercase;
  }
  header h1 {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -.01em;
    flex: 1;
  }
  header .pulse {
    width: 8px; height: 8px; border-radius: 50%; background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

  /* ── Layout ── */
  .main { display: grid; grid-template-columns: 260px 1fr; min-height: calc(100vh - 65px); }
  .sidebar {
    border-right: 1px solid var(--border);
    padding: 24px 16px;
    background: var(--surface);
    display: flex; flex-direction: column; gap: 24px;
  }
  .content { padding: 28px 32px; overflow-x: auto; }

  /* ── Stats ── */
  .stats { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; margin-bottom: 28px; }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }
  .stat .val {
    font-family: var(--font-mono);
    font-size: 28px;
    font-weight: 600;
    color: var(--accent);
  }
  .stat .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }

  /* ── Filters ── */
  .filter-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
  .filter-row select, .filter-row input {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 7px 12px;
    border-radius: 6px;
    font-size: 13px;
    font-family: var(--font-sans);
  }
  .filter-row input { flex: 1; min-width: 200px; }

  /* ── Table ── */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--muted);
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    white-space: nowrap;
  }
  tbody tr {
    border-bottom: 1px solid #1a2235;
    transition: background .15s;
    cursor: pointer;
  }
  tbody tr:hover { background: #141f2e; }
  td { padding: 12px 14px; vertical-align: top; }
  td.case-name { font-weight: 600; max-width: 220px; }
  td.case-name small { display: block; color: var(--muted); font-weight: 400; font-size: 11px; margin-top: 3px; }

  /* ── Badges ── */
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-family: var(--font-mono);
    font-weight: 600;
    text-transform: uppercase;
  }
  .badge-active  { background: rgba(0,212,255,.12); color: var(--accent); border: 1px solid rgba(0,212,255,.3); }
  .badge-settled { background: rgba(46,213,115,.12); color: var(--green); border: 1px solid rgba(46,213,115,.3); }
  .badge-dismissed { background: rgba(100,116,139,.12); color: var(--muted); border: 1px solid var(--border); }
  .badge-appealed { background: rgba(255,211,42,.12); color: var(--yellow); border: 1px solid rgba(255,211,42,.3); }
  .badge-closed  { background: rgba(255,71,87,.12); color: var(--red); border: 1px solid rgba(255,71,87,.3); }
  .flag { font-size: 18px; }

  /* ── Detail modal ── */
  .modal-backdrop {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.7);
    z-index: 100; align-items: center; justify-content: center;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    width: 680px; max-width: 95vw; max-height: 88vh;
    overflow-y: auto; padding: 28px;
  }
  .modal h2 { font-size: 18px; margin-bottom: 20px; }
  .modal-close {
    float: right; background: none; border: none;
    color: var(--muted); cursor: pointer; font-size: 22px;
    line-height: 1; margin-top: -4px;
  }
  .detail-grid { display: grid; grid-template-columns: 140px 1fr; gap: 10px 16px; }
  .detail-grid dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .1em; padding-top: 2px; }
  .detail-grid dd { font-size: 13px; }

  /* ── Updates list ── */
  .updates-section { margin-top: 24px; }
  .updates-section h3 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; margin-bottom: 12px; }
  .update-item {
    border-left: 2px solid var(--accent);
    padding: 10px 14px;
    margin-bottom: 10px;
    background: #0d1420;
    border-radius: 0 6px 6px 0;
  }
  .update-item .upd-type { font-family: var(--font-mono); font-size: 11px; color: var(--accent); }
  .update-item .upd-date { font-size: 11px; color: var(--muted); float: right; }
  .update-item .upd-desc { font-size: 13px; margin-top: 6px; }

  /* ── Sidebar nav ── */
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px; border-radius: 6px; cursor: pointer;
    font-size: 13px; color: var(--muted); transition: all .15s;
  }
  .nav-item:hover, .nav-item.active { background: #1a2640; color: var(--text); }
  .nav-item .icon { font-size: 16px; }

  .section-title {
    font-family: var(--font-mono);
    font-size: 10px; letter-spacing: .15em;
    text-transform: uppercase; color: var(--muted);
    padding: 0 4px; margin-bottom: 8px;
  }

  .country-tag {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 12px; border-radius: 6px; cursor: pointer;
    font-size: 12px; transition: background .15s;
  }
  .country-tag:hover { background: #1a2640; }
  .country-tag .count {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 11px; color: var(--muted);
  }

  .run-btn {
    background: linear-gradient(135deg, var(--accent), #0099cc);
    border: none; color: #000; padding: 10px 18px; border-radius: 6px;
    font-family: var(--font-mono); font-size: 12px; cursor: pointer;
    font-weight: 600; width: 100%; letter-spacing: .05em;
    transition: opacity .15s;
  }
  .run-btn:hover { opacity: .85; }
  .run-btn:disabled { opacity: .4; cursor: not-allowed; }

  a.src-link { color: var(--accent); font-size: 12px; text-decoration: none; display: block; margin-top: 3px; }
  a.src-link:hover { text-decoration: underline; }

  .empty { text-align: center; color: var(--muted); padding: 60px; font-size: 14px; }
</style>
</head>
<body>

<header>
  <div class="logo">⚖ AI-LM</div>
  <h1>AI 학습데이터 소송 모니터</h1>
  <div class="pulse"></div>
  <span id="last-run" style="font-size:12px;color:var(--muted);margin-left:12px;font-family:var(--font-mono)"></span>
</header>

<div class="main">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div>
      <div class="section-title">Navigation</div>
      <div class="nav-item active" onclick="showView('all')">
        <span class="icon">📋</span> 전체 소송
      </div>
      <div class="nav-item" onclick="showView('updates')">
        <span class="icon">🔄</span> 최근 업데이트
      </div>
    </div>

    <div>
      <div class="section-title">국가별 필터</div>
      <div id="country-list"></div>
    </div>

    <div style="margin-top:auto">
      <button class="run-btn" id="run-btn" onclick="runNow()">▶ 지금 검색 실행</button>
      <div style="font-size:11px;color:var(--muted);text-align:center;margin-top:8px">
        자동: 매일 08:00 / 20:00 KST
      </div>
    </div>
  </aside>

  <!-- Main content -->
  <main class="content">
    <!-- Stats -->
    <div class="stats">
      <div class="stat">
        <div class="val" id="stat-total">—</div>
        <div class="lbl">전체 소송</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-active" style="color:var(--accent)">—</div>
        <div class="lbl">진행중</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-new" style="color:var(--yellow)">—</div>
        <div class="lbl">이번 주 신규</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-row">
      <input type="text" id="search-input" placeholder="🔍  사건명, 원고, 피고 검색..." oninput="applyFilters()">
      <select id="status-filter" onchange="applyFilters()">
        <option value="">전체 상태</option>
        <option value="active">진행중</option>
        <option value="settled">합의</option>
        <option value="dismissed">기각</option>
        <option value="appealed">항소</option>
        <option value="closed">종결</option>
      </select>
      <select id="country-filter" onchange="applyFilters()">
        <option value="">전체 국가</option>
        <option value="US">🇺🇸 미국</option>
        <option value="KR">🇰🇷 한국</option>
        <option value="JP">🇯🇵 일본</option>
        <option value="CN">🇨🇳 중국</option>
        <option value="DE">🇩🇪 독일</option>
        <option value="FR">🇫🇷 프랑스</option>
        <option value="GB">🇬🇧 영국</option>
        <option value="EU">🇪🇺 EU</option>
      </select>
    </div>

    <!-- Table -->
    <div id="view-all">
      <table>
        <thead>
          <tr>
            <th>국가</th>
            <th>사건명 / 원고 v 피고</th>
            <th>법원</th>
            <th>대상 데이터</th>
            <th>소송 원인</th>
            <th>제소일</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody id="lawsuit-table"></tbody>
      </table>
      <div class="empty" id="empty-msg" style="display:none">조건에 맞는 소송이 없습니다</div>
    </div>

    <div id="view-updates" style="display:none">
      <div id="updates-list"></div>
    </div>
  </main>
</div>

<!-- Detail Modal -->
<div class="modal-backdrop" id="modal">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">×</button>
    <h2 id="modal-title">—</h2>
    <dl class="detail-grid" id="modal-body"></dl>
    <div class="updates-section">
      <h3>진행 내역</h3>
      <div id="modal-updates"></div>
    </div>
  </div>
</div>

<script>
const FLAGS = {US:"🇺🇸",KR:"🇰🇷",JP:"🇯🇵",CN:"🇨🇳",DE:"🇩🇪",FR:"🇫🇷",GB:"🇬🇧",EU:"🇪🇺"};
const STATUS_LABELS = {active:"진행중",settled:"합의",dismissed:"기각",appealed:"항소",closed:"종결"};
let allLawsuits = [];

async function loadData() {
  const r = await fetch("/api/lawsuits");
  const data = await r.json();
  allLawsuits = data.lawsuits;

  document.getElementById("stat-total").textContent = data.stats.total;
  document.getElementById("stat-active").textContent = data.stats.active;
  document.getElementById("stat-new").textContent = data.stats.new_this_week;
  document.getElementById("last-run").textContent = data.stats.last_run ? "마지막 실행: "+data.stats.last_run : "";

  // Country sidebar
  const counts = {};
  allLawsuits.forEach(l => { counts[l.country] = (counts[l.country]||0)+1; });
  const el = document.getElementById("country-list");
  el.innerHTML = Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([c,n])=>`
    <div class="country-tag" onclick="filterByCountry('${c}')">
      <span>${FLAGS[c]||"🌐"}</span><span>${c}</span><span class="count">${n}</span>
    </div>`).join("");

  applyFilters();
}

function applyFilters() {
  const q = document.getElementById("search-input").value.toLowerCase();
  const st = document.getElementById("status-filter").value;
  const co = document.getElementById("country-filter").value;
  const filtered = allLawsuits.filter(l => {
    const text = `${l.case_name} ${l.plaintiff} ${l.defendant} ${l.subject_data}`.toLowerCase();
    return (!q || text.includes(q))
        && (!st || l.status === st)
        && (!co || l.country === co);
  });
  renderTable(filtered);
}

function filterByCountry(c) {
  document.getElementById("country-filter").value = c;
  applyFilters();
}

function renderTable(rows) {
  const tbody = document.getElementById("lawsuit-table");
  document.getElementById("empty-msg").style.display = rows.length ? "none" : "block";
  if (!rows.length) { tbody.innerHTML=""; return; }
  tbody.innerHTML = rows.map(l => `
    <tr onclick="openDetail('${l.id}')">
      <td class="flag">${FLAGS[l.country]||"🌐"}</td>
      <td class="case-name">${l.case_name||"—"}
        <small>${l.plaintiff||""} v. ${l.defendant||""}</small>
      </td>
      <td style="color:var(--muted);font-size:12px">${l.court||l.jurisdiction||"—"}</td>
      <td style="font-size:12px;max-width:160px">${l.subject_data||"—"}</td>
      <td style="font-size:12px;max-width:180px">${l.claims||"—"}</td>
      <td style="font-family:var(--font-mono);font-size:12px">${l.filed_date||"—"}</td>
      <td><span class="badge badge-${l.status||'active'}">${STATUS_LABELS[l.status]||l.status||"active"}</span></td>
    </tr>`).join("");
}

async function openDetail(id) {
  const r = await fetch(`/api/lawsuit/${id}`);
  const d = await r.json();
  document.getElementById("modal-title").textContent = d.case_name || "—";
  const fields = [
    ["원고", d.plaintiff],["피고", d.defendant],
    ["국가", (FLAGS[d.country]||"")+" "+d.country],
    ["법원", d.court],["관할", d.jurisdiction],
    ["사건번호", d.case_number],["제소일", d.filed_date],
    ["대상 데이터", d.subject_data],["소송 원인", d.claims],
    ["상태", STATUS_LABELS[d.status]||d.status],["발견일", d.discovered_at?.slice(0,10)],
    ["요약", d.summary],
  ];
  document.getElementById("modal-body").innerHTML = fields.filter(f=>f[1]).map(([k,v])=>
    `<dt>${k}</dt><dd>${v}</dd>`).join("");

  const srcs = JSON.parse(d.source_urls||"[]");
  if (srcs.length) {
    document.getElementById("modal-body").innerHTML +=
      `<dt>출처</dt><dd>${srcs.map(u=>`<a class="src-link" href="${u}" target="_blank">${u.slice(0,70)}</a>`).join("")}</dd>`;
  }

  const updates = d.updates || [];
  document.getElementById("modal-updates").innerHTML = updates.length ?
    updates.map(u=>`
      <div class="update-item">
        <span class="upd-type">${u.update_type}</span>
        <span class="upd-date">${u.updated_at?.slice(0,10)}</span>
        <div class="upd-desc">${u.description}</div>
        ${u.source_url ? `<a class="src-link" href="${u.source_url}" target="_blank">출처 →</a>` : ""}
      </div>`).join("") :
    `<div style="color:var(--muted);font-size:13px">업데이트 내역 없음</div>`;

  document.getElementById("modal").classList.add("open");
}

function closeModal() {
  document.getElementById("modal").classList.remove("open");
}
document.getElementById("modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeModal();
});

function showView(v) {
  document.getElementById("view-all").style.display = v==="all"?"block":"none";
  document.getElementById("view-updates").style.display = v==="updates"?"block":"none";
  document.querySelectorAll(".nav-item").forEach((el,i)=>el.classList.toggle("active",i===(v==="all"?0:1)));
  if (v==="updates") loadUpdates();
}

async function loadUpdates() {
  const r = await fetch("/api/updates?limit=50");
  const data = await r.json();
  document.getElementById("updates-list").innerHTML = data.updates.length ?
    data.updates.map(u=>`
      <div class="update-item" style="margin-bottom:14px">
        <span class="upd-type">${u.update_type}</span>
        <span class="upd-date">${u.updated_at?.slice(0,16)}</span>
        <div style="font-size:12px;color:var(--muted);margin-top:2px">${u.case_name}</div>
        <div class="upd-desc">${u.description}</div>
        ${u.source_url ? `<a class="src-link" href="${u.source_url}" target="_blank">출처 →</a>` : ""}
      </div>`).join("") :
    `<div class="empty">업데이트 내역 없음</div>`;
}

async function runNow() {
  const btn = document.getElementById("run-btn");
  btn.disabled = true; btn.textContent = "⏳ 검색 중...";
  try {
    await fetch("/api/run", {method:"POST"});
    await new Promise(r=>setTimeout(r,3000));
    await loadData();
    btn.textContent = "✓ 완료";
    setTimeout(()=>{ btn.disabled=false; btn.textContent="▶ 지금 검색 실행"; },3000);
  } catch(e) {
    btn.disabled=false; btn.textContent="▶ 지금 검색 실행";
  }
}

loadData();
setInterval(loadData, 60000); // Auto-refresh every minute
</script>
</body>
</html>
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/lawsuits")
def api_lawsuits():
    conn = get_db()
    rows = conn.execute("SELECT * FROM lawsuits ORDER BY discovered_at DESC").fetchall()
    lawsuits = [dict(r) for r in rows]
    total   = len(lawsuits)
    active  = sum(1 for l in lawsuits if l["status"] == "active")
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    new_week = sum(1 for l in lawsuits if (l.get("discovered_at") or "") >= week_ago)
    last_log = conn.execute("SELECT searched_at FROM search_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return jsonify({
        "lawsuits": lawsuits,
        "stats": {
            "total": total, "active": active, "new_this_week": new_week,
            "last_run": last_log["searched_at"][:16] if last_log else None
        }
    })

@app.route("/api/lawsuit/<lawsuit_id>")
def api_lawsuit(lawsuit_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM lawsuits WHERE id=?", (lawsuit_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    data = dict(row)
    updates = conn.execute(
        "SELECT * FROM updates WHERE lawsuit_id=? ORDER BY updated_at DESC", (lawsuit_id,)
    ).fetchall()
    data["updates"] = [dict(u) for u in updates]
    conn.close()
    return jsonify(data)

@app.route("/api/updates")
def api_updates():
    limit = int(request.args.get("limit", 30))
    conn = get_db()
    rows = conn.execute("""
        SELECT u.*, l.case_name FROM updates u
        JOIN lawsuits l ON l.id = u.lawsuit_id
        ORDER BY u.updated_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify({"updates": [dict(r) for r in rows]})

@app.route("/api/run", methods=["POST"])
def api_run():
    """Trigger manual run (runs in background)"""
    import threading
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from monitor import run_all, init_db
        init_db()
        t = threading.Thread(target=run_all, daemon=True)
        t.start()
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
