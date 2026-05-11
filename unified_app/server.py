#!/usr/bin/env python3
from __future__ import annotations
import json, threading, time, platform
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parent
MODELS = ["gpt-5.3-codex", "gpt-5.1", "gpt-4.1", "o4-mini"]

@dataclass
class Agent:
    name: str
    role: str

AGENTS = [
    Agent("Architect Agent", "Decompose mission and architecture."),
    Agent("Coder Agent", "Implement backend/frontend code."),
    Agent("Motion Agent", "Build Framer Motion style interactions."),
    Agent("3D Agent", "Design high-graphics 3D sections."),
    Agent("Mobile Agent", "Manage mobile bridge actions."),
    Agent("QA Agent", "Run verification and quality gates."),
]
_state_lock = threading.Lock()
_state = {"timeline": []}

def push_event(event: str) -> None:
    with _state_lock:
        _state["timeline"].insert(0, {"ts": time.strftime("%H:%M:%S"), "event": event})
        _state["timeline"] = _state["timeline"][:250]

def run_mission(mission: str, model: str) -> None:
    push_event(f"Mission accepted on {model}: {mission}")
    for step in [
        "Architect Agent published phased roadmap.",
        "Coder Agent started implementation batch.",
        "Motion Agent produced animation choreography.",
        "3D Agent generated graphics scene plan.",
        "Mobile Agent prepared mobile automation hooks.",
        "QA Agent opened verification matrix.",
    ]:
        time.sleep(0.6)
        push_event(step)

class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def _static(self, rel: str):
        path = ROOT / rel
        if not path.exists() or not path.is_file(): return self.send_error(404)
        ctype = {".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"application/javascript; charset=utf-8",".webmanifest":"application/manifest+json"}.get(path.suffix,"text/plain")
        data = path.read_bytes(); self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/agents": return self._json({"agents":[a.__dict__ for a in AGENTS]})
        if self.path == "/api/models": return self._json({"models": MODELS})
        if self.path == "/api/health": return self._json({"ok":True,"runtime":"python","version":platform.python_version()})
        if self.path == "/api/timeline":
            with _state_lock: return self._json({"timeline":_state["timeline"]})
        if self.path.startswith("/api/mobile/ping"):
            q = parse.parse_qs(parse.urlparse(self.path).query); endpoint = q.get("endpoint", [""])[0]
            if not endpoint: return self._json({"ok":False,"error":"Missing endpoint"},400)
            try:
                with request.urlopen(endpoint, timeout=5) as resp:
                    body = resp.read(1200).decode("utf-8", errors="replace")
                    return self._json({"ok":True,"status":resp.status,"body":body})
            except error.URLError as ex:
                return self._json({"ok":False,"error":str(ex)},502)
        rel = self.path.strip("/") or "index.html"
        return self._static(rel)

    def do_POST(self):
        if self.path != "/api/dispatch": return self.send_error(404)
        ln = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(ln) or b"{}")
        mission = str(payload.get("mission","")).strip(); model = str(payload.get("model", MODELS[0])).strip() or MODELS[0]
        if not mission: return self._json({"ok":False,"error":"mission is required"},400)
        if model not in MODELS: return self._json({"ok":False,"error":"unsupported model"},400)
        threading.Thread(target=run_mission, args=(mission, model), daemon=True).start()
        self._json({"ok":True,"message":"Mission dispatched","model":model})

def main():
    print("Power Codex Studio PWA: http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1",8787), Handler).serve_forever()

if __name__ == "__main__": main()
