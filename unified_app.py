#!/usr/bin/env python3
"""
unified_app.py — Single-file launcher for the Ai-main repository.

Drop this file in your Ai-main/ project root and run:
    python unified_app.py

Opens a web dashboard at http://127.0.0.1:7799 with:
  • Dashboard   — project overview & quick stats
  • Terminal    — run clawspring in chat/brainstorm/worker/ssj modes with live output
  • Agents      — view all defined agents and their roles
  • Memory      — browse/search persistent memory files
  • Skills      — list all available built-in & user skills
  • Source      — explore project file tree
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
CLAWSPRING_DIR = ROOT / "clawspring"
CLAWSPRING_PY  = CLAWSPRING_DIR / "clawspring.py"
MEMORY_DIR     = Path.home() / ".clawspring" / "memory"
SKILLS_DIR     = Path.home() / ".clawspring" / "skills"
PROJECT_MEMORY = ROOT / ".clawspring" / "memory"
PROJECT_SKILLS = ROOT / ".clawspring" / "skills"

PORT = 7799

# ─────────────────────────────────────────────────────────────────────────────
# Project metadata
# ─────────────────────────────────────────────────────────────────────────────
SUBPROJECTS = [
    {
        "id": "original-source-code",
        "name": "Original Source Code",
        "lang": "TypeScript",
        "desc": "Raw leaked Claude Code source archive (1,884 files)",
        "icon": "📦",
        "files": 1884,
    },
    {
        "id": "claude-code-source-code",
        "name": "Claude Code Source",
        "lang": "TypeScript",
        "desc": "Decompiled source of Claude Code v2.1.88 + research docs",
        "icon": "🔬",
        "files": 1940,
    },
    {
        "id": "claw-code",
        "name": "Claw Code",
        "lang": "Python",
        "desc": "Clean-room architectural rewrite of Claude Code",
        "icon": "🐾",
        "files": 109,
    },
    {
        "id": "clawspring",
        "name": "ClawSpring",
        "lang": "Python",
        "desc": "Multi-agent rewrite with memory, skills, MCP, voice, cloud save",
        "icon": "🌿",
        "files": 30,
    },
    {
        "id": "memory",
        "name": "Memory Package",
        "lang": "Python",
        "desc": "Persistent file-based memory system with AI consolidation",
        "icon": "🧠",
        "files": 8,
    },
    {
        "id": "skill",
        "name": "Skill Package",
        "lang": "Python",
        "desc": "Built-in & user-defined slash-command skill system",
        "icon": "⚡",
        "files": 5,
    },
]

AGENTS = [
    {"name": "Architect Agent", "role": "Decompose mission into phases and define architecture.",     "icon": "🏗️"},
    {"name": "Coder Agent",     "role": "Implement backend and frontend code.",                        "icon": "💻"},
    {"name": "Motion Agent",    "role": "Build animations and interactive UI choreography.",            "icon": "🎬"},
    {"name": "3D Agent",        "role": "Design high-fidelity 3D scene plans.",                        "icon": "🎮"},
    {"name": "Mobile Agent",    "role": "Manage mobile bridge hooks and automation.",                   "icon": "📱"},
    {"name": "QA Agent",        "role": "Run verification, quality gates, and test coverage.",          "icon": "✅"},
]

MODES = [
    {"id": "chat",       "label": "Chat",       "icon": "💬", "desc": "Interactive REPL chat with Claude"},
    {"id": "brainstorm", "label": "Brainstorm", "icon": "🧩", "desc": "Creative ideation mode (/brainstorm)"},
    {"id": "worker",     "label": "Worker",     "icon": "🔧", "desc": "Background task execution (/worker)"},
    {"id": "ssj",        "label": "SSJ",        "icon": "🚀", "desc": "Speed-run job mode (/ssj)"},
]

BUILTIN_SKILLS = [
    {"name": "commit",  "triggers": ["/commit"],              "desc": "Review staged changes and create a well-structured git commit",       "tools": ["Bash", "Read"]},
    {"name": "review",  "triggers": ["/review", "/review-pr"],"desc": "Review code changes or a PR and give structured feedback",            "tools": ["Bash", "Read", "Grep"]},
]

# ─────────────────────────────────────────────────────────────────────────────
# Process manager (for running clawspring subprocesses)
# ─────────────────────────────────────────────────────────────────────────────
_processes: dict[str, dict] = {}  # pid -> {proc, queue, stdin_queue, thread}
_proc_lock = threading.Lock()


def _stream_output(proc_id: str, proc: subprocess.Popen, q: queue.Queue) -> None:
    """Read stdout/stderr from child process and push to queue."""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            q.put({"type": "stdout", "data": line.rstrip("\n")})
        proc.wait()
        q.put({"type": "exit", "code": proc.returncode})
    except Exception as exc:
        q.put({"type": "error", "data": str(exc)})
    finally:
        with _proc_lock:
            _processes.pop(proc_id, None)


def start_process(mode: str, prompt: str, model: str, accept_all: bool, verbose: bool) -> str:
    """Spawn clawspring and return a process ID."""
    if not CLAWSPRING_PY.exists():
        raise FileNotFoundError(f"clawspring.py not found at {CLAWSPRING_PY}")

    args = [sys.executable, str(CLAWSPRING_PY)]
    if model:
        args += ["--model", model]
    if accept_all:
        args.append("--accept-all")
    if verbose:
        args.append("--verbose")

    if mode == "chat":
        if prompt:
            args += ["-p", prompt]
    elif mode == "brainstorm":
        args += ["-p", f"/brainstorm {prompt}".strip()]
    elif mode == "worker":
        args += ["-p", f"/worker {prompt}".strip()]
    elif mode == "ssj":
        args += ["-p", "/ssj"]

    proc = subprocess.Popen(
        args,
        cwd=str(CLAWSPRING_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    pid = str(uuid.uuid4())[:8]
    q: queue.Queue = queue.Queue(maxsize=2000)

    t = threading.Thread(target=_stream_output, args=(pid, proc, q), daemon=True)
    t.start()

    with _proc_lock:
        _processes[pid] = {"proc": proc, "queue": q, "thread": t, "mode": mode}

    return pid


def send_input(pid: str, text: str) -> bool:
    with _proc_lock:
        entry = _processes.get(pid)
    if not entry:
        return False
    try:
        entry["proc"].stdin.write(text + "\n")
        entry["proc"].stdin.flush()
        return True
    except Exception:
        return False


def kill_process(pid: str) -> bool:
    with _proc_lock:
        entry = _processes.get(pid)
    if not entry:
        return False
    try:
        entry["proc"].terminate()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def list_memory_files() -> list[dict]:
    entries = []
    for d in [MEMORY_DIR, PROJECT_MEMORY]:
        if d.exists():
            for f in sorted(d.glob("*.md")):
                try:
                    content = f.read_text(errors="replace")[:400]
                    entries.append({
                        "name": f.name,
                        "scope": "user" if d == MEMORY_DIR else "project",
                        "size": f.stat().st_size,
                        "preview": content.strip(),
                        "path": str(f),
                    })
                except Exception:
                    pass
    return entries


def list_skills() -> list[dict]:
    skills = list(BUILTIN_SKILLS)
    for d in [PROJECT_SKILLS, SKILLS_DIR]:
        if d.exists():
            for f in sorted(d.glob("*.md")):
                try:
                    text = f.read_text(errors="replace")
                    name = f.stem
                    desc = ""
                    for line in text.splitlines():
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip().strip('"')
                            break
                    skills.append({
                        "name": name,
                        "triggers": [f"/{name}"],
                        "desc": desc or f.name,
                        "tools": [],
                        "source": "user",
                    })
                except Exception:
                    pass
    return skills


def file_tree(root: Path, max_depth: int = 3) -> list[dict]:
    result = []

    def _walk(p: Path, depth: int):
        if depth > max_depth:
            return
        try:
            children = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return
        for child in children[:60]:
            if child.name.startswith(".") or child.name in ("node_modules", "__pycache__", "src.zip"):
                continue
            entry = {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else 0,
                "depth": depth,
                "children": [],
            }
            if child.is_dir():
                _walk(child, depth + 1)
            result.append(entry)

    _walk(root, 0)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Embedded HTML
# ─────────────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AI Dev Hub</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg: #0a0c10;
    --surface: #111318;
    --surface2: #1a1d25;
    --border: #252830;
    --accent: #00e5a0;
    --accent2: #7c6fff;
    --text: #e2e4ec;
    --muted: #666a7a;
    --danger: #ff5470;
    --warn: #ffb547;
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Syne', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }

  body {
    font-family: var(--mono);
    background: var(--bg);
    color: var(--text);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  /* ── Header ── */
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
  }
  .logo {
    font-family: var(--sans);
    font-weight: 800;
    font-size: 18px;
    color: var(--accent);
    letter-spacing: -0.5px;
  }
  .logo span { color: var(--accent2); }
  .badge {
    font-size: 10px;
    background: var(--accent2);
    color: #fff;
    padding: 2px 8px;
    border-radius: 99px;
    font-weight: 600;
    letter-spacing: 1px;
  }
  .header-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 12px;
    color: var(--muted);
  }
  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--accent);
    display: inline-block;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%,100%{opacity:1} 50%{opacity:.4}
  }

  /* ── Layout ── */
  .app {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* ── Sidebar ── */
  nav {
    width: 180px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    background: var(--surface);
    padding: 16px 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 20px;
    cursor: pointer;
    font-size: 13px;
    color: var(--muted);
    transition: all .15s;
    border-left: 2px solid transparent;
    user-select: none;
  }
  .nav-item:hover { color: var(--text); background: var(--surface2); }
  .nav-item.active {
    color: var(--accent);
    border-left-color: var(--accent);
    background: rgba(0,229,160,.05);
  }
  .nav-icon { font-size: 16px; width: 20px; text-align: center; }
  .nav-section {
    font-size: 9px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted);
    padding: 16px 20px 4px;
    font-weight: 600;
  }

  /* ── Main content ── */
  main {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  main::-webkit-scrollbar { width: 4px; }
  main::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .panel { display: none; }
  .panel.active { display: flex; flex-direction: column; gap: 20px; }

  /* ── Section title ── */
  .section-title {
    font-family: var(--sans);
    font-size: 22px;
    font-weight: 800;
    color: var(--text);
  }
  .section-sub {
    font-size: 12px;
    color: var(--muted);
    margin-top: 2px;
  }

  /* ── Cards ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
  }
  .card-title {
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
    font-weight: 600;
  }

  /* ── Grid ── */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; }

  /* ── Subproject cards ── */
  .proj-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    transition: border-color .2s;
  }
  .proj-card:hover { border-color: var(--accent); }
  .proj-icon { font-size: 24px; margin-bottom: 8px; }
  .proj-name { font-family: var(--sans); font-weight: 700; font-size: 14px; margin-bottom: 2px; }
  .proj-lang {
    display: inline-block;
    font-size: 10px;
    padding: 1px 7px;
    border-radius: 99px;
    background: rgba(124,111,255,.2);
    color: var(--accent2);
    margin-bottom: 8px;
  }
  .proj-desc { font-size: 12px; color: var(--muted); line-height: 1.5; }
  .proj-files { font-size: 11px; color: var(--accent); margin-top: 8px; font-weight: 600; }

  /* ── Stat row ── */
  .stats { display: flex; gap: 16px; }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 20px;
    flex: 1;
    text-align: center;
  }
  .stat-val {
    font-family: var(--sans);
    font-size: 28px;
    font-weight: 800;
    color: var(--accent);
  }
  .stat-label { font-size: 11px; color: var(--muted); margin-top: 2px; }

  /* ── Terminal panel ── */
  .term-controls {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: flex-end;
  }
  .field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 140px; }
  .field label { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  input[type=text], select {
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    padding: 8px 10px;
    border-radius: 6px;
    outline: none;
    transition: border-color .15s;
  }
  input[type=text]:focus, select:focus { border-color: var(--accent); }
  select option { background: var(--bg); }

  .check-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
  input[type=checkbox] { accent-color: var(--accent); }

  .btn {
    padding: 9px 18px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 600;
    transition: all .15s;
  }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-primary:hover { filter: brightness(1.1); }
  .btn-danger { background: var(--danger); color: #fff; }
  .btn-danger:hover { filter: brightness(1.1); }
  .btn-ghost {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
  }
  .btn-ghost:hover { border-color: var(--accent); color: var(--accent); }

  .mode-pills { display: flex; gap: 8px; }
  .mode-pill {
    padding: 7px 14px;
    border-radius: 6px;
    border: 1px solid var(--border);
    cursor: pointer;
    font-size: 12px;
    color: var(--muted);
    transition: all .15s;
    user-select: none;
  }
  .mode-pill:hover { border-color: var(--accent); color: var(--text); }
  .mode-pill.sel { background: rgba(0,229,160,.12); border-color: var(--accent); color: var(--accent); }

  .terminal {
    background: #050608;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-size: 12.5px;
    line-height: 1.6;
    display: flex;
    flex-direction: column;
    height: 420px;
  }
  .term-bar {
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    color: var(--muted);
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .term-bar .dot { width:10px; height:10px; border-radius:50%; }
  .term-dot-r { background: #ff5470; }
  .term-dot-y { background: #ffb547; }
  .term-dot-g { background: #00e5a0; }
  .term-output {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .term-output::-webkit-scrollbar { width: 3px; }
  .term-output::-webkit-scrollbar-thumb { background: var(--border); }
  .line-out { color: #c9d1d9; }
  .line-err { color: var(--danger); }
  .line-sys { color: var(--accent); font-style: italic; }
  .line-exit { color: var(--warn); font-weight: 600; }
  .term-input-row {
    border-top: 1px solid var(--border);
    display: flex;
    padding: 8px 12px;
    gap: 8px;
  }
  .term-prompt { color: var(--accent); line-height: 32px; }
  .term-input {
    flex: 1;
    background: transparent;
    border: none;
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    outline: none;
  }

  /* ── Agent cards ── */
  .agent-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
    display: flex;
    gap: 14px;
    align-items: flex-start;
    transition: border-color .2s;
  }
  .agent-card:hover { border-color: var(--accent2); }
  .agent-icon { font-size: 28px; }
  .agent-name { font-family: var(--sans); font-weight: 700; font-size: 14px; margin-bottom: 4px; }
  .agent-role { font-size: 12px; color: var(--muted); line-height: 1.5; }

  /* ── Memory / Skills ── */
  .mem-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
  }
  .mem-name { font-size: 13px; font-weight: 600; margin-bottom: 4px; color: var(--accent); }
  .mem-scope {
    display: inline-block;
    font-size: 9px;
    padding: 1px 6px;
    border-radius: 99px;
    background: rgba(0,229,160,.15);
    color: var(--accent);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .mem-preview { font-size: 11px; color: var(--muted); white-space: pre-wrap; line-height: 1.5; }
  .mem-empty { color: var(--muted); font-size: 13px; padding: 20px; text-align: center; }

  .skill-row {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    display: flex;
    align-items: flex-start;
    gap: 14px;
  }
  .skill-triggers { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  .trigger-tag {
    font-size: 10px;
    background: rgba(124,111,255,.2);
    color: var(--accent2);
    padding: 1px 7px;
    border-radius: 4px;
    font-weight: 600;
  }
  .skill-tools { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .skill-name { font-weight: 700; font-size: 13px; }
  .skill-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }

  /* ── Source tree ── */
  .tree-item {
    padding: 5px 8px;
    font-size: 12px;
    border-radius: 4px;
    cursor: default;
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text);
  }
  .tree-item:hover { background: var(--surface2); }
  .tree-dir { color: var(--accent2); font-weight: 600; }
  .tree-size { margin-left: auto; color: var(--muted); font-size: 11px; }

  /* ── Running procs ── */
  .proc-row {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    padding: 8px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  .proc-id { color: var(--accent); font-weight: 600; }
  .proc-mode { color: var(--muted); }
  .proc-kill { margin-left: auto; }

  /* ── Search ── */
  .search-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .search-row input { flex: 1; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  /* ── Responsive ── */
  @media (max-width: 700px) {
    .grid-3 { grid-template-columns: 1fr; }
    .grid-2 { grid-template-columns: 1fr; }
    nav { width: 56px; }
    .nav-item span { display: none; }
    .nav-section { display: none; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">AI<span>Dev</span>Hub</div>
  <div class="badge">UNIFIED</div>
  <div class="header-right">
    <span class="status-dot"></span>
    <span>Server running</span>
    <span style="color:var(--border)">|</span>
    <span id="clock"></span>
  </div>
</header>

<div class="app">
  <nav>
    <div class="nav-section">Overview</div>
    <div class="nav-item active" onclick="show('dashboard')">
      <span class="nav-icon">📊</span><span>Dashboard</span>
    </div>

    <div class="nav-section">Run</div>
    <div class="nav-item" onclick="show('terminal')">
      <span class="nav-icon">💻</span><span>Terminal</span>
    </div>
    <div class="nav-item" onclick="show('agents')">
      <span class="nav-icon">🤖</span><span>Agents</span>
    </div>

    <div class="nav-section">Data</div>
    <div class="nav-item" onclick="show('memory')">
      <span class="nav-icon">🧠</span><span>Memory</span>
    </div>
    <div class="nav-item" onclick="show('skills')">
      <span class="nav-icon">⚡</span><span>Skills</span>
    </div>

    <div class="nav-section">Explore</div>
    <div class="nav-item" onclick="show('source')">
      <span class="nav-icon">📁</span><span>Source</span>
    </div>
  </nav>

  <main>

    <!-- ── Dashboard ── -->
    <div id="panel-dashboard" class="panel active">
      <div>
        <div class="section-title">Project Dashboard</div>
        <div class="section-sub">Unified view of all Ai-main subprojects</div>
      </div>

      <div class="stats" id="statsRow"></div>

      <div class="card">
        <div class="card-title">Subprojects</div>
        <div class="grid-3" id="projGrid"></div>
      </div>

      <div class="card">
        <div class="card-title">Quick Launch</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap" id="quickLaunch"></div>
      </div>
    </div>

    <!-- ── Terminal ── -->
    <div id="panel-terminal" class="panel">
      <div>
        <div class="section-title">Terminal</div>
        <div class="section-sub">Run ClawSpring in any mode with live output</div>
      </div>

      <div class="term-controls">
        <div class="field">
          <label>Mode</label>
          <div class="mode-pills" id="modePills"></div>
        </div>
        <div class="field" style="flex:2">
          <label>Prompt (optional)</label>
          <input type="text" id="promptInput" placeholder="Enter your task or question…"/>
        </div>
        <div class="field">
          <label>Model</label>
          <input type="text" id="modelInput" placeholder="e.g. claude-opus-4-5"/>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px">
          <div class="check-row">
            <input type="checkbox" id="acceptAll"/>
            <label for="acceptAll">Accept All</label>
          </div>
          <div class="check-row">
            <input type="checkbox" id="verboseMode"/>
            <label for="verboseMode">Verbose</label>
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:flex-end">
          <button class="btn btn-primary" onclick="launchProcess()">▶ Launch</button>
          <button class="btn btn-ghost" onclick="clearTerminal()">Clear</button>
        </div>
      </div>

      <div class="terminal">
        <div class="term-bar">
          <div class="dot term-dot-r"></div>
          <div class="dot term-dot-y"></div>
          <div class="dot term-dot-g"></div>
          <span style="margin-left:8px" id="termStatus">No process running</span>
          <span style="margin-left:auto" id="termPid"></span>
        </div>
        <div class="term-output" id="termOutput"></div>
        <div class="term-input-row">
          <span class="term-prompt">›</span>
          <input class="term-input" id="termInput" placeholder="Type input to running process…" onkeydown="handleTermInput(event)"/>
          <button class="btn btn-ghost" style="padding:4px 10px;font-size:11px" onclick="killProcess()">Kill</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Running Processes</div>
        <div id="procList"><span style="color:var(--muted);font-size:12px">No active processes</span></div>
      </div>
    </div>

    <!-- ── Agents ── -->
    <div id="panel-agents" class="panel">
      <div>
        <div class="section-title">Agent Roster</div>
        <div class="section-sub">6 specialized agents available for multi-agent workflows</div>
      </div>
      <div id="agentGrid"></div>
    </div>

    <!-- ── Memory ── -->
    <div id="panel-memory" class="panel">
      <div>
        <div class="section-title">Memory Files</div>
        <div class="section-sub">Persistent memory stored in ~/.clawspring/memory/</div>
      </div>
      <div class="search-row">
        <input type="text" id="memSearch" placeholder="Search memory…" oninput="filterMemory()"/>
      </div>
      <div id="memList"></div>
    </div>

    <!-- ── Skills ── -->
    <div id="panel-skills" class="panel">
      <div>
        <div class="section-title">Skills</div>
        <div class="section-sub">Built-in and user-defined slash-command skills</div>
      </div>
      <div id="skillList"></div>
    </div>

    <!-- ── Source ── -->
    <div id="panel-source" class="panel">
      <div>
        <div class="section-title">Source Explorer</div>
        <div class="section-sub">Project file tree</div>
      </div>
      <div class="card">
        <div id="fileTree"></div>
      </div>
    </div>

  </main>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let activeMode = 'chat';
let activePid  = null;
let evtSource  = null;
let allMemory  = [];

// ── Navigation ────────────────────────────────────────────────────────────
function show(tab) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('panel-' + tab).classList.add('active');
  event.currentTarget.classList.add('active');
  if (tab === 'memory') loadMemory();
  if (tab === 'skills') loadSkills();
  if (tab === 'source') loadSource();
  if (tab === 'terminal') loadProcs();
}

// ── Clock ─────────────────────────────────────────────────────────────────
function tick() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();
}
setInterval(tick, 1000); tick();

// ── Dashboard ─────────────────────────────────────────────────────────────
const SUBPROJECTS = """ + json.dumps(SUBPROJECTS) + r""";
const MODES = """ + json.dumps(MODES) + r""";

function buildDashboard() {
  // Stats
  const totalFiles = SUBPROJECTS.reduce((a, s) => a + s.files, 0);
  document.getElementById('statsRow').innerHTML = [
    { val: SUBPROJECTS.length, label: 'Subprojects' },
    { val: totalFiles.toLocaleString(), label: 'Total Source Files' },
    { val: MODES.length, label: 'Agent Modes' },
    { val: 6, label: 'Specialized Agents' },
  ].map(s => `<div class="stat"><div class="stat-val">${s.val}</div><div class="stat-label">${s.label}</div></div>`).join('');

  // Projects
  document.getElementById('projGrid').innerHTML = SUBPROJECTS.map(p => `
    <div class="proj-card">
      <div class="proj-icon">${p.icon}</div>
      <div class="proj-name">${p.name}</div>
      <div class="proj-lang">${p.lang}</div>
      <div class="proj-desc">${p.desc}</div>
      <div class="proj-files">${p.files.toLocaleString()} files</div>
    </div>
  `).join('');

  // Quick launch
  document.getElementById('quickLaunch').innerHTML = MODES.map(m => `
    <button class="btn btn-ghost" onclick="quickLaunch('${m.id}')" title="${m.desc}">
      ${m.icon} ${m.label}
    </button>
  `).join('');

  // Mode pills
  document.getElementById('modePills').innerHTML = MODES.map(m => `
    <div class="mode-pill ${m.id === activeMode ? 'sel' : ''}" onclick="selectMode('${m.id}')" title="${m.desc}">
      ${m.icon} ${m.label}
    </div>
  `).join('');
}
buildDashboard();

function quickLaunch(mode) {
  selectMode(mode);
  show('terminal');
  document.querySelector('.nav-item:nth-child(5)').classList.remove('active');
  document.querySelector('#panel-terminal').classList.add('active');
}

// ── Mode selection ─────────────────────────────────────────────────────────
function selectMode(m) {
  activeMode = m;
  document.querySelectorAll('.mode-pill').forEach(p => {
    p.classList.toggle('sel', p.textContent.trim().toLowerCase().includes(m));
  });
}

// ── Agents ────────────────────────────────────────────────────────────────
const AGENTS = """ + json.dumps(AGENTS) + r""";
document.getElementById('agentGrid').innerHTML = AGENTS.map(a => `
  <div class="agent-card">
    <div class="agent-icon">${a.icon}</div>
    <div>
      <div class="agent-name">${a.name}</div>
      <div class="agent-role">${a.role}</div>
    </div>
  </div>
`).join('');

// ── Process launch ─────────────────────────────────────────────────────────
function launchProcess() {
  const prompt = document.getElementById('promptInput').value.trim();
  const model  = document.getElementById('modelInput').value.trim();
  const acceptAll = document.getElementById('acceptAll').checked;
  const verbose   = document.getElementById('verboseMode').checked;

  fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: activeMode, prompt, model, accept_all: acceptAll, verbose }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      activePid = d.pid;
      document.getElementById('termPid').textContent = 'PID: ' + d.pid;
      document.getElementById('termStatus').textContent = activeMode + ' running…';
      clearTerminal(false);
      addTermLine(`▶ Launched ${activeMode} [${d.pid}]`, 'sys');
      startStream(d.pid);
    } else {
      addTermLine('Error: ' + d.error, 'err');
    }
  })
  .catch(e => addTermLine('Launch failed: ' + e.message, 'err'));
}

function startStream(pid) {
  if (evtSource) evtSource.close();
  evtSource = new EventSource('/api/stream/' + pid);
  evtSource.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'stdout') addTermLine(msg.data, 'out');
    if (msg.type === 'error')  addTermLine(msg.data, 'err');
    if (msg.type === 'exit') {
      addTermLine(`\n✓ Process exited with code ${msg.code}`, 'exit');
      document.getElementById('termStatus').textContent = 'Exited (code ' + msg.code + ')';
      evtSource.close();
      activePid = null;
      loadProcs();
    }
  };
  evtSource.onerror = () => {
    evtSource.close();
  };
}

function addTermLine(text, cls = 'out') {
  const out = document.getElementById('termOutput');
  const el = document.createElement('div');
  el.className = 'line-' + cls;
  el.textContent = text;
  out.appendChild(el);
  out.scrollTop = out.scrollHeight;
}

function clearTerminal(resetState = true) {
  document.getElementById('termOutput').innerHTML = '';
  if (resetState) {
    document.getElementById('termStatus').textContent = 'No process running';
    document.getElementById('termPid').textContent = '';
  }
}

function handleTermInput(e) {
  if (e.key === 'Enter' && activePid) {
    const val = document.getElementById('termInput').value;
    fetch('/api/send/' + activePid, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: val }),
    });
    addTermLine('› ' + val, 'sys');
    document.getElementById('termInput').value = '';
  }
}

function killProcess() {
  if (!activePid) return;
  fetch('/api/kill/' + activePid, { method: 'POST' })
    .then(() => { addTermLine('⚠ Process killed', 'exit'); activePid = null; });
}

function loadProcs() {
  fetch('/api/procs')
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('procList');
      if (!d.procs.length) {
        el.innerHTML = '<span style="color:var(--muted);font-size:12px">No active processes</span>';
        return;
      }
      el.innerHTML = d.procs.map(p => `
        <div class="proc-row">
          <span class="proc-id">${p.pid}</span>
          <span class="proc-mode">${p.mode}</span>
          <button class="btn btn-danger proc-kill" style="padding:4px 10px;font-size:11px"
            onclick="fetch('/api/kill/${p.pid}',{method:'POST'}).then(loadProcs)">Kill</button>
        </div>
      `).join('');
    });
}

// ── Memory ────────────────────────────────────────────────────────────────
function loadMemory() {
  fetch('/api/memory')
    .then(r => r.json())
    .then(d => {
      allMemory = d.files;
      renderMemory(allMemory);
    });
}

function renderMemory(files) {
  const el = document.getElementById('memList');
  if (!files.length) {
    el.innerHTML = '<div class="mem-empty">No memory files found.<br><small>Run <code>/memory consolidate</code> in ClawSpring to create entries.</small></div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div class="mem-card">
      <div class="mem-name">${f.name}</div>
      <span class="mem-scope">${f.scope}</span>
      <div class="mem-preview">${escHtml(f.preview)}</div>
    </div>
  `).join('');
}

function filterMemory() {
  const q = document.getElementById('memSearch').value.toLowerCase();
  renderMemory(allMemory.filter(f =>
    f.name.toLowerCase().includes(q) || f.preview.toLowerCase().includes(q)
  ));
}

// ── Skills ────────────────────────────────────────────────────────────────
function loadSkills() {
  fetch('/api/skills')
    .then(r => r.json())
    .then(d => {
      document.getElementById('skillList').innerHTML = d.skills.map(s => `
        <div class="skill-row">
          <div style="flex:1">
            <div class="skill-name">/${s.name}</div>
            <div class="skill-desc">${s.desc}</div>
            <div class="skill-triggers">${(s.triggers||[]).map(t=>`<span class="trigger-tag">${t}</span>`).join('')}</div>
            ${s.tools?.length ? `<div class="skill-tools">Tools: ${s.tools.join(', ')}</div>` : ''}
          </div>
          <span class="mem-scope" style="background:rgba(124,111,255,.15)">${s.source||'builtin'}</span>
        </div>
      `).join('');
    });
}

// ── Source tree ────────────────────────────────────────────────────────────
function loadSource() {
  fetch('/api/files')
    .then(r => r.json())
    .then(d => {
      document.getElementById('fileTree').innerHTML = d.tree.map(item => {
        const indent = item.depth * 16;
        const icon = item.type === 'dir' ? '📂' : '📄';
        const cls  = item.type === 'dir' ? 'tree-dir' : '';
        const size = item.type === 'file' && item.size ? fmtSize(item.size) : '';
        return `<div class="tree-item ${cls}" style="padding-left:${indent + 8}px">
          ${icon} <span>${item.name}</span>
          ${size ? `<span class="tree-size">${size}</span>` : ''}
        </div>`;
      }).join('');
    });
}

// ── Utils ─────────────────────────────────────────────────────────────────
function fmtSize(b) {
  if (b < 1024) return b + 'B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + 'KB';
  return (b/1024/1024).toFixed(1) + 'MB';
}
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Auto-refresh procs every 5s while terminal is open
setInterval(() => {
  if (document.getElementById('panel-terminal').classList.contains('active')) loadProcs();
}, 5000);
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# HTTP Handler
# ─────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress default access log
        pass

    def _send(self, payload: dict | list, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._html(HTML)

        if path == "/api/info":
            return self._send({
                "subprojects": SUBPROJECTS,
                "agents": AGENTS,
                "modes": MODES,
            })

        if path == "/api/agents":
            return self._send({"agents": AGENTS})

        if path == "/api/memory":
            return self._send({"files": list_memory_files()})

        if path == "/api/skills":
            return self._send({"skills": list_skills()})

        if path == "/api/files":
            return self._send({"tree": file_tree(ROOT)})

        if path == "/api/procs":
            with _proc_lock:
                procs = [{"pid": pid, "mode": v["mode"]} for pid, v in _processes.items()]
            return self._send({"procs": procs})

        if path.startswith("/api/stream/"):
            pid = path.split("/")[-1]
            return self._sse_stream(pid)

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            body = self._read_body()
            try:
                pid = start_process(
                    mode       = body.get("mode", "chat"),
                    prompt     = body.get("prompt", ""),
                    model      = body.get("model", ""),
                    accept_all = body.get("accept_all", False),
                    verbose    = body.get("verbose", False),
                )
                return self._send({"ok": True, "pid": pid})
            except FileNotFoundError as e:
                return self._send({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                return self._send({"ok": False, "error": str(e)}, 500)

        if path.startswith("/api/send/"):
            pid = path.split("/")[-1]
            body = self._read_body()
            ok = send_input(pid, body.get("text", ""))
            return self._send({"ok": ok})

        if path.startswith("/api/kill/"):
            pid = path.split("/")[-1]
            ok = kill_process(pid)
            return self._send({"ok": ok})

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _sse_stream(self, pid: str):
        with _proc_lock:
            entry = _processes.get(pid)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if not entry:
            # Process already done or not found
            self._sse_write({"type": "exit", "code": -1})
            return

        q = entry["queue"]
        while True:
            try:
                msg = q.get(timeout=30)
                self._sse_write(msg)
                if msg["type"] in ("exit", "error"):
                    break
            except queue.Empty:
                # Send keepalive
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    break

    def _sse_write(self, payload: dict):
        data = f"data: {json.dumps(payload)}\n\n".encode()
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    url = f"http://127.0.0.1:{PORT}"
    print(f"""
╔══════════════════════════════════════════════════╗
║           AI Dev Hub — Unified App               ║
╠══════════════════════════════════════════════════╣
║  Dashboard  →  {url:<33}║
║                                                  ║
║  Subprojects: {len(SUBPROJECTS):<35}║
║  Agents:      {len(AGENTS):<35}║
║  Modes:       {', '.join(m['id'] for m in MODES):<35}║
║                                                  ║
║  Press Ctrl+C to stop                            ║
╚══════════════════════════════════════════════════╝
""")

    # Sanity check for clawspring
    if not CLAWSPRING_PY.exists():
        print(f"⚠  Warning: {CLAWSPRING_PY} not found.")
        print("   Terminal launch will fail. Make sure you run this from Ai-main/\n")

    # Open browser after a short delay
    def _open():
        time.sleep(1.2)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
        server.shutdown()


if __name__ == "__main__":
    main()
