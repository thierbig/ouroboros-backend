"""Replay a stuck session's initial user message through the agent loop.

Usage:
    python analysis/replay_driver.py <session_id> [--runs N]
    python analysis/replay_driver.py --all [--runs N]
    python analysis/replay_driver.py --golden [--runs N]

For each run, writes analysis/runs/<session_id>_<run_idx>.json with:
- the event stream (yielded by Agent.run)
- final status (completed_clean | force_summary | error | interrupted)
- iteration count, token count, wall-clock time
- a copy of the initial_user_message for context

Reconstructs initial conditions by creating an isolated working directory
at  C:/Users/thier/ouroboros-temp/replay/<session_id>_<run_idx>/
and seeding it with an empty CLAUDE.md (the real backend seeds more metadata,
but we have no record of the original file contents in Mongo — a gap worth
flagging to the fixers if CLAUDE.md content turns out to influence stuckness).

The replay driver is reused by the Phase 3 validator. This script is
self-contained: it does not touch Mongo or the backend server.
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path so we can import core.*
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from core.agent import Agent
from core.adapters.anthropic import AnthropicAdapter
from core.adapters.openai import OpenAIAdapter
from core.tools import create_tool_registry


REPLAY_SET_PATH = _ROOT / "analysis" / "replay_set.json"
RUNS_DIR = _ROOT / "analysis" / "runs"
TEMP_ROOT = Path("C:/Users/thier/ouroboros-temp/replay")


def load_replay_set() -> dict:
    with open(REPLAY_SET_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_entry(replay_set: dict, session_id: str) -> dict | None:
    for entry in replay_set.get("replay_set", []):
        if entry["session_id"] == session_id:
            return entry
    for entry in replay_set.get("golden_set", []):
        if entry["session_id"] == session_id:
            return entry
    return None


def get_adapter(provider: str, model: str):
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        a = AnthropicAdapter(api_key=key)
        a.default_model = model or a.default_model
        return a
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        a = OpenAIAdapter(api_key=key)
        if model:
            a.default_model = model
        return a
    raise ValueError(f"Unknown provider: {provider}")


def prepare_working_dir(session_id: str, run_idx: int) -> Path:
    wd = TEMP_ROOT / f"{session_id}_{run_idx}"
    if wd.exists():
        shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True, exist_ok=True)
    # Seed CLAUDE.md — the real backend writes one per project with stack rules.
    # We don't have the exact contents; use a minimal stub that mirrors the
    # project-instruction shape so the agent's initial-message check doesn't fail.
    (wd / "CLAUDE.md").write_text(
        "# Project Rules\n\n"
        "Stack: Bun + Vite + React for frontends, Foundry + Solidity for contracts.\n"
        "Deploy frontends to Netlify; deploy contracts to Base Sepolia.\n"
        "Use the pyth_deploy tool for contract deployment — do not try to install Foundry manually.\n",
        encoding="utf-8",
    )
    return wd


def classify_outcome(events: list[dict], exception: str | None) -> str:
    """Classify the final state of a run."""
    if exception:
        return "error"
    # Walk events backwards
    last_response = None
    last_tool_call = None
    for e in reversed(events):
        if e["type"] == "response" and last_response is None:
            last_response = e
            break
    for e in reversed(events):
        if e["type"] == "tool_call" and last_tool_call is None:
            last_tool_call = e
            break
    if last_response is None:
        return "no_response"
    content = last_response.get("content", "") or ""
    # force_summary path emits a response with specific phrasing
    if "maximum number of tool-calling iterations" in content.lower():
        return "force_summary"
    if content.startswith("Agent interrupted"):
        return "interrupted"
    return "completed_clean"


async def run_one(entry: dict, run_idx: int, max_iterations: int = 100) -> dict:
    session_id = entry["session_id"]
    provider = entry.get("provider") or "anthropic"
    model = entry.get("model") or "claude-sonnet-4-20250514"
    initial = entry["initial_user_message"]

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    working_dir = prepare_working_dir(session_id, run_idx)
    adapter = get_adapter(provider, model)
    registry = create_tool_registry()
    agent = Agent(
        adapter=adapter,
        registry=registry,
        max_iterations=max_iterations,
        working_dir=str(working_dir),
    )

    events: list[dict] = []
    # Seed history from the recorded session so the replay resumes from the
    # same conversational state (see analysis/build_replay_set.py).
    history: list[dict] = [dict(m) for m in entry.get("history", [])]
    start = time.monotonic()
    exception_msg: str | None = None
    try:
        async for ev in agent.run(initial, history):
            # Trim oversized tool results in the captured record to keep files readable.
            stored_ev = dict(ev)
            if ev.get("type") == "tool_result":
                r = ev.get("result", "")
                if isinstance(r, str) and len(r) > 4000:
                    stored_ev["result"] = r[:2000] + f"\n[... {len(r)-4000} chars truncated ...]\n" + r[-2000:]
            events.append(stored_ev)
    except Exception as e:
        exception_msg = f"{type(e).__name__}: {e}"
    elapsed = time.monotonic() - start

    outcome = classify_outcome(events, exception_msg)

    # Count iterations = number of assistant messages with tool_calls
    # (same shape as Agent.run's iteration counter)
    iteration_count = sum(1 for e in events if e.get("type") == "tool_call")

    out = {
        "session_id": session_id,
        "run_idx": run_idx,
        "bucket": entry.get("bucket"),
        "baseline_outcome_in_data": entry.get("baseline_outcome"),
        "initial_user_message": initial[:500] + ("..." if len(initial) > 500 else ""),
        "seeded_history_length": len(history) - 1,  # -1 because Agent.run appended user_message
        "provider": provider,
        "model": model,
        "working_dir": str(working_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "iteration_count": iteration_count,
        "total_tokens": agent._total_tokens,
        "outcome": outcome,
        "exception": exception_msg,
        "final_response": _last_response_text(events),
        "event_count": len(events),
        "events": events,
    }
    out_path = RUNS_DIR / f"{session_id}_{run_idx}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    return out


def _last_response_text(events: list[dict]) -> str:
    for e in reversed(events):
        if e.get("type") == "response":
            return (e.get("content") or "")[:800]
    return ""


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("session_id", nargs="?", help="session_id to replay")
    p.add_argument("--runs", type=int, default=1, help="number of runs per session")
    p.add_argument("--all", action="store_true", help="run every session in replay_set")
    p.add_argument("--golden", action="store_true", help="run every session in golden_set")
    p.add_argument("--max-iterations", type=int, default=100)
    args = p.parse_args()

    replay_set = load_replay_set()

    targets: list[dict] = []
    if args.all:
        targets.extend(replay_set["replay_set"])
    if args.golden:
        targets.extend(replay_set["golden_set"])
    if args.session_id:
        entry = find_entry(replay_set, args.session_id)
        if not entry:
            print(f"ERROR: session_id {args.session_id} not found in replay_set.json", file=sys.stderr)
            sys.exit(1)
        targets.append(entry)

    if not targets:
        print("Nothing to do — provide session_id, --all, or --golden", file=sys.stderr)
        sys.exit(1)

    summary = []
    for entry in targets:
        for idx in range(args.runs):
            print(f"[replay] {entry['session_id']} run {idx+1}/{args.runs} ({entry.get('bucket')}) ...", flush=True)
            try:
                result = await run_one(entry, idx, max_iterations=args.max_iterations)
                print(
                    f"  -> outcome={result['outcome']} iters={result['iteration_count']} "
                    f"tokens={result['total_tokens']} elapsed={result['elapsed_seconds']}s",
                    flush=True,
                )
                summary.append({
                    "session_id": entry["session_id"],
                    "run_idx": idx,
                    "bucket": entry.get("bucket"),
                    "outcome": result["outcome"],
                    "iterations": result["iteration_count"],
                    "tokens": result["total_tokens"],
                    "elapsed": result["elapsed_seconds"],
                })
            except Exception as e:
                print(f"  -> EXCEPTION: {type(e).__name__}: {e}", flush=True)
                summary.append({
                    "session_id": entry["session_id"],
                    "run_idx": idx,
                    "bucket": entry.get("bucket"),
                    "outcome": "driver_error",
                    "error": f"{type(e).__name__}: {e}",
                })

    # Write a summary file for convenience
    summary_path = RUNS_DIR / f"_summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote summary to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
