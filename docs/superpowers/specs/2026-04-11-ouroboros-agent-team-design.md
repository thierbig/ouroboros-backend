# Ouroboros Agent-Quality Team — Design

**Date:** 2026-04-11
**Status:** Approved design, ready for implementation plan
**Owner:** Leader agent (Claude) + human reviewer

## Mission

Measurably reduce the rate at which the ouroboros agent gets stuck or gives up on real game-building sessions. A session is "stuck" if any of the following hold:

- `session.error_message` is set
- Chunks exist with `status != "success"` or a non-null `error` field
- Chunk count reached `max_iterations` without a terminal assistant-without-tool-calls message (the "hit the wall" case)
- `session.status == "running"` but `last_activity` is more than 24 hours old (abandoned)

Evidence comes from MongoDB: `db.sessions` and `db.chunks`, accessed via the existing helpers in `db/models.py`.

## Success criteria

1. A written failure-mode taxonomy with counts per category and at least three example session IDs per category.
2. A curated **replay set** of 10–15 hard sessions that reliably reproduce stuckness on today's `main`.
3. On that replay set, the patched agent's success rate is **≥60%** absolute (stretch: **≥75%**), measured as "cases that finish cleanly in ≥2 of 3 runs / total cases." Baseline on the same set is expected to be ≤20%.
4. No regression on a small **golden set** of 5 sessions the agent already handles well.
5. All fixes land as a reviewable, reversible diff (single PR or small stack). The user merges manually.

## Execution mode

**tmux mode.** Agents run as Claude Code teammate instances in separate tmux panes, coordinating through the shared task list (`TaskCreate`/`TaskUpdate`/`TaskList`) and `SendMessage`. Not the in-process `Agent` tool.

**Leader pane = the user's existing Claude Code session.** The leader does not spawn itself; it *is* whatever session is currently open when the plan begins executing. Teammate panes are spawned from the leader's pane via the user's terminal multiplexer — **psmux on Windows** in this environment. ("tmux mode" is the Claude Code mode name regardless of which multiplexer runs underneath.) The leader is responsible for: creating the team via `TeamCreate`, seeding the shared task list, instructing the user on when to open new psmux panes, and closing panes as phases complete.

Peak pane count is **7**:

- 1 leader (orchestrates, runs review gates — this is the user's existing session)
- 1 investigator
- up to 5 fixers
- 1 validator

Phases stage the panes — never all seven open at once. Phase 1 uses 2 panes (leader + investigator). Phase 2 uses up to 6 panes (leader + up to 5 fixers). Phase 3 uses 2 panes (leader + validator).

## Team roster and phases

| Role | Count | Phase | Job |
|---|---|---|---|
| Leader | 1 | all | Spawns roles, holds the shared task list, runs human review gates |
| Investigator | 1 | 1 | Mine Mongo, produce taxonomy + replay set + baseline numbers |
| Fixer | up to 5 | 2 | One per ranked failure mode; ships a focused diff with tests |
| Validator | 1 | 3 | Runs the replay harness against patched `main`, reports deltas |

## Phase 1 — Investigator

**Inputs.** Read access to MongoDB via the backend's existing `MONGODB_URI`. Helpers in `db/models.py` are reusable.

**Deliverables**, all under a new `analysis/` directory at the repo root:

1. `analysis/dump_stuck_sessions.py` — script that queries `db.sessions` and `db.chunks` for stuck candidates per the definitions above.
2. `analysis/dumps/<session_id>.json` — full session + chunks for every candidate. **Gitignored** (contains potentially sensitive user prompts and generated code).
3. `analysis/taxonomy.md` — ranked failure modes. Each entry contains:
   - Bucket name
   - Definition
   - Count
   - 3+ example session IDs
   - 1–2 illustrative chunk excerpts
   - A one-line hypothesis about the cause
4. `analysis/replay_set.json` — 10–15 hard sessions chosen to cover the taxonomy. Each entry is `{session_id, initial_user_message, bucket, baseline_outcome, notes}`. Committed (scrubbed of PII if necessary).
5. `analysis/baseline.md` — today's success rate on the replay set, computed by running each case once against current `main` through a minimal replay driver. The investigator builds the driver; the validator reuses it.

**Scope boundaries for the investigator:**

- Does not modify any production code outside `analysis/`.
- Does not propose fixes. That is the fixers' job — the taxonomy's "hypothesis" lines are one-liners, not plans.
- Writes the replay driver as a standalone script under `analysis/`, not as a modification to `core/agent.py` or `api/`.

## Phase 2 — Fixers

**Spawning rule.** One fixer per taxonomy bucket, capped at 5. If the taxonomy has more than 5 buckets, the leader merges the lowest-count ones. If it has fewer, we spawn fewer.

**File-collision rule.** General principle: no two fixers may have overlapping write targets. In practice this matters most for `core/agent.py` and `core/prompt.py` — the hot-spot shared files — but the leader also applies the rule to any other file where two or more fixers have a pending change (e.g., `core/registry.py`, `tools/*.py`). The leader serializes conflicting fixers via `TaskUpdate addBlockedBy` on the shared task list. Fixers touching only non-overlapping files, new modules, or tests run in parallel freely.

**Per-fixer contract**, written into each task description:

- Read `analysis/taxonomy.md` and the relevant `analysis/dumps/*` files for the assigned bucket.
- Produce a **minimal** diff targeting that bucket only. No opportunistic refactors. No touching unrelated files.
- Write at least one test that would have failed before the fix. Tests live under `tests/` following existing pytest patterns.
- Write `analysis/fixes/<bucket>.md`: 1-paragraph explanation, which replay sessions it targets, how to verify manually.
- Run `pytest` locally and report the result in the task comment.
- **Must not touch `analysis/replay_set.json` or `analysis/baseline.md`.** Those are the validator's input.

**Fixer handoff.** Each fixer marks its task `completed` and leaves the branch clean. The leader reviews the diff before the validator runs — if a fixer has gone out of scope, the leader reverts or asks them to narrow.

## Phase 3 — Validator

**Inputs.** `analysis/replay_set.json`, `analysis/baseline.md`, and the post-fixer `main` branch.

**What it does.**

1. For each session in the replay set, reconstruct initial conditions: spin up an isolated working directory, replay only the **first user message** (not the full chunk-by-chunk transcript — the patched agent should make its own choices from the same starting point).
2. Run the agent to completion or failure. Record: did it finish cleanly? iterations used? total cost? error_message? final assistant output.
3. Run each case **3 times**. LLMs aren't deterministic. A case counts as passing if ≥2 of 3 runs finish cleanly.
4. Emit `analysis/validation.md`: per-case results, before-vs-after table, aggregate success rate, cost delta, iteration-count delta.

**Success-criteria check.** Validator explicitly evaluates each criterion from the Success criteria section and reports pass/fail.

**Failure loop.** If the ≥60% bar is missed, or the golden set regresses, the validator files a new task describing which fixer's change is suspect. The leader re-queues that one fixer only. Other fixers' work is not re-run.

## Human review gates

1. **After Phase 1, before Phase 2 spawns.** The user reviews `analysis/taxonomy.md` and `analysis/replay_set.json`. If a bucket looks wrong or the replay set is cherry-picked, the taxonomy is re-cut before any fixer spawns.
2. **Per-fixer diff review (soft).** The leader checks each fixer's diff on completion. The user only sees it if the leader flags something.
3. **After Phase 3, before merge.** The user reviews `analysis/validation.md` and the combined diff, then merges manually. The leader does not run git write operations — ever. (See memory: `feedback_git_handling.md`.)

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Investigator mis-classifies; fixers chase the wrong thing | Review gate 1 before any fixer spawns |
| Two fixers touch `agent.py` / `prompt.py` and clobber each other | File-collision lock via `addBlockedBy`, serialize |
| Replay cost blows up | Replay set capped at 15; one provider/model per validation run; budget ceiling per pane |
| LLM flakiness makes validation noisy | 3 runs per case, majority-rules scoring |
| A fixer's test passes but production behavior regresses | Golden set catches it; validator reruns golden set every pass |
| Mongo query pulls production PII into the repo | `analysis/dumps/*` is gitignored; only scrubbed taxonomy + replay set are tracked |
| Investigator is a bottleneck | Expected — accepted as the cost of evidence-based design |
| Stale doc: README says 25-iter budget but `core/agent.py:22` defaults to 100 | Flagged during investigation; a fixer can address it if the taxonomy justifies |

## Related projects: ouroboros-frontend

The Nuxt 3 chat UI lives in a sibling repo at `c:\Users\thier\ouroboros-frontend\`. It is the **I/O surface** for the ouroboros agent — WebSocket client, message rendering, live preview — but it is **not where stuck failures originate**. The agent loop, tool registry, prompt, and error recovery all live in `ouroboros-backend/core/` and `ouroboros-backend/tools/`. Fixes for agent quality do not require frontend changes.

**Frontend is explicitly out of scope for the fixers.** Fixers may not edit any file under `ouroboros-frontend/`.

**However, the investigator must rule out frontend-caused false positives.** A session can appear "stuck" in `db.chunks` while the frontend actually rendered an error state, or a WebSocket disconnect may have masked a completed-but-undelivered response. The investigator's classification must distinguish:

- **Genuine agent-stuck:** The agent's chunk stream shows a real dead end (hit max_iterations, unrecoverable tool error, repeated self-correction loop).
- **Frontend/transport artifact:** The backend session looks incomplete only because the WebSocket dropped, the user abandoned the tab, or a UI render bug hid the final message.

The latter class is filed in `analysis/frontend_followups.md` as a separate deliverable and **does not** drive fixer work in this team. If the count is non-trivial (>10% of stuck sessions), the leader raises it with the user as a follow-up team charter.

**Replay harness also bypasses the frontend.** The validator's replay driver calls the agent directly (via `core.agent.Agent.run` or the `/api/agent` WebSocket endpoint in a headless client), not through the browser. This isolates agent behavior from any frontend noise and keeps the replay deterministic.

## Out of scope

- New agent capabilities, new Pyth tools, new deploy targets.
- Frontend / Nuxt UI work (see **Related projects** above — strictly forbidden for fixers).
- Cost-optimization work that does not also address stuck sessions.
- Prompt rewrites for reasons unrelated to observed failure modes.
- Anything the investigator's data does not justify.

## Open questions to resolve in the plan

- Concrete mechanism for spawning and naming teammate panes (leader's responsibility during plan execution).
- Which MongoDB collection / query path the investigator uses for efficiency (full scan vs. indexed on `status`/`error_message`).
- Where the replay driver's isolated working directory lives on Windows (WSL path vs. native).
- Exact pytest invocation for fixers (pytest.ini already exists — reuse it).
