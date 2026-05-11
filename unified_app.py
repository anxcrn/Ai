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
    {"id": "webforge",   "label": "WebForge AI", "icon": "🏗️", "desc": "Multi-agent website builder"},
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
elif mode == "webforge":
    args = [sys.executable, "multi_agent_chat.py"]
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
  .skill-triggers { display: flex; gap: 6px; flex-wrap: w