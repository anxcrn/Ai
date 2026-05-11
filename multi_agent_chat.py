#!/usr/bin/env python3
"""
multi_agent_chat.py  —  Multi-Agent Website Builder

Drop this file anywhere and run:
    python multi_agent_chat.py

Opens http://127.0.0.1:7800
Type a website idea → all 6 agents automatically chain together to build it.
Requires: ANTHROPIC_API_KEY environment variable.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

PORT  = 7800
MODEL = "claude-sonnet-4-20250514"
API   = "https://api.anthropic.com/v1/messages"

# ─────────────────────────────────────────────────────────────────────────────
# Agent definitions — each has a focused system prompt
# ─────────────────────────────────────────────────────────────────────────────
AGENTS = [
    {
        "id":    "architect",
        "name":  "Architect Agent",
        "icon":  "🏗️",
        "color": "#7c6fff",
        "label": "Planning structure & layout…",
        "system": """You are the Architect Agent in a multi-agent website-building pipeline.

Your job: analyse the user's website request and produce a detailed TECHNICAL PLAN.

Output format (use these exact headings):
## Purpose & Audience
## Pages & Sections  (list every section with one-line description)
## Design Tokens     (primary color, accent, background, font choices)
## Component Inventory  (navbar, hero, cards, footer, etc.)
## Interactions & Features
## File Strategy     (single HTML file with embedded CSS + JS)

Be specific. The Coder Agent will implement your plan exactly. No code yet — plan only.""",
    },
    {
        "id":    "coder",
        "name":  "Coder Agent",
        "icon":  "💻",
        "color": "#00e5a0",
        "label": "Writing HTML, CSS & JavaScript…",
        "system": """You are the Coder Agent. The Architect Agent has produced a plan. Implement it fully.

Rules:
- Output ONE complete HTML file (all CSS in <style>, all JS in <script>)
- Use CSS custom properties (variables) for the design tokens
- Use semantic HTML5 elements
- Every section from the plan must be present
- Real placeholder text (not Lorem Ipsum) that matches the site's purpose
- Smooth scroll behaviour, working nav links
- No external dependencies — pure HTML/CSS/JS only

Output ONLY the HTML file, starting with <!DOCTYPE html>. No explanation before or after.""",
    },
    {
        "id":    "motion",
        "name":  "Motion Agent",
        "icon":  "🎬",
        "color": "#ff9f47",
        "label": "Adding animations & transitions…",
        "system": """You are the Motion Agent. You receive a working website and add polished motion design.

Add ALL of the following:
1. Scroll-reveal animations using IntersectionObserver (fade + slide in)
2. Hover states on every interactive element (buttons, cards, nav links)
3. Page-load entrance animations (hero text, nav items stagger)
4. Smooth CSS transitions on color/transform changes (0.2–0.4s ease)
5. At least one "wow" moment — e.g. a hero element that scales or shifts on load

Rules:
- Use only CSS animations + vanilla JS IntersectionObserver
- Never break existing layout or functionality
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "3d",
        "name":  "3D Agent",
        "icon":  "🎮",
        "color": "#ff5470",
        "label": "Adding depth & 3D effects…",
        "system": """You are the 3D Agent. Add depth, dimension, and visual sophistication.

Add ALL of the following:
1. Card tilt effect on hover using CSS perspective + JS mouse tracking (subtle, 8–12deg)
2. Layered box-shadows that simulate elevation (3 depth levels)
3. Glassmorphism on at least one element (backdrop-filter: blur + semi-transparent bg)
4. Parallax scrolling on hero background using JS scroll listener
5. CSS 3D transform on a decorative element (rotate3d, translateZ)

Rules:
- Pure CSS + vanilla JS only
- Never break existing layout, animations, or responsiveness
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "mobile",
        "name":  "Mobile Agent",
        "icon":  "📱",
        "color": "#47c8ff",
        "label": "Making it fully responsive…",
        "system": """You are the Mobile Agent. Make the site flawless on every screen size.

Do ALL of the following:
1. Mobile-first media queries at 768px and 480px breakpoints
2. Hamburger menu that toggles mobile nav (with smooth open/close animation)
3. All text readable without zoom (min 16px body, fluid headings with clamp())
4. Touch targets ≥ 44px (buttons, links, nav items)
5. Grid/Flex layouts that stack correctly on small screens
6. No horizontal overflow on any screen width
7. Proper <meta name="viewport"> tag

Rules:
- Never break desktop layout
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "qa",
        "name":  "QA Agent",
        "icon":  "✅",
        "color": "#a8ff78",
        "label": "Final review & polish…",
        "system": """You are the QA Agent — the last step. Deliver the production-ready website.

Review and fix:
1. Any broken layout, overflow, or z-index issues
2. Accessibility: alt text, aria-labels, focus rings, color contrast
3. SEO: <title>, <meta description>, Open Graph tags, canonical URL placeholder
4. Performance: remove any duplicate CSS rules or unused JS
5. Cross-browser safety: replace any cutting-edge CSS that needs prefixes
6. Consistency: uniform spacing, font sizes match the design token scale
7. Final polish: any rough edges in design, copy, or interactions

Output the FINAL, COMPLETE, PRODUCTION-READY HTML file starting with <!DOCTYPE html>.
This is the file the user will download. Make it perfect. No explanation before or after.""",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Session store
# ─────────────────────────────────────────────────────────────────────────────
# sid → {"queue": Queue, "final_html": str | None, "done": bool, "error": str | None}
_sessions: dict[str, dict] = {}
_sess_lock = threading.Lock()

def new_session() -> str:
    sid = uuid.uuid4().hex[:10]
    with _sess_lock:
        _sessions[sid] = {
            "queue":      queue.Queue(maxsize=4000),
            "final_html": None,
            "done":       False,
            "error":      None,
        }
    return sid

def push(sid: str, event: dict) -> None:
    with _sess_lock:
        sess = _sessions.get(sid)
    if sess:
        try:
            sess["queue"].put_nowait(event)
        except queue.Full:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# Claude streaming API call
# ─────────────────────────────────────────────────────────────────────────────
def stream_claude(system: str, messages: list[dict], sid: str, agent: dict) -> str:
    """
    Stream a Claude response. Pushes token events to the session queue.
    Returns the full text of the response.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Export it before running.")

    body = json.dumps({
        "model":      MODEL,
        "max_tokens": 8192,
        "stream":     True,
        "system":     system,
        "messages":   messages,
    }).encode()

    req = Request(
        API,
        data=body,
        headers={
            "Content-Type":    "application/json",
            "x-api-key":       api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    full_text = ""
    with urlopen(req, timeout=180) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                evt = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if evt.get("type") == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    token = delta.get("text", "")
                    full_text += token
                    push(sid, {"type": "token", "text": token, "agent_id": agent["id"]})

    return full_text


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner
# ─────────────────────────────────────────────────────────────────────────────
def extract_html(text: str) -> str:
    """Pull out HTML from a code fence or raw output."""
    # Try fenced code block first
    m = re.search(r"```(?:html)?\s*(<!DOCTYPE.*?</html>)\s*```", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    # Try raw HTML
    m = re.search(r"(<!DOCTYPE\s+html.*?</html>)", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    return text.strip()


def run_pipeline(sid: str, user_request: str) -> None:
    """Run all agents in sequence, streaming tokens to the session queue."""
    try:
        outputs: dict[str, str] = {}   # agent_id → full text output
        current_html = ""              # latest HTML artifact passed between code agents

        for idx, agent in enumerate(AGENTS):
            # ── Announce agent start ──────────────────────────────────────
            push(sid, {
                "type":        "agent_start",
                "agent_id":    agent["id"],
                "agent_name":  agent["name"],
                "agent_icon":  agent["icon"],
                "agent_color": agent["color"],
                "agent_label": agent["label"],
                "step":        idx + 1,
                "total":       len(AGENTS),
            })

            # ── Build message for this agent ──────────────────────────────
            if agent["id"] == "architect":
                # First agent: just the user request
                messages = [{"role": "user", "content": f"Build me this website:\n\n{user_request}"}]

            elif agent["id"] == "coder":
                # Coder gets architect's plan
                arch_plan = outputs.get("architect", "")
                messages = [{
                    "role": "user",
                    "content": (
                        f"Original request:\n{user_request}\n\n"
                        f"Architect's plan:\n{arch_plan}\n\n"
                        "Now implement this plan as a complete single-file HTML website."
                    ),
                }]

            else:
                # All later agents get the running HTML + context
                messages = [{
                    "role": "user",
                    "content": (
                        f"Original request:\n{user_request}\n\n"
                        f"Current website code:\n\n```html\n{current_html}\n```\n\n"
                        f"Your task ({agent['name']}): {agent['label']}"
                    ),
                }]

            # ── Stream the response ────────────────────────────────────────
            full_output = stream_claude(agent["system"], messages, sid, agent)
            outputs[agent["id"]] = full_output

            # Update the running HTML artifact for code-producing agents
            if agent["id"] in ("coder", "motion", "3d", "mobile", "qa"):
                extracted = extract_html(full_output)
                if extracted:
                    current_html = extracted

            # ── Announce agent done ───────────────────────────────────────
            push(sid, {"type": "agent_done", "agent_id": agent["id"]})

        # ── Pipeline complete ─────────────────────────────────────────────
        final_html = current_html or extract_html(outputs.get("qa", ""))
        with _sess_lock:
            sess = _sessions.get(sid)
            if sess:
                sess["final_html"] = final_html
                sess["done"] = True

        push(sid, {
            "type":         "pipeline_done",
            "has_download": bool(final_html),
        })

    except Exception as exc:
        err = str(exc)
        with _sess_lock:
            sess = _sessions.get(sid)
            if sess:
                sess["error"] = err
                sess["done"]  = True
        push(sid, {"type": "error", "message": err})


# ─────────────────────────────────────────────────────────────────────────────
# Embedded HTML dashboard
# ─────────────────────────────────────────────────────────────────────────────
_AGENTS_JSON = json.dumps([
    {"id": a["id"], "name": a["name"], "icon": a["icon"], "color": a["color"], "label": a["label"]}
    for a in AGENTS
])

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Multi-Agent Website Builder</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;600&family=Clash+Display:wght@500;700&display=swap');

:root{
  --bg:#07090f;
  --surface:#0f1117;
  --surface2:#161920;
  --border:#1e2130;
  --text:#dde2f0;
  --muted:#5a5f75;
  --accent:#00e5a0;
  --mono:'IBM Plex Mono',monospace;
  --display:'Clash Display',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:var(--mono);background:var(--bg);color:var(--text);display:flex;flex-direction:column}

/* Header */
header{
  padding:14px 28px;
  border-bottom:1px solid var(--border);
  background:var(--surface);
  display:flex;align-items:center;gap:14px;
  flex-shrink:0;
}
.logo{font-family:var(--display);font-size:19px;font-weight:700;color:var(--accent);letter-spacing:-0.5px}
.logo em{color:#7c6fff;font-style:normal}
.tagline{font-size:11px;color:var(--muted)}
.api-status{margin-left:auto;font-size:11px;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex-shrink:0}
.dot.bad{background:#ff5470}
.dot.warn{background:#ffb547}

/* Layout */
.layout{display:flex;flex:1;overflow:hidden}

/* Pipeline sidebar */
.sidebar{
  width:220px;flex-shrink:0;
  border-right:1px solid var(--border);
  background:var(--surface);
  padding:20px 0;
  display:flex;flex-direction:column;gap:2px;
  overflow-y:auto;
}
.sidebar-title{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);padding:0 18px 10px;font-weight:600}
.agent-step{
  padding:11px 18px;
  display:flex;align-items:flex-start;gap:10px;
  border-left:2px solid transparent;
  transition:all .2s;
  position:relative;
}
.agent-step.waiting{opacity:.35}
.agent-step.active{border-left-color:var(--step-color,var(--accent));background:rgba(0,229,160,.04)}
.agent-step.done{opacity:.7}
.agent-step.done .step-icon{filter:grayscale(0)}
.step-icon{font-size:18px;flex-shrink:0;margin-top:1px}
.step-info{flex:1;min-width:0}
.step-name{font-size:12px;font-weight:600;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.step-status{font-size:10px;color:var(--muted)}
.step-num{
  position:absolute;right:12px;top:12px;
  font-size:10px;color:var(--muted);
  background:var(--surface2);
  padding:1px 5px;border-radius:4px;
}
.check{display:none;color:var(--accent);font-size:12px;margin-left:auto;margin-top:2px}
.agent-step.done .check{display:block}
.spinner{
  width:12px;height:12px;
  border:1.5px solid var(--step-color,var(--accent));
  border-top-color:transparent;
  border-radius:50%;
  animation:spin .7s linear infinite;
  flex-shrink:0;
  margin-top:3px;
  display:none;
}
.agent-step.active .spinner{display:block}
@keyframes spin{to{transform:rotate(360deg)}}

.sidebar-footer{margin-top:auto;padding:16px 18px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}

/* Main chat area */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* Messages */
.messages{
  flex:1;overflow-y:auto;
  padding:24px 28px;
  display:flex;flex-direction:column;gap:16px;
}
.messages::-webkit-scrollbar{width:4px}
.messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

.msg{display:flex;gap:12px;max-width:100%;animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.user{justify-content:flex-end}
.msg-avatar{
  width:32px;height:32px;border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-size:16px;flex-shrink:0;
  border:1px solid var(--border);
}
.msg-body{max-width:72%;display:flex;flex-direction:column;gap:6px}
.msg-header{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted)}
.msg-name{font-weight:600}
.agent-badge{
  font-size:9px;padding:1px 6px;border-radius:4px;
  text-transform:uppercase;letter-spacing:1px;font-weight:600;
}
.msg-bubble{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:10px;
  padding:12px 16px;
  font-size:13px;line-height:1.65;
  white-space:pre-wrap;word-break:break-word;
}
.msg.user .msg-bubble{
  background:rgba(0,229,160,.08);
  border-color:rgba(0,229,160,.2);
  text-align:right;
}

/* Code blocks in messages */
.code-block{
  background:#050608;
  border:1px solid var(--border);
  border-radius:8px;
  overflow:hidden;
  margin:8px 0;
  font-size:11.5px;
}
.code-bar{
  display:flex;align-items:center;justify-content:space-between;
  padding:6px 12px;
  border-bottom:1px solid var(--border);
  font-size:10px;color:var(--muted);
}
.code-pre{padding:12px;overflow-x:auto;color:#a8c0ff;line-height:1.6;max-height:320px;overflow-y:auto}
.copy-btn{
  background:transparent;border:1px solid var(--border);
  color:var(--muted);font-family:var(--mono);font-size:10px;
  padding:2px 8px;border-radius:4px;cursor:pointer;transition:all .15s;
}
.copy-btn:hover{border-color:var(--accent);color:var(--accent)}

/* Thinking indicator */
.thinking-msg .msg-bubble{
  display:flex;gap:6px;align-items:center;
  color:var(--muted);font-size:12px;
  padding:10px 16px;
}
.think-dots span{
  display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--muted);animation:blink 1.2s infinite;
}
.think-dots span:nth-child(2){animation-delay:.2s}
.think-dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}

/* Download banner */
.download-banner{
  margin:8px 28px;padding:14px 18px;
  background:rgba(0,229,160,.06);
  border:1px solid rgba(0,229,160,.25);
  border-radius:10px;
  display:none;
  align-items:center;gap:12px;
  font-size:13px;
}
.download-banner.show{display:flex}
.dl-text{flex:1}
.dl-title{font-weight:600;color:var(--accent)}
.dl-sub{font-size:11px;color:var(--muted);margin-top:2px}
.btn{
  padding:9px 18px;border-radius:7px;border:none;cursor:pointer;
  font-family:var(--mono);font-size:13px;font-weight:600;transition:all .15s;
}
.btn-primary{background:var(--accent);color:#000}
.btn-primary:hover{filter:brightness(1.1)}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn:disabled{opacity:.4;cursor:not-allowed;filter:none}

/* Input row */
.input-area{
  border-top:1px solid var(--border);
  padding:16px 28px;
  background:var(--surface);
  flex-shrink:0;
}
.input-row{display:flex;gap:10px;align-items:flex-end}
.input-wrap{
  flex:1;background:var(--bg);
  border:1px solid var(--border);
  border-radius:10px;
  padding:10px 14px;
  transition:border-color .15s;
  display:flex;align-items:flex-end;gap:8px;
}
.input-wrap:focus-within{border-color:var(--accent)}
textarea{
  flex:1;background:transparent;border:none;
  color:var(--text);font-family:var(--mono);font-size:13px;
  outline:none;resize:none;max-height:120px;line-height:1.5;
  min-height:20px;
}
.input-hint{font-size:10px;color:var(--muted);margin-top:6px}

/* Empty state */
.empty-state{
  flex:1;display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:12px;color:var(--muted);text-align:center;
  padding:40px;
}
.empty-icon{font-size:48px;opacity:.4}
.empty-title{font-family:var(--display);font-size:20px;font-weight:700;color:var(--text);opacity:.6}
.empty-sub{font-size:12px;line-height:1.7;max-width:360px}
.examples{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:8px}
.example-pill{
  padding:7px 14px;border-radius:7px;
  border:1px solid var(--border);font-size:12px;
  cursor:pointer;transition:all .15s;color:var(--muted);
}
.example-pill:hover{border-color:var(--accent);color:var(--accent);background:rgba(0,229,160,.04)}

/* Error state */
.error-msg .msg-bubble{
  border-color:rgba(255,84,112,.3);
  background:rgba(255,84,112,.05);
  color:#ff8fa3;
}

@media(max-width:640px){
  .sidebar{display:none}
  .messages{padding:16px}
  .input-area{padding:12px 16px}
}
</style>
</head>
<body>

<header>
  <div>
    <div class="logo">Web<em>Forge</em> AI</div>
    <div class="tagline">6 agents · fully automatic</div>
  </div>
  <div class="api-status" id="apiStatus">
    <div class="dot warn" id="apiDot"></div>
    <span id="apiText">Checking API key…</span>
  </div>
</header>

<div class="layout">

  <!-- Pipeline sidebar -->
  <aside class="sidebar">
    <div class="sidebar-title">Agent Pipeline</div>
    <div id="agentSteps"></div>
    <div class="sidebar-footer" id="pipelineStatus">Waiting for input…</div>
  </aside>

  <!-- Chat -->
  <div class="main">
    <div class="messages" id="messages">
      <div class="empty-state" id="emptyState">
        <div class="empty-icon">🏗️</div>
        <div class="empty-title">What shall we build?</div>
        <div class="empty-sub">Describe your website and all 6 agents will work together automatically to design, code, animate, and polish it.</div>
        <div class="examples">
          <div class="example-pill" onclick="setPrompt(this)">Portfolio for a photographer</div>
          <div class="example-pill" onclick="setPrompt(this)">SaaS landing page for a task app</div>
          <div class="example-pill" onclick="setPrompt(this)">Restaurant website with menu</div>
          <div class="example-pill" onclick="setPrompt(this)">Personal blog with dark theme</div>
          <div class="example-pill" onclick="setPrompt(this)">Startup landing page with pricing</div>
        </div>
      </div>
    </div>

    <div class="download-banner" id="downloadBanner">
      <div>✨</div>
      <div class="dl-text">
        <div class="dl-title">Your website is ready!</div>
        <div class="dl-sub">All 6 agents finished. Download the complete HTML file.</div>
      </div>
      <button class="btn btn-primary" onclick="downloadSite()">⬇ Download HTML</button>
      <button class="btn btn-ghost" onclick="previewSite()">👁 Preview</button>
    </div>

    <div class="input-area">
      <div class="input-row">
        <div class="input-wrap">
          <textarea id="promptInput" rows="1" placeholder="Describe your website…"
            oninput="autoResize(this)" onkeydown="handleKey(event)"></textarea>
        </div>
        <button class="btn btn-primary" id="sendBtn" onclick="sendMessage()">Build ↗</button>
      </div>
      <div class="input-hint">Press Enter to send · Shift+Enter for new line · All agents run automatically</div>
    </div>
  </div>

</div>

<script>
const AGENTS = """ + _AGENTS_JSON + r""";

// ── State ──────────────────────────────────────────────────────────────────
let activeSid       = null;
let evtSource       = null;
let currentAgentId  = null;
let currentBubble   = null;   // the live DOM element being streamed into
let currentText     = "";     // accumulated text for current agent
let finalHtml       = "";
let busy            = false;

// ── Init sidebar ──────────────────────────────────────────────────────────
function buildSidebar() {
  const container = document.getElementById('agentSteps');
  container.innerHTML = AGENTS.map((a, i) => `
    <div class="agent-step waiting" id="step-${a.id}" style="--step-color:${a.color}">
      <div class="step-icon">${a.icon}</div>
      <div class="step-info">
        <div class="step-name">${a.name}</div>
        <div class="step-status" id="stepStatus-${a.id}">Waiting…</div>
      </div>
      <div class="spinner"></div>
      <div class="check">✓</div>
    </div>
  `).join('');
}
buildSidebar();

// ── API key check ─────────────────────────────────────────────────────────
fetch('/api/health').then(r => r.json()).then(d => {
  const dot  = document.getElementById('apiDot');
  const text = document.getElementById('apiText');
  if (d.api_key_set) {
    dot.className  = 'dot';
    text.textContent = 'API key ✓ · ' + d.model;
  } else {
    dot.className  = 'dot bad';
    text.textContent = 'No ANTHROPIC_API_KEY set!';
  }
}).catch(() => {});

// ── Example prompts ───────────────────────────────────────────────────────
function setPrompt(el) {
  document.getElementById('promptInput').value = el.textContent;
  autoResize(document.getElementById('promptInput'));
  document.getElementById('promptInput').focus();
}

// ── Textarea auto-resize ──────────────────────────────────────────────────
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

// ── Send message ──────────────────────────────────────────────────────────
function sendMessage() {
  if (busy) return;
  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) return;

  // Clear UI
  document.getElementById('emptyState')?.remove();
  document.getElementById('downloadBanner').classList.remove('show');
  document.getElementById('promptInput').value = '';
  autoResize(document.getElementById('promptInput'));
  finalHtml = '';

  // Reset sidebar
  buildSidebar();
  document.getElementById('pipelineStatus').textContent = 'Pipeline starting…';

  // Show user message
  appendUserMsg(prompt);

  setBusy(true);

  fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      activeSid = d.sid;
      openStream(d.sid);
    } else {
      appendError(d.error || 'Failed to start pipeline');
      setBusy(false);
    }
  })
  .catch(e => { appendError(e.message); setBusy(false); });
}

// ── SSE stream ────────────────────────────────────────────────────────────
function openStream(sid) {
  if (evtSource) evtSource.close();
  evtSource = new EventSource('/api/stream/' + sid);

  evtSource.onmessage = e => {
    const msg = JSON.parse(e.data);

    if (msg.type === 'agent_start') {
      finalizeCurrentAgent();
      startAgentBubble(msg);
    }
    else if (msg.type === 'token') {
      appendToken(msg.text);
    }
    else if (msg.type === 'agent_done') {
      finalizeCurrentAgent();
      markAgentDone(msg.agent_id);
    }
    else if (msg.type === 'pipeline_done') {
      evtSource.close();
      onPipelineDone(msg);
    }
    else if (msg.type === 'error') {
      evtSource.close();
      finalizeCurrentAgent();
      appendError(msg.message);
      setBusy(false);
      document.getElementById('pipelineStatus').textContent = 'Error occurred';
    }
  };

  evtSource.onerror = () => {
    evtSource.close();
    setBusy(false);
  };
}

// ── Agent bubble management ───────────────────────────────────────────────
function startAgentBubble(msg) {
  const agent = AGENTS.find(a => a.id === msg.agent_id);
  currentAgentId = msg.agent_id;
  currentText    = "";

  // Update sidebar
  const step = document.getElementById('step-' + msg.agent_id);
  if (step) {
    step.className = 'agent-step active';
    document.getElementById('stepStatus-' + msg.agent_id).textContent = msg.agent_label;
  }
  document.getElementById('pipelineStatus').textContent =
    `Step ${msg.step}/${msg.total} · ${msg.agent_name}`;

  // Show thinking indicator then replace with bubble
  const thinkId = 'think-' + msg.agent_id;
  const thinkEl = document.createElement('div');
  thinkEl.className = 'msg thinking-msg';
  thinkEl.id = thinkId;
  thinkEl.innerHTML = `
    <div class="msg-avatar" style="background:${msg.agent_color}22;border-color:${msg.agent_color}44">${msg.agent_icon}</div>
    <div class="msg-body">
      <div class="msg-header">
        <span class="msg-name" style="color:${msg.agent_color}">${msg.agent_name}</span>
        <span class="agent-badge" style="background:${msg.agent_color}22;color:${msg.agent_color}">${msg.agent_id}</span>
      </div>
      <div class="msg-bubble">
        <div class="think-dots"><span></span><span></span><span></span></div>
        <span>Working…</span>
      </div>
    </div>`;
  document.getElementById('messages').appendChild(thinkEl);
  scrollToBottom();

  // Create the real streaming bubble (hidden until first token)
  const msgEl = document.createElement('div');
  msgEl.className = 'msg';
  msgEl.id = 'msg-' + msg.agent_id;
  msgEl.style.display = 'none';
  msgEl.innerHTML = `
    <div class="msg-avatar" style="background:${msg.agent_color}22;border-color:${msg.agent_color}44">${msg.agent_icon}</div>
    <div class="msg-body">
      <div class="msg-header">
        <span class="msg-name" style="color:${msg.agent_color}">${msg.agent_name}</span>
        <span class="agent-badge" style="background:${msg.agent_color}22;color:${msg.agent_color}">${msg.agent_id}</span>
      </div>
      <div class="msg-bubble" id="bubble-${msg.agent_id}"></div>
    </div>`;
  document.getElementById('messages').appendChild(msgEl);
  currentBubble = document.getElementById('bubble-' + msg.agent_id);
}

function appendToken(text) {
  if (!currentBubble) return;
  currentText += text;

  // Hide thinking indicator once first token arrives
  const thinkEl = document.getElementById('think-' + currentAgentId);
  if (thinkEl) thinkEl.style.display = 'none';
  const msgEl = document.getElementById('msg-' + currentAgentId);
  if (msgEl) msgEl.style.display = 'flex';

  // Render with basic code block detection
  renderBubble(currentBubble, currentText);
  scrollToBottom();
}

function renderBubble(el, text) {
  // Split on code fences
  const parts = text.split(/(```[\w]*\n[\s\S]*?```|```[\w]*[\s\S]*$)/g);
  el.innerHTML = '';
  parts.forEach(part => {
    if (part.startsWith('```')) {
      const langMatch = part.match(/^```(\w*)/);
      const lang = langMatch ? langMatch[1] : '';
      const code = part.replace(/^```\w*\n?/, '').replace(/```$/, '');
      const block = document.createElement('div');
      block.className = 'code-block';
      block.innerHTML = `
        <div class="code-bar">
          <span>${lang || 'code'}</span>
          <button class="copy-btn" onclick="copyCode(this)">copy</button>
        </div>
        <pre class="code-pre">${escHtml(code)}</pre>`;
      el.appendChild(block);
    } else if (part.trim()) {
      const p = document.createElement('span');
      p.textContent = part;
      el.appendChild(p);
    }
  });
}

function finalizeCurrentAgent() {
  // Remove thinking indicator if still visible
  const thinkEl = document.getElementById('think-' + currentAgentId);
  if (thinkEl) thinkEl.remove();
  currentBubble  = null;
  currentText    = "";
  currentAgentId = null;
}

function markAgentDone(agentId) {
  const step = document.getElementById('step-' + agentId);
  if (step) {
    step.className = 'agent-step done';
    document.getElementById('stepStatus-' + agentId).textContent = 'Done ✓';
  }
}

function onPipelineDone(msg) {
  setBusy(false);
  document.getElementById('pipelineStatus').textContent = '✅ All agents done!';
  if (msg.has_download) {
    document.getElementById('downloadBanner').classList.add('show');
    // Fetch the final HTML
    fetch('/api/download/' + activeSid)
      .then(r => r.text())
      .then(html => { finalHtml = html; });
  }
  // System message
  const sysEl = document.createElement('div');
  sysEl.style.cssText = 'text-align:center;font-size:11px;color:var(--muted);padding:8px';
  sysEl.textContent = '✨ Pipeline complete — all 6 agents finished';
  document.getElementById('messages').appendChild(sysEl);
  scrollToBottom();
}

// ── Download / Preview ────────────────────────────────────────────────────
function downloadSite() {
  if (!finalHtml) return;
  const blob = new Blob([finalHtml], { type: 'text/html' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = 'website.html';
  a.click();
  URL.revokeObjectURL(url);
}

function previewSite() {
  if (!finalHtml) return;
  const blob = new Blob([finalHtml], { type: 'text/html' });
  window.open(URL.createObjectURL(blob), '_blank');
}

// ── Helpers ───────────────────────────────────────────────────────────────
function appendUserMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg user';
  el.innerHTML = `
    <div class="msg-body">
      <div class="msg-header" style="justify-content:flex-end">
        <span class="msg-name">You</span>
      </div>
      <div class="msg-bubble">${escHtml(text)}</div>
    </div>
    <div class="msg-avatar" style="background:rgba(0,229,160,.12)">🧑</div>`;
  document.getElementById('messages').appendChild(el);
  scrollToBottom();
}

function appendError(text) {
  const el = document.createElement('div');
  el.className = 'msg error-msg';
  el.innerHTML = `
    <div class="msg-avatar" style="background:rgba(255,84,112,.12)">⚠️</div>
    <div class="msg-body">
      <div class="msg-header"><span class="msg-name" style="color:#ff5470">Error</span></div>
      <div class="msg-bubble">${escHtml(text)}</div>
    </div>`;
  document.getElementById('messages').appendChild(el);
  scrollToBottom();
}

function copyCode(btn) {
  const code = btn.closest('.code-block').querySelector('.code-pre').textContent;
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = 'copied!';
    setTimeout(() => btn.textContent = 'copy', 1500);
  });
}

function setBusy(b) {
  busy = b;
  document.getElementById('sendBtn').disabled = b;
  document.getElementById('sendBtn').textContent = b ? '…' : 'Build ↗';
}

function scrollToBottom() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def _json(self, d: dict, status: int = 200):
        body = json.dumps(d).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            data = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/health":
            return self._json({
                "ok":         True,
                "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
                "model":      MODEL,
            })

        if path.startswith("/api/stream/"):
            sid = path.split("/")[-1]
            return self._sse(sid)

        if path.startswith("/api/download/"):
            sid = path.split("/")[-1]
            with _sess_lock:
                sess = _sessions.get(sid)
            html = sess["final_html"] if sess else ""
            data = (html or "").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="website.html"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/chat":
            body   = self._body()
            prompt = body.get("prompt", "").strip()
            if not prompt:
                return self._json({"ok": False, "error": "prompt is required"}, 400)
            sid = new_session()
            threading.Thread(target=run_pipeline, args=(sid, prompt), daemon=True).start()
            return self._json({"ok": True, "sid": sid})

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _sse(self, sid: str):
        with _sess_lock:
            sess = _sessions.get(sid)

        self.send_response(200)
        self.send_header("Content-Type",  "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if not sess:
            self._sse_write({"type": "error", "message": "Session not found"})
            return

        q = sess["queue"]
        while True:
            try:
                event = q.get(timeout=30)
                self._sse_write(event)
                if event["type"] in ("pipeline_done", "error"):
                    break
            except queue.Empty:
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
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
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    url = f"http://127.0.0.1:{PORT}"

    print(f"""
╔══════════════════════════════════════════════════╗
║        WebForge AI — Multi-Agent Builder         ║
╠══════════════════════════════════════════════════╣
║  Dashboard  →  {url:<33}║
║  API Key    →  {"✅ Set" if api_key else "❌ NOT SET — export ANTHROPIC_API_KEY":<33}║
║  Model      →  {MODEL:<33}║
║  Agents     →  {len(AGENTS)} agents running automatically      ║
╚══════════════════════════════════════════════════╝
""")

    if not api_key:
        print("  ⚠  Set your API key first:")
        print("     export ANTHROPIC_API_KEY='sk-ant-...'")
        print()

    threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
        server.shutdown()


if __name__ == "__main__":
    main()
