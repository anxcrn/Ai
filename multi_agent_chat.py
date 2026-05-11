#!/usr/bin/env python3
"""
multi_agent_chat.py  —  Multi-Agent Website & App Builder (OpenRouter Edition)

Run:
    pip install -U requests          # optional — falls back to urllib
    export OPENROUTER_API_KEY='sk-or-...'
    python multi_agent_chat.py

Opens http://127.0.0.1:7800
Describe any website or app → 7 specialised agents auto-chain to build it.
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

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
PORT  = 7800
# Default model — any OpenRouter model ID works here, e.g.:
#   "anthropic/claude-sonnet-4-5"
#   "openai/gpt-4o"
#   "google/gemini-2.5-pro"
#   "meta-llama/llama-3.3-70b-instruct"
MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")
API   = "https://openrouter.ai/api/v1/chat/completions"

# ─────────────────────────────────────────────────────────────────────────────
# Agent Definitions — 7 agents, each laser-focused on one responsibility
# ─────────────────────────────────────────────────────────────────────────────
AGENTS = [
    {
        "id":    "planner",
        "name":  "Planner Agent",
        "icon":  "🧠",
        "color": "#c084fc",
        "label": "Analysing request & writing master plan…",
        "system": """You are the Planner Agent — the very first step in an AI website/app building pipeline.

Your ONLY job is to produce a comprehensive MASTER PROJECT PLAN before a single line of code is written.

## What to output (use these exact headings):

### 🎯 Project Brief
Restate the project in 2–3 sentences: what it is, who it's for, and the core value it delivers.

### 👤 Target Audience & Goals
Who will use this? What are their primary goals? What actions should the site drive?

### 🗺️ Sitemap & Content Architecture
List every page or section with a one-line description of its purpose and key content.

### 🎨 Visual Identity
- Brand personality (3 adjectives)
- Primary colour, accent colour, background palette
- Typography: heading font + body font (Google Fonts names)
- Overall aesthetic (minimalist / bold / playful / corporate / etc.)

### 🧩 Component Inventory
List every UI component needed (navbar, hero, feature cards, testimonials, pricing table, CTA, footer, etc.)

### ⚡ Features & Interactions
List every interactive feature: hamburger menu, smooth scroll, contact form, tabs, accordions, carousels, etc.

### 🔧 Technical Constraints
- Single HTML file (embedded CSS + JS, no build tools)
- No external JS libraries except CDN fonts
- Must be fully responsive (mobile-first)
- Must work offline after first load

### 📋 Agent Task Assignments
For each downstream agent (Architect, Coder, Motion, 3D, Mobile, QA) write one sentence on what they specifically need to focus on for THIS project.

Be thorough. This plan drives every downstream agent. No code — plan only.""",
    },
    {
        "id":    "architect",
        "name":  "Architect Agent",
        "icon":  "🏗️",
        "color": "#7c6fff",
        "label": "Designing technical structure & system…",
        "system": """You are the Architect Agent. You receive a Master Plan and translate it into a precise technical blueprint.

## Output (use these exact headings):

### 🏛️ HTML Structure
Write the full semantic HTML skeleton (no CSS/JS yet) — every element, section, and landmark.
Use real, meaningful placeholder text that matches the site's purpose. NO Lorem Ipsum.

### 🎨 CSS Design System
Define all CSS custom properties:
- Colour tokens (--color-primary, --color-accent, --color-bg, --color-surface, --color-text, --color-muted)
- Typography scale (--font-display, --font-body, --size-xs through --size-5xl)
- Spacing scale (--space-1 through --space-16)
- Shadow levels (--shadow-sm, --shadow-md, --shadow-lg, --shadow-xl)
- Border radius tokens
- Transition defaults

### 📐 Layout Strategy
Describe the CSS Grid / Flexbox layout for each major section. Include breakpoint strategy.

### 🔗 JavaScript Architecture
List every JS function needed, its purpose, and what DOM it manipulates. No code yet — just the plan.

### ♿ Accessibility Checklist
List every ARIA label, role, and accessibility feature required for this specific site.

### 🚀 Performance Strategy
Lazy loading, critical CSS inlining, image optimisation strategy.

Be precise — the Coder Agent will implement EXACTLY what you specify.""",
    },
    {
        "id":    "coder",
        "name":  "Coder Agent",
        "icon":  "💻",
        "color": "#00e5a0",
        "label": "Writing production HTML, CSS & JavaScript…",
        "system": """You are the Coder Agent. You receive a Master Plan + Technical Blueprint. Build the complete website.

## Rules:
1. Output ONE complete, self-contained HTML file — all CSS in <style>, all JS in <script>
2. Use ALL CSS custom properties from the blueprint's design system
3. Use semantic HTML5: <header>, <nav>, <main>, <section>, <article>, <aside>, <footer>
4. Every section from the plan MUST be present and fully built
5. Real, purposeful placeholder content matching the site topic — never Lorem Ipsum
6. Working navigation: smooth scroll, active states, keyboard accessible
7. All interactive elements must actually work: forms have validation, toggles toggle, tabs switch
8. Responsive from the start: use CSS Grid + Flexbox, relative units, clamp() for fluid type
9. Include <meta name="viewport">, <title>, and <meta name="description">
10. No external JS libraries — pure vanilla JavaScript only
11. CSS must include :focus-visible outlines, sufficient colour contrast, aria-label on icon buttons
12. Add CSS comments marking each section (/* === HERO === */)
13. Add JS comments explaining each function

Output ONLY the complete HTML file starting with <!DOCTYPE html>. Zero explanation before or after.""",
    },
    {
        "id":    "motion",
        "name":  "Motion Agent",
        "icon":  "🎬",
        "color": "#ff9f47",
        "label": "Crafting animations & micro-interactions…",
        "system": """You are the Motion Agent. You receive a working website. Add a world-class motion design layer.

## Must add ALL of the following:

### Scroll Animations (IntersectionObserver)
- Fade + slide-up on every section as it enters viewport
- Staggered entrance for grid/list items (nth-child delay)
- Counter animation on stats/numbers
- Progress bar that fills as user scrolls

### Hover Micro-interactions
- Buttons: subtle scale(1.03) + shadow lift + colour shift
- Cards: border glow + translateY(-4px)
- Nav links: animated underline that slides in from left
- Icons: rotate or bounce on hover
- Images: gentle scale(1.05) with overflow:hidden clip

### Page-load Entrance
- Hero headline: split into words, each word slides up with stagger
- Nav items: fade in from top with delay
- Hero image/graphic: scale from 0.95 to 1 with opacity

### Scroll-linked Effects
- Parallax on hero background (JS scroll listener, -0.3x speed)
- Navbar becomes solid/compact on scroll past hero

### Delightful Details
- Smooth page scroll with scroll-behavior:smooth
- Ripple effect on button clicks
- Form fields: label floats on focus
- Loading shimmer placeholder (if applicable)

## Rules:
- CSS animations + vanilla JS IntersectionObserver + scroll listeners only
- All animations respect prefers-reduced-motion via @media query
- Never break existing layout, content, or functionality
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "3d",
        "name":  "3D & FX Agent",
        "icon":  "🎮",
        "color": "#ff5470",
        "label": "Adding depth, 3D & visual effects…",
        "system": """You are the 3D & Visual Effects Agent. Elevate the site from flat to dimensional.

## Must add ALL of the following:

### Card Tilt Effect
- On every card: CSS perspective + JS mouse-tracking (mousemove event)
- Max tilt: 10deg on X and Y axes
- Smooth lerp interpolation (requestAnimationFrame)
- Glare overlay effect: a pseudo-element that moves with mouse
- Reset to flat on mouseleave with transition

### Elevation System
- Apply consistent box-shadows with 3 depth levels:
  - Level 1 (resting): small, close shadow
  - Level 2 (hover): medium, spread shadow with colour tint
  - Level 3 (active/featured): large, ambient shadow
- Add CSS `transform: translateZ(0)` for GPU compositing

### Glassmorphism
- Apply to at least one featured element (hero card, pricing card, CTA box):
  backdrop-filter: blur(20px) saturate(180%)
  background: rgba(255,255,255,0.05)
  border: 1px solid rgba(255,255,255,0.1)

### Parallax Depth Layers
- Hero: 2–3 depth layers moving at different scroll speeds
- Decorative floating shapes: animate with CSS @keyframes (float up/down, rotate)
- Mouse parallax on hero: elements shift slightly based on cursor position (JS)

### CSS 3D Showcase
- At least one element uses CSS 3D: rotate3d, rotateY, or a 3D card flip
- Decorative geometric shapes using CSS (borders, transforms) to create depth

### Particle / Gradient Effects
- Animated gradient mesh background or conic-gradient on a section
- Noise texture overlay (CSS or SVG filter) for depth on flat backgrounds

## Rules:
- Pure CSS + vanilla JS — no Three.js, no Canvas (unless specifically fitting)
- Preserve all existing animations from the Motion Agent
- Never break layout, responsiveness, or accessibility
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "mobile",
        "name":  "Mobile Agent",
        "icon":  "📱",
        "color": "#47c8ff",
        "label": "Perfecting responsive design & touch UX…",
        "system": """You are the Mobile Agent. Make the site pixel-perfect on every device.

## Must implement ALL of the following:

### Breakpoint System
- 1200px: large desktop adjustments
- 992px: desktop to tablet transition
- 768px: tablet layout (2-column grids become 1-column)
- 480px: phone layout
- 360px: small phone (minimum supported width)
Use min-width (mobile-first) approach.

### Navigation
- Hamburger menu with animated icon (3 bars → X)
- Full-screen overlay nav on mobile with staggered link entrance
- Backdrop blur on mobile menu overlay
- Close on: hamburger click, link click, Escape key, outside tap
- Prevent body scroll when menu is open

### Typography
- Use clamp() for all headings: clamp(min, preferred, max)
- Minimum body text: 16px
- Minimum tap target: 44×44px for all interactive elements
- Line length: max-width on paragraphs for readability

### Touch Optimisation
- Remove hover effects that don't work on touch (use @media (hover: hover))
- Add touch feedback: active states with slightly darker background
- Swipe gesture support on carousels/sliders if present
- Prevent accidental zoom: font-size ≥ 16px on inputs

### Layout Fixes
- No horizontal overflow at any viewport width
- Images: max-width:100% everywhere
- Tables: horizontal scroll wrapper if any tables exist
- Sticky header on mobile: position:sticky top:0 with z-index

### Performance
- Reduce animation complexity on mobile (simpler transforms)
- Use will-change sparingly and only on animated elements
- Lazy-load images (loading="lazy" attribute)

## Rules:
- Never break desktop layout
- Test every existing feature at 360px width
- Output the COMPLETE updated HTML file starting with <!DOCTYPE html>. No explanation.""",
    },
    {
        "id":    "qa",
        "name":  "QA & Polish Agent",
        "icon":  "✅",
        "color": "#a8ff78",
        "label": "Final audit, accessibility & production polish…",
        "system": """You are the QA & Polish Agent — the final gatekeeper. Deliver a production-perfect website.

## Full Audit Checklist:

### 🐛 Bug Fixes
- Fix any broken layout, overflow, z-index conflicts, or clipping
- Ensure all JS functions are defined before they're called
- Verify all event listeners are properly attached
- Check all CSS animations have correct keyframe references
- Verify IntersectionObserver targets actually exist

### ♿ Accessibility (WCAG 2.1 AA)
- All images have meaningful alt text
- All icon-only buttons have aria-label
- Colour contrast ratio ≥ 4.5:1 for body text, ≥ 3:1 for large text
- Focus ring visible on all interactive elements (outline: 2px solid currentColor)
- Logical heading hierarchy (h1 → h2 → h3, no skipping)
- Skip-to-content link at top of page
- All form fields have associated <label>
- ARIA roles where semantic HTML isn't enough

### 🔍 SEO
- <title> tag: descriptive, 50–60 chars
- <meta name="description">: compelling, 150–160 chars
- Open Graph tags: og:title, og:description, og:type
- Twitter Card meta tags
- Canonical URL placeholder: <link rel="canonical" href="#">
- Proper heading structure and keyword-rich copy
- <html lang="en"> attribute

### 🎨 Design Consistency
- Verify all design tokens are applied consistently
- Remove any hardcoded colours that bypass CSS variables
- Uniform spacing using the token scale
- Font sizes follow the type scale — no arbitrary values
- All interactive states defined: hover, focus, active, disabled

### ⚡ Performance
- Remove all duplicate CSS rules (deduplicate with precision)
- Remove unused JavaScript
- Consolidate repeated code into reusable functions/classes
- Ensure smooth 60fps animations (no layout-triggering properties in animation)
- Add <meta name="theme-color"> for mobile browsers

### 🌐 Cross-browser Safety
- Replace any properties that need vendor prefixes
- Ensure -webkit-backdrop-filter alongside backdrop-filter
- Add -webkit-font-smoothing: antialiased
- Test all CSS Grid usage for IE/old browser graceful degradation

### ✨ Final Polish
- Ensure copy is polished, on-brand, and compelling
- Verify the visual hierarchy guides the eye correctly
- All transitions feel snappy but not jarring (100–300ms sweet spot)
- The site tells a coherent story from top to bottom
- Add a subtle scroll-to-top button (appears after 400px scroll)
- Ensure footer has copyright year (use JS: new Date().getFullYear())

Output the FINAL, COMPLETE, PRODUCTION-READY HTML file starting with <!DOCTYPE html>.
This is what the user downloads. It must be perfect. No explanation before or after.""",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Session store
# ─────────────────────────────────────────────────────────────────────────────
_sessions: dict[str, dict] = {}
_sess_lock = threading.Lock()


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    with _sess_lock:
        _sessions[sid] = {
            "queue":      queue.Queue(maxsize=8000),
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
# OpenRouter streaming API call  (OpenAI-compatible SSE format)
# ─────────────────────────────────────────────────────────────────────────────
def stream_openrouter(system: str, messages: list[dict], sid: str, agent: dict) -> str:
    """
    Stream a response from OpenRouter.
    Pushes token events to the session queue.
    Returns the full accumulated text.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set.\n"
            "Export it with:  export OPENROUTER_API_KEY='sk-or-...'"
        )

    # OpenAI-compatible message format: system goes into messages array
    full_messages = [{"role": "system", "content": system}] + messages

    body = json.dumps({
        "model":       MODEL,
        "max_tokens":  16000,
        "stream":      True,
        "messages":    full_messages,
        "temperature": 0.7,
        # OpenRouter-specific: identify your app
        "extra_headers": {
            "HTTP-Referer": f"http://127.0.0.1:{PORT}",
            "X-Title":      "WebForge AI Multi-Agent Builder",
        },
    }).encode()

    req = Request(
        API,
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  f"http://127.0.0.1:{PORT}",
            "X-Title":       "WebForge AI Multi-Agent Builder",
        },
        method="POST",
    )

    full_text = ""
    last_err  = None

    # Retry up to 3 times on transient errors
    for attempt in range(3):
        try:
            with urlopen(req, timeout=300) as resp:
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

                    # OpenAI SSE delta format
                    choices = evt.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_text += token
                        push(sid, {
                            "type":     "token",
                            "text":     token,
                            "agent_id": agent["id"],
                        })

                    # Check for finish reason
                    finish = choices[0].get("finish_reason")
                    if finish and finish != "null":
                        break

            return full_text  # success

        except HTTPError as e:
            body_bytes = e.read()
            err_msg = body_bytes.decode("utf-8", errors="replace")
            last_err = f"HTTP {e.code}: {err_msg[:400]}"
            if e.code in (429, 500, 502, 503, 504):
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)

        except (URLError, OSError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
            continue

    raise RuntimeError(f"OpenRouter API failed after 3 attempts: {last_err}")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline utilities
# ─────────────────────────────────────────────────────────────────────────────
def extract_html(text: str) -> str:
    """
    Robustly extract HTML from model output.
    Handles fenced code blocks and raw HTML output.
    """
    if not text:
        return ""

    # 1. Try ```html ... ``` fence (most common)
    m = re.search(r"```html\s*(<!DOCTYPE.*?</html>)\s*```", text, re.S | re.I)
    if m:
        return m.group(1).strip()

    # 2. Try generic ``` ... ``` fence containing HTML
    m = re.search(r"```\w*\s*(<!DOCTYPE.*?</html>)\s*```", text, re.S | re.I)
    if m:
        return m.group(1).strip()

    # 3. Try raw HTML without fence
    m = re.search(r"(<!DOCTYPE\s+html[\s\S]*?</html>)", text, re.S | re.I)
    if m:
        return m.group(1).strip()

    # 4. If nothing found, return the full text (agent may have output raw HTML)
    stripped = text.strip()
    if stripped.lower().startswith("<!doctype"):
        return stripped

    return 