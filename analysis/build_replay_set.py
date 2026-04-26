"""Rebuild replay_set.json from analysis/dumps/.

For each session, extract:
  - history: all messages up to (but not including) the final user message
  - initial_user_message: the final user message content

This captures the state the agent was in when it last received user input —
which is what we want to replay. For stuck sessions, the stuck loop happens
AFTER this last user turn, so replaying reproduces the failure conditions.

Run:
    py -3.12 analysis/build_replay_set.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DUMPS = ROOT / "dumps"
OUT = ROOT / "replay_set.json"

# Manually curated buckets + notes (preserved from previous replay_set.json)
META = {
    # stuck
    "69cafdd3c9ee05a19b45638a": ("foundry-install-loop", "stuck",
        "Entropy game; 13 chunks; 7 straight foundry PATH retries before cutoff"),
    "69cb280662972386aaf55ff4": ("foundry-install-loop", "stuck",
        "Entropy game; 17 chunks; loops on PATH prefix + forge install pyth-crosschain"),
    "69cc0171365f162bc336119f": ("foundry-install-loop", "stuck",
        "Price-Feed game; includes bun-vite-scaffold-fallback path"),
    "69cc5c542447cfb1b234d419": ("foundry-install-loop", "stuck",
        "E2E test run; 7 chunks; forge install loops; short stuck case"),
    "69cc5d252447cfb1b234d422": ("foundry-install-loop", "stuck",
        "Short prompt Coin Flip start; 4 chunks before cutoff"),
    "69caf6db825fef911ec3ebd3": ("empty-resume-context", "stuck",
        "Initial message is 'resume' with no history; ends mid-write_file"),
    "69c5c96fd00e0eacbd9bc64f": ("api-tool-result-mismatch", "error",
        "Highest-cost at $2.54 / 41 chunks; Anthropic 400 tool_use/tool_result mismatch"),
    # golden
    "69cc194866eebfa5ccde6a6f": ("golden", "completed", "17 chunks; completed with deploy"),
    "69cc20f34735ef0c0f1c3089": ("golden", "completed", "24 chunks; completed with deploy"),
    "69cbefc607eb531d6dbd5f21": ("golden", "completed", "22 chunks; completed with deploy"),
    "69cc06975ef566cf5fe2e06d": ("golden", "completed", "27 chunks; completed with deploy"),
    "69cbfb652f17f872550f8ab9": ("golden", "completed", "24 chunks; completed with deploy"),
}

STUCK_IDS = [
    "69cafdd3c9ee05a19b45638a",
    "69cb280662972386aaf55ff4",
    "69cc0171365f162bc336119f",
    "69cc5c542447cfb1b234d419",
    "69cc5d252447cfb1b234d422",
    "69caf6db825fef911ec3ebd3",
    "69c5c96fd00e0eacbd9bc64f",
]
GOLDEN_IDS = [
    "69cc194866eebfa5ccde6a6f",
    "69cc20f34735ef0c0f1c3089",
    "69cbefc607eb531d6dbd5f21",
    "69cc06975ef566cf5fe2e06d",
    "69cbfb652f17f872550f8ab9",
]


def _normalize_content(content):
    """If content is a list of Anthropic content-blocks, reduce to plain text.
    Otherwise pass through. The agent passes history back to the adapter — keeping
    it in plain-string form avoids reserialization quirks across providers."""
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    # already represented in tool_calls; skip here
                    pass
                elif b.get("type") == "tool_result":
                    c = b.get("content", "")
                    if isinstance(c, list):
                        for cb in c:
                            if isinstance(cb, dict) and cb.get("type") == "text":
                                parts.append(cb.get("text", ""))
                    else:
                        parts.append(str(c))
                else:
                    parts.append(str(b))
        return "\n".join(parts)
    return content


def _split_history(messages: list[dict]) -> tuple[list[dict], str]:
    """Return (history_before_last_user, last_user_content)."""
    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        raise ValueError("no user message found")
    history = messages[:last_user_idx]
    last_user = messages[last_user_idx].get("content", "")
    last_user = _normalize_content(last_user)

    cleaned = []
    for m in history:
        cm = dict(m)
        cm["content"] = _normalize_content(cm.get("content", ""))
        cleaned.append(cm)
    return cleaned, last_user


def build_entry(sid: str) -> dict:
    path = DUMPS / f"{sid}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    bucket, outcome, notes = META[sid]
    msgs = d["session"].get("messages", [])
    history, last_user = _split_history(msgs)
    return {
        "session_id": sid,
        "initial_user_message": last_user,
        "history": history,
        "bucket": bucket,
        "baseline_outcome": outcome,
        "provider": d["session"].get("provider") or "anthropic",
        "model": d["session"].get("model") or "claude-sonnet-4-20250514",
        "notes": notes,
        "message_count_in_dump": len(msgs),
        "history_length": len(history),
    }


def main():
    replay = [build_entry(sid) for sid in STUCK_IDS]
    golden = [build_entry(sid) for sid in GOLDEN_IDS]
    out = {
        "_meta": {
            "generated_at": "2026-04-14",
            "source": "analysis/dumps/",
            "corpus_size": 19,
            "stuck_found": 7,
            "replay_set_size": len(replay),
            "golden_set_size": len(golden),
            "note": (
                "Each entry's `history` is the full conversation up to (but not "
                "including) the final user message in the original session. "
                "`initial_user_message` is that final user turn. Replaying with "
                "(initial, history) reproduces the conditions the agent was in "
                "when the stuck loop (or successful build) began."
            ),
        },
        "replay_set": replay,
        "golden_set": golden,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Wrote {OUT}")
    for e in replay + golden:
        print(f"  {e['session_id']} [{e['bucket']}]: history_len={e['history_length']} "
              f"last_user_preview={(e['initial_user_message'] or '')[:60]!r}")


if __name__ == "__main__":
    main()
