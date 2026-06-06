#!/usr/bin/env python3
"""HAB 运维管理 Web 服务器。

提供: 显示服务控制 / 手动刷新 / 日志查看 / 工具统计 / LLM 交互日志。
运行: python3 ops_server.py --port 8080
"""

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

# ── 项目路径 ──
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
OUTPUTS_DIR = os.path.join(_PROJECT_ROOT, "outputs")
INTERACTIONS_DIR = os.path.join(LOG_DIR, "interactions")

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ops_server")

# ── 日志文件路径 ──
LOG_FILES = {
    "lightweight": os.path.join(LOG_DIR, "refresh_lightweight.log"),
    "heavyweight": os.path.join(LOG_DIR, "refresh_heavyweight.log"),
}


# ══════════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════════

def _tail_file(path: str, lines: int = 100) -> str:
    """读取文件末尾 N 行。"""
    if not os.path.exists(path):
        return "(文件不存在)"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception as e:
        return f"(读取失败: {e})"


def _run_cmd(cmd: list[str], timeout: float = 60) -> dict:
    """执行 shell 命令，返回 {ok, stdout, stderr, code}。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip() or "",
            "stderr": r.stderr.strip() or "",
            "code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "命令超时", "code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "code": -1}


def _display_status() -> dict:
    """获取 display server 状态。"""
    r = _run_cmd(["sudo", "systemctl", "is-active", "hab-display"], timeout=5)
    active = r["stdout"] == "active"
    # 获取更详细的状态
    info = {}
    if active:
        r2 = _run_cmd(
            ["sudo", "systemctl", "show", "hab-display",
             "--property=ActiveEnterTimestamp,ActiveState,SubState,MainPID"],
            timeout=5,
        )
        for line in r2["stdout"].split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v
    return {
        "active": active,
        "status": r["stdout"],
        "info": info,
    }


def _journalctl_log(lines: int = 100) -> str:
    """读取 display server 的 journalctl 日志。"""
    r = _run_cmd(
        ["sudo", "journalctl", "-u", "hab-display", "--no-pager",
         "-n", str(lines), "-o", "short-iso"],
        timeout=10,
    )
    return r["stdout"] if r["ok"] else f"(journalctl 失败: {r['stderr']})"


# ══════════════════════════════════════════════════════════════════
#  HTML 模板 (单页，暗色主题，移动端自适应)
# ══════════════════════════════════════════════════════════════════

OPS_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HAB 运维面板</title>
<style>
  :root {
    --bg: #1a1a2e; --card: #16213e; --border: #0f3460;
    --accent: #e94560; --green: #00b894; --yellow: #fdcb6e;
    --text: #dfe6e9; --muted: #636e72;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family: -apple-system, "Segoe UI", sans-serif;
         background: var(--bg); color: var(--text); min-height:100vh; }
  .header { background: var(--card); border-bottom:2px solid var(--accent);
            padding:14px 20px; display:flex; justify-content:space-between;
            align-items:center; flex-wrap:wrap; gap:8px; }
  .header h1 { font-size:1.3em; white-space:nowrap; }
  .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%;
                margin-right:6px; }
  .status-dot.on { background: var(--green); box-shadow:0 0 6px var(--green); }
  .status-dot.off { background: var(--accent); }
  .container { max-width:960px; margin:0 auto; padding:16px; }
  .card { background: var(--card); border:1px solid var(--border);
          border-radius:10px; padding:16px; margin-bottom:14px; }
  .card h2 { font-size:1.05em; margin-bottom:10px; color: var(--yellow); }
  .btn-row { display:flex; flex-wrap:wrap; gap:8px; }
  button { padding:9px 18px; border:none; border-radius:6px;
           font-size:0.9em; cursor:pointer; font-weight:600;
           transition: opacity 0.2s; }
  button:active { opacity:0.7; }
  button:disabled { opacity:0.4; cursor:not-allowed; }
  .btn-start { background:var(--green); color:#000; }
  .btn-stop { background:var(--accent); color:#fff; }
  .btn-restart { background:var(--yellow); color:#000; }
  .btn-refresh { background:#6c5ce7; color:#fff; }
  .btn-heavy { background:#e17055; color:#fff; }
  .log-viewer { background:#0a0a1a; border:1px solid var(--border);
                border-radius:6px; padding:10px; max-height:420px;
                overflow:auto; font-family:"Cascadia Code","Fira Code",monospace;
                font-size:0.78em; line-height:1.5; white-space:pre-wrap;
                word-break:break-all; }
  .tab-bar { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:8px; }
  .tab { padding:6px 14px; background:var(--border); border-radius:5px 5px 0 0;
         cursor:pointer; font-size:0.82em; border:none; color:var(--muted); }
  .tab.active { background:var(--accent); color:#fff; }
  .toast { position:fixed; bottom:20px; right:20px; padding:10px 20px;
           border-radius:8px; font-weight:600; z-index:999; animation:fade 3s forwards; }
  @keyframes fade { 0%,70%{opacity:1} 100%{opacity:0} }
  .toast.ok { background:var(--green); color:#000; }
  .toast.err { background:var(--accent); color:#fff; }
  .stats-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(180px,1fr));
                gap:10px; }
  .stat-item { background:#0a0a1a; padding:10px 14px; border-radius:6px; }
  .stat-item .val { font-size:1.5em; font-weight:700; color:var(--accent); }
  .stat-item .lbl { font-size:0.75em; color:var(--muted); }
  @media (max-width:600px) {
    .header h1 { font-size:1.1em; }
    button { padding:8px 14px; font-size:0.82em; }
  }
</style>
</head>
<body>

<div class="header">
  <h1><span class="status-dot" id="statusDot"></span>HAB 运维</h1>
  <span style="font-size:0.82em;color:var(--muted)" id="clock"></span>
</div>

<div class="container">

<!-- 显示服务控制 -->
<div class="card">
  <h2>🖥️ 显示服务 <span id="dsStatus" style="font-size:0.85em;color:var(--muted)">查询中...</span></h2>
  <div class="btn-row">
    <button class="btn-start" onclick="displayAction('start')">▶ 启动</button>
    <button class="btn-stop" onclick="displayAction('stop')">⏹ 停止</button>
    <button class="btn-restart" onclick="displayAction('restart')">↻ 重启</button>
    <span style="flex:1"></span>
    <button class="btn-refresh" onclick="refreshAction('lightweight')">⚡ 轻量刷新</button>
    <button class="btn-heavy" onclick="refreshAction('heavyweight')">🧠 重量刷新</button>
  </div>
</div>

<!-- 统计 -->
<div class="card">
  <h2>📊 概况 <span id="statsTime" style="font-size:0.8em;color:var(--muted)"></span></h2>
  <div class="stats-grid" id="statsGrid">加载中...</div>
</div>

<!-- 日志 -->
<div class="card">
  <h2>📋 日志 <span style="font-size:0.8em;color:var(--muted)">
    <button class="tab" style="font-size:0.75em;padding:3px 8px" onclick="loadLog('current', true)">↻ 刷新</button>
  </span></h2>
  <div class="tab-bar">
    <button class="tab active" onclick="switchTab('display')">Display Server</button>
    <button class="tab" onclick="switchTab('lightweight')">轻量刷新</button>
    <button class="tab" onclick="switchTab('heavyweight')">重量刷新</button>
    <button class="tab" onclick="switchTab('interactions')">LLM 交互</button>
    <button class="tab" onclick="switchTab('tool_stats')">工具统计</button>
    <button class="tab" onclick="switchTab('preview')">🖵 屏幕预览</button>
  </div>
  <div class="log-viewer" id="logContent">点击 tab 加载日志...</div>
  <div id="previewArea" style="display:none;text-align:center;padding:8px;background:#0a0a1a;border-radius:6px">
    <div style="margin-bottom:6px;color:var(--muted);font-size:0.8em">
      当前屏幕内容 · <button onclick="loadPreview()" style="font-size:0.75em;padding:3px 8px">⟳ 刷新</button>
    </div>
    <img id="previewImg" src="" style="max-width:100%;border:1px solid var(--border);border-radius:4px"
         onerror="this.alt='无预览数据'">
  </div>
</div>

</div>

<script>
let currentTab = 'display';
const DS_SERVICE = 'hab-display';

// ── Toast ──
function toast(msg, ok) {
  const t = document.createElement('div');
  t.className = 'toast ' + (ok ? 'ok' : 'err');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ── 时钟 ──
setInterval(() => {
  document.getElementById('clock').textContent = new Date().toLocaleString('zh-CN');
}, 1000);

// ── 状态轮询 ──
async function pollStatus() {
  try {
    const r = await fetch('/api/display/status');
    const d = await r.json();
    const dot = document.getElementById('statusDot');
    dot.className = 'status-dot ' + (d.active ? 'on' : 'off');
    document.getElementById('dsStatus').textContent =
      d.active ? '● 运行中' : '○ 已停止';
    document.getElementById('statsTime').textContent =
      '  @ ' + new Date().toLocaleTimeString('zh-CN');
  } catch(e) {}
}
pollStatus();
setInterval(pollStatus, 5000);

// ── 加载统计 ──
async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    let html = '';
    for (const [k, v] of Object.entries(d)) {
      html += `<div class="stat-item"><div class="val">${v}</div><div class="lbl">${k}</div></div>`;
    }
    document.getElementById('statsGrid').innerHTML = html;
  } catch(e) {
    document.getElementById('statsGrid').textContent = '加载失败';
  }
}
loadStats();

// ── 显示服务控制 ──
async function displayAction(action) {
  if (!confirm(`确认 ${action} Display Server？`)) return;
  try {
    const r = await fetch(`/api/display/${action}`, {method:'POST'});
    const d = await r.json();
    toast(d.msg || d.error, d.ok);
    pollStatus();
  } catch(e) { toast('请求失败: '+e, false); }
}

// ── 手动刷新 ──
async function refreshAction(type) {
  const label = type === 'heavyweight' ? '重量级刷新 (调用LLM)' : '轻量级刷新';
  if (!confirm(`确认触发 ${label}？`)) return;
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '执行中...';
  try {
    const r = await fetch(`/api/refresh/${type}`, {method:'POST'});
    const d = await r.json();
    toast(d.msg || d.error, d.ok);
    loadStats();
  } catch(e) { toast('请求失败: '+e, false); }
  finally { btn.disabled = false; btn.textContent = type === 'heavyweight' ? '🧠 重量刷新' : '⚡ 轻量刷新'; }
}

// ── 日志切换 ──
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  loadLog(tab);
}

async function loadLog(tab, forceReload) {
  if (!tab || tab === 'current') tab = currentTab || 'display';
  currentTab = tab;
  const logEl = document.getElementById('logContent');
  const previewEl = document.getElementById('previewArea');

  // 切换显示模式
  if (tab === 'preview') {
    logEl.style.display = 'none';
    previewEl.style.display = 'block';
    loadPreview();
    return;
  } else {
    logEl.style.display = 'block';
    previewEl.style.display = 'none';
  }

  logEl.textContent = '加载中...';

  try {
    let url;
    if (tab === 'display') url = '/api/logs/display';
    else if (tab === 'lightweight') url = '/api/logs/lightweight';
    else if (tab === 'heavyweight') url = '/api/logs/heavyweight';
    else if (tab === 'interactions') { url = '/api/interactions'; }
    else if (tab === 'tool_stats') { url = '/api/tool_stats'; }

    const r = await fetch(url + (url.includes('?')?'&':'?') + 't=' + Date.now());
    const ct = r.headers.get('content-type') || '';

    if (ct.includes('application/json')) {
      const d = await r.json();
      if (tab === 'interactions') {
        logEl.innerHTML = renderInteractions(d);
      } else if (tab === 'tool_stats') {
        logEl.innerHTML = renderToolStats(d);
      }
    } else {
      logEl.textContent = await r.text();
      logEl.scrollTop = logEl.scrollHeight;
    }
  } catch(e) {
    logEl.textContent = '加载失败: ' + e;
  }
}

function loadPreview() {
  const img = document.getElementById('previewImg');
  img.src = '/api/preview.png?t=' + Date.now();
}

function renderInteractions(files) {
  if (!files.length) return '<div style="padding:12px;color:var(--muted)">暂无交互日志</div>';
  let html = '<div style="font-size:0.82em">';
  for (const f of files) {
    html += `<div style="padding:6px 0;border-bottom:1px solid var(--border);cursor:pointer"
              onclick="loadInteractionLog('${f.name}')" title="点击查看">
      📄 ${f.name} <span style="color:var(--muted)">${f.size} ${f.time}</span>
    </div>`;
  }
  html += '</div>';
  return html;
}

async function loadInteractionLog(name) {
  const el = document.getElementById('logContent');
  el.textContent = '加载中...';
  try {
    const r = await fetch(`/api/interactions/${encodeURIComponent(name)}`);
    const d = await r.json();
    el.innerHTML = renderInteractionDetail(d);
  } catch(e) { el.textContent = '加载失败: '+e; }
}

function renderInteractionDetail(d) {
  let html = `<div style="font-size:0.82em">
    <div style="margin-bottom:10px">
      <button onclick="switchTab('interactions')" style="font-size:0.8em;padding:4px 10px">← 返回列表</button>
    </div>`;

  for (const round of (d.rounds || [])) {
    const durSec = (round.duration_ms / 1000).toFixed(1);
    let typeLabel = round.type;
    if (round.type === 'round') typeLabel = '🔄 Agent Round';
    else if (round.type === 'fix_retry') typeLabel = '🔧 JSON 修复';
    else if (round.type === 'fallback') typeLabel = '⚠️ 兜底';
    else if (round.type === 'fallback_fix') typeLabel = '🔧 兜底修复';

    html += `<div style="margin-bottom:12px;border:1px solid var(--border);border-radius:6px;overflow:hidden">
      <div style="padding:6px 10px;background:var(--border);color:var(--yellow);font-weight:600;font-size:0.9em">
        Round ${round.round} · ${typeLabel} · ${durSec}s
      </div>`;

    // Reasoning
    if (round.reasoning) {
      html += `<div style="padding:6px 10px;background:#1a1a3e;color:#a29bfe;font-style:italic;font-size:0.85em;max-height:200px;overflow:auto">
        <div style="color:var(--muted);font-size:0.8em;margin-bottom:2px">💭 Thinking:</div>
        ${escapeHtml(round.reasoning)}</div>`;
    }

    // Input messages
    for (const msg of (round.messages || [])) {
      let roleIcon, roleColor;
      switch (msg.role) {
        case 'system': roleIcon='⚙️'; roleColor='#636e72'; break;
        case 'user': roleIcon='👤'; roleColor='#74b9ff'; break;
        case 'assistant': roleIcon='🤖'; roleColor='#00b894'; break;
        case 'tool': roleIcon='🔧'; roleColor='#fdcb6e'; break;
        default: roleIcon='❓'; roleColor='#dfe6e9';
      }
      const content = msg.content || '';
      const preview = content.length > 500 ? content.substring(0,500) + '...' : content;

      html += `<div style="padding:5px 10px;border-bottom:1px solid rgba(255,255,255,0.05)">
        <span style="color:${roleColor};font-weight:600">${roleIcon} ${msg.role}</span>`;
      if (msg.tool_call_id) {
        html += ` <span style="color:var(--muted);font-size:0.8em">← ${msg.tool_call_id}</span>`;
      }
      if (msg.tool_calls) {
        html += '<div style="margin-left:16px;margin-top:3px">';
        for (const tc of msg.tool_calls) {
          const fn = tc.function || {};
          html += `<div style="color:var(--green);font-size:0.9em">→ ${escapeHtml(fn.name || '?')}`;
          if (fn.arguments) {
            html += `<span style="color:var(--muted);font-size:0.85em">(${escapeHtml(String(fn.arguments).substring(0,200))})</span>`;
          }
          html += '</div>';
        }
        html += '</div>';
      }
      if (preview && msg.role !== 'assistant') {
        html += `<div style="margin-left:16px;color:var(--muted);font-size:0.88em;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow:auto">${escapeHtml(preview)}</div>`;
      }
      html += '</div>';
    }

    // Response content (assistant text output without tool calls)
    if (round.content) {
      html += `<div style="padding:5px 10px;background:#0d3320;color:#55efc4;font-size:0.85em;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow:auto">
        <div style="color:var(--muted);font-size:0.75em;margin-bottom:2px">📤 LLM Output:</div>
        ${escapeHtml(round.content)}</div>`;
    }

    // Tool calls from response
    if (round.tool_calls && round.tool_calls.length > 0) {
      html += '<div style="padding:5px 10px;background:#1a1a0a">';
      for (const tc of round.tool_calls) {
        html += `<div style="color:var(--yellow);font-weight:600;margin-top:2px">🔨 ${escapeHtml(tc.name)}</div>`;
        html += `<div style="color:var(--muted);font-size:0.82em;margin-left:16px;white-space:pre-wrap;max-height:200px;overflow:auto">${escapeHtml(tc.arguments)}</div>`;
      }
      html += '</div>';
    }

    html += '</div>';
  }

  if (!d.rounds || !d.rounds.length) {
    html += '<div style="padding:12px;color:var(--muted)">无交互记录</div>';
  }

  html += '</div>';
  return html;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderToolStats(d) {
  if (d.error) return `<div style="color:var(--accent)">${d.error}</div>`;
  let html = '<div class="stats-grid">';
  for (const t of (d.tools || [])) {
    html += `<div class="stat-item">
      <div class="val">${t.count}</div>
      <div class="lbl">${t.name}</div>
      <div style="font-size:0.7em;color:var(--muted)">上次: ${t.last_used}</div>
    </div>`;
  }
  html += '</div>';
  return html;
}

// 初始加载
loadLog('display');
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
#  API 路由
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template_string(OPS_HTML)


# ── 显示服务控制 ──

@app.route("/api/display/status")
def api_display_status():
    s = _display_status()
    return jsonify(s)


@app.route("/api/display/<action>", methods=["POST"])
def api_display_action(action: str):
    if action not in ("start", "stop", "restart"):
        return jsonify({"ok": False, "error": f"未知操作: {action}"})
    r = _run_cmd(["sudo", "systemctl", action, "hab-display"], timeout=30)
    if r["ok"]:
        logger.info("Display server %s: OK", action)
        return jsonify({"ok": True, "msg": f"显示服务 {action} 成功"})
    else:
        logger.warning("Display server %s failed: %s", action, r["stderr"])
        return jsonify({"ok": False, "error": f"{action} 失败: {r['stderr']}"})


# ── 手动刷新 ──

def _trigger_refresh(script: str, log_path: str) -> dict:
    """在后台执行刷新脚本，输出追加到日志文件。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    script_path = os.path.join(_PROJECT_ROOT, script)
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n{'='*50}\n")
            logf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                       f"手动触发 {script}\n")
            logf.flush()
            subprocess.Popen(
                [sys.executable, script_path],
                stdout=logf, stderr=subprocess.STDOUT,
                cwd=_PROJECT_ROOT,
            )
        logger.info("Triggered %s", script)
        return {"ok": True, "msg": f"{script} 已在后台启动，请查看日志"}
    except Exception as e:
        logger.error("Failed to trigger %s: %s", script, e)
        return {"ok": False, "error": str(e)}


@app.route("/api/refresh/<ref_type>", methods=["POST"])
def api_refresh(ref_type: str):
    if ref_type == "lightweight":
        return jsonify(_trigger_refresh(
            "refresh_lightweight.py",
            LOG_FILES["lightweight"],
        ))
    elif ref_type == "heavyweight":
        return jsonify(_trigger_refresh(
            "refresh_heavyweight.py",
            LOG_FILES["heavyweight"],
        ))
    return jsonify({"ok": False, "error": f"未知刷新类型: {ref_type}"})


# ── 日志读取 ──

@app.route("/api/logs/display")
def api_logs_display():
    lines = request.args.get("tail", 100, type=int)
    return _journalctl_log(lines), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/logs/<log_name>")
def api_logs_file(log_name: str):
    if log_name not in LOG_FILES:
        return "(未知日志)", 404, {"Content-Type": "text/plain; charset=utf-8"}
    lines = request.args.get("tail", 200, type=int)
    content = _tail_file(LOG_FILES[log_name], lines)
    return content, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ── 统计 ──

@app.route("/api/stats")
def api_stats():
    stats = {}

    # 输出文件数
    outputs = list(Path(OUTPUTS_DIR).glob("*.json")) if os.path.isdir(OUTPUTS_DIR) else []
    stats["输出文件"] = len(outputs)

    # 交互日志文件数
    int_dir = Path(INTERACTIONS_DIR)
    interactions = list(int_dir.glob("*.jsonl")) if int_dir.is_dir() else []
    stats["LLM交互日志"] = len(interactions)

    # 轻量日志大小
    lw_path = LOG_FILES["lightweight"]
    if os.path.exists(lw_path):
        stats["轻量日志"] = f"{os.path.getsize(lw_path)/1024:.0f}KB"

    # 重量日志大小
    hw_path = LOG_FILES["heavyweight"]
    if os.path.exists(hw_path):
        stats["重量日志"] = f"{os.path.getsize(hw_path)/1024:.0f}KB"

    # 工具调用计数
    try:
        tc_path = os.path.join(_PROJECT_ROOT, "config", "tool_usage.json")
        if os.path.exists(tc_path):
            with open(tc_path, "r", encoding="utf-8") as f:
                tc_data = json.load(f)
            stats["工具总调用"] = sum(tc_data.values()) if isinstance(tc_data, dict) else 0
    except Exception:
        pass

    # 上次重量刷新 token 消耗
    token_info = _last_refresh_tokens()
    if token_info:
        stats["上次Token消耗"] = f"{token_info['total']:,}"
        stats["轮数"] = token_info['rounds']

    return jsonify(stats)


def _last_refresh_tokens() -> dict | None:
    """读取最近一次重量刷新的 LLM 交互日志，汇总 token 消耗。"""
    int_dir = Path(INTERACTIONS_DIR)
    if not int_dir.is_dir():
        return None
    files = sorted(int_dir.glob("*.jsonl"), reverse=True)
    if not files:
        return None
    try:
        total_tokens = 0
        rounds = 0
        with open(files[0], "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = entry.get("usage", {})
                total_tokens += usage.get("total_tokens", 0)
                rounds += 1
        if total_tokens > 0:
            return {"total": total_tokens, "rounds": rounds}
    except Exception:
        pass
    return None


# ── LLM 交互日志 ──

@app.route("/api/interactions")
def api_interactions_list():
    int_dir = Path(INTERACTIONS_DIR)
    if not int_dir.is_dir():
        return jsonify([])
    files = []
    for f in sorted(int_dir.glob("*.jsonl"), reverse=True):
        st = f.stat()
        files.append({
            "name": f.name,
            "size": f"{st.st_size/1024:.1f}KB",
            "time": datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"),
        })
    return jsonify(files[:30])


@app.route("/api/interactions/<filename>")
def api_interactions_detail(filename: str):
    """返回全量 LLM 交互日志（含输入消息、输出、reasoning、工具调用）。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "invalid filename"}), 400
    filepath = os.path.join(INTERACTIONS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "file not found"}), 404

    rounds = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                resp = entry.get("response", {})

                # 工具调用
                tool_calls = []
                for tc in resp.get("tool_calls", []):
                    fn = tc.get("function", {})
                    args_str = str(fn.get("arguments", ""))
                    try:
                        args_parsed = json.loads(args_str)
                        args_str = json.dumps(args_parsed, ensure_ascii=False, indent=2)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "name": fn.get("name", "?"),
                        "arguments": args_str[:2000],
                    })

                # 输入消息（截断过长内容）
                messages = []
                for msg in entry.get("messages", []):
                    content = msg.get("content", "") or ""
                    if isinstance(content, str) and len(content) > 3000:
                        content = content[:3000] + "...[truncated]"
                    messages.append({
                        "role": msg.get("role", "?"),
                        "content": content,
                        "tool_calls": msg.get("tool_calls"),
                        "tool_call_id": msg.get("tool_call_id"),
                        "name": msg.get("name"),
                    })

                # reasoning 可能在 response.reasoning_content 或 entry.reasoning_content
                reasoning = (resp.get("reasoning_content") or
                            entry.get("reasoning_content") or "")

                rounds.append({
                    "round": entry.get("round", "?"),
                    "type": entry.get("type", "?"),
                    "duration_ms": entry.get("duration_ms", 0),
                    "messages": messages,
                    "tool_calls": tool_calls,
                    "content": (resp.get("content") or "")[:2000],
                    "reasoning": reasoning[:3000],
                    "assistant_message": resp.get("assistant_message"),
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"filename": filename, "rounds": rounds})


# ── 工具调用统计 ──

@app.route("/api/tool_stats")
def api_tool_stats():
    tc_path = os.path.join(_PROJECT_ROOT, "config", "tool_usage.json")
    if not os.path.exists(tc_path):
        return jsonify({"error": "tool_usage.json 不存在"})

    try:
        with open(tc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)})

    tools = []
    for name, count in sorted(data.items(), key=lambda x: -x[1]):
        tools.append({
            "name": name,
            "count": count,
            "last_used": "—",
        })
    return jsonify({"tools": tools})


# ── 屏幕预览 ──

@app.route("/api/preview.png")
def api_preview_png():
    """使用 Layout 渲染最新输出为 PNG 预览。"""
    import io

    # 找到最新的输出 JSON
    outputs_dir = Path(OUTPUTS_DIR)
    if not outputs_dir.is_dir():
        return _preview_placeholder("outputs/ 目录不存在")

    json_files = sorted(outputs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return _preview_placeholder("暂无输出数据")

    try:
        with open(json_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _preview_placeholder(f"读取失败: {e}")

    # 注入 refresh_info（如果 output 里没有）
    if "refresh_info" not in data:
        data["refresh_info"] = {"text": "[预览模式]"}

    # 使用 Layout 渲染
    try:
        from lib.display.renderer import create_layout
        from lib.config import load_config

        cfg = load_config()
        disp_cfg = getattr(cfg, 'display', cfg)
        font_dir = os.path.join(_PROJECT_ROOT, "fonts")
        layout = create_layout(font_dir, disp_cfg)
        img = layout.render_full(data)
    except Exception as e:
        # 降级：文字提示（ASCII 安全）
        logger.warning("Layout render failed, fallback: %s", e)
        return _preview_placeholder(f"Render error: {e}")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), 200, {"Content-Type": "image/png"}


def _preview_placeholder(msg: str):
    """生成占位预览图（ASCII 安全，避免 PIL 默认字体中文乱码）。"""
    import io
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("1", (800, 480), 255)
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font = None
    font_dir = os.path.join(_PROJECT_ROOT, "fonts")
    if os.path.isdir(font_dir):
        for f in sorted(os.listdir(font_dir)):
            if f.lower().endswith(('.ttf', '.ttc', '.otf')):
                try:
                    font = ImageFont.truetype(os.path.join(font_dir, f), 18)
                    break
                except Exception:
                    continue
    if font is None:
        # 尝试系统字体
        for sys_path in ['/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
                         '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
            if os.path.exists(sys_path):
                try:
                    font = ImageFont.truetype(sys_path, 18)
                    break
                except Exception:
                    continue

    draw.text((20, 200), msg, fill=0, font=font)
    draw.text((20, 230), "HAB display preview", fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), 200, {"Content-Type": "image/png"}


# ══════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HAB OPS Web Server")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    args = parser.parse_args()

    logger.info("OPS Server starting on %s:%d", args.host, args.port)
    logger.info("Log dir: %s", LOG_DIR)
    logger.info("Project root: %s", _PROJECT_ROOT)

    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
