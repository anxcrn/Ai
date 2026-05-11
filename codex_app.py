#!/usr/bin/env python3
"""Unified Codex-style launcher for this repository.

This turns the mixed repository into one entrypoint with multiple agent modes.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLAWSPRING_MAIN = ROOT / "clawspring" / "clawspring.py"


def _run_clawspring(extra_args: list[str]) -> int:
    if not CLAWSPRING_MAIN.exists():
        print("Error: clawspring/clawspring.py not found.", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(CLAWSPRING_MAIN), *extra_args]
    return subprocess.call(cmd, cwd=str(ROOT / "clawspring"))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="codex-app",
        description="Single-app launcher with multiple agent workflows (codex style).",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="chat",
        choices=["chat", "brainstorm", "worker", "ssj"],
        help="Agent mode to start.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional initial prompt.")
    parser.add_argument("--model", dest="model", help="Model override forwarded to clawspring.")
    parser.add_argument("--accept-all", action="store_true", help="Auto-approve tool permissions.")
    parser.add_argument("--verbose", action="store_true", help="Show thinking/debug output.")

    args = parser.parse_args()

    forwarded: list[str] = []
    if args.model:
        forwarded += ["--model", args.model]
    if args.accept_all:
        forwarded.append("--accept-all")
    if args.verbose:
        forwarded.append("--verbose")

    initial = " ".join(args.prompt).strip()
    if args.mode == "chat":
        if initial:
            forwarded += ["-p", initial]
    elif args.mode == "brainstorm":
        forwarded += ["-p", f"/brainstorm {initial}".strip()]
    elif args.mode == "worker":
        forwarded += ["-p", f"/worker {initial}".strip()]
    elif args.mode == "ssj":
        forwarded += ["-p", "/ssj"]

    return _run_clawspring(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
