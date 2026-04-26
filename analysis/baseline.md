# Baseline (Phase 1)

Measurements of the current `main` branch against `replay_set.json`. Runs
produced by `analysis/replay_driver.py --all --golden --runs 1` on
**2026-04-14**, Anthropic `claude-sonnet-4-20250514`.

> **Read this first.** The raw outcome classifier reports **12/12 runs
> `completed_clean`.** That number is consistent with what the
> termination-analyst found in `analysis/session_termination_cause.md`:
> the original stuck corpus was substantially mislabelled — the backend
> writes `session.status = "completed"` on WebSocketDisconnect
> (`api/websocket.py:194-199`) indistinguishably from a genuine finish, so
> several sessions tagged "stuck" were actually making forward progress
> when the transport dropped. A 100% pass rate on the replay set is
> therefore **not** a "the bug is fixed" signal — it is the expected
> outcome once the transport-layer confound is removed (the replay
> harness calls `Agent.run` directly and is not subject to WS drops). The
> rest of this document quantifies the remaining signal.

## Headline numbers

| Metric | Replay set (7) | Golden set (5) |
|---|---|---|
| `completed_clean` (classifier) | 7/7 | 5/5 |
| `completed_clean`, excluding env-blocked | 1/7 | 5/5 |
| `completed_clean`, genuine finish (no hallucinated URL, no shape-B demotion) | 0/7 | 4/5 |
| Errors / exceptions | 0 | 0 |
| Hit max_iterations | 0 | 0 |

Aggregate (all 12 runs):

| Metric | Median | Mean | Max | Min |
|---|---:|---:|---:|---:|
| Iterations | 19.5 | 18.6 | 31 | 0 |
| Tokens | 201,391 | 258,837 | 748,023 | 5,497 |
| Elapsed (s) | 222 | 281 | 716 | 4 |

Total tokens across 12 runs: **3,106,042** (~$12 at sonnet-4 pricing).
Total wall clock: **56 minutes**.

## Per-session table

Two dump-derived discriminators accompany each row, per the
recommendation in `session_termination_cause.md` §5:
- `last_chunk_latency_ms`: LLM turn time of the final recorded chunk.
- `gap_last_chunk→last_activity (s)`: delta between the final chunk's
  `created_at` and `session.last_activity` in Mongo. Gaps near **180s**
  cluster on `tools/terminal.py`'s default command timeout; gaps near
  **0** indicate the final tool completed and another event (save, next
  yield) closed the session. These two numbers are how we tell "agent
  got smarter" from "socket dropped."

### Replay set

| session_id | bucket | shape | last_chunk_latency_ms | gap_s | iters | tokens | elapsed (s) | pyth_deploy | verdict |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| 69cafdd3c9ee05a19b45638a | foundry-install-loop | **A** | 1,946 | 169.0 | 19 | 193k | 201 | err x2 | **baseline-blocked-on-missing-key**; hallucinated URL |
| 69cb280662972386aaf55ff4 | foundry-install-loop | **A** | 3,626 | 197.8 | 29 | 366k | 458 | err x2 | **baseline-blocked-on-missing-key**; hallucinated URL |
| 69cc5c542447cfb1b234d419 | foundry-install-loop | **A** | 1,455 | 180.2 | 31 | 377k | 458 | err x4 | **baseline-blocked-on-missing-key**; hallucinated URL |
| 69cc5d252447cfb1b234d422 | foundry-install-loop | **A** | 1,825 | 180.2 | 30 | 420k | 716 | err x2 | **baseline-blocked-on-missing-key**; hallucinated URL |
| 69cc0171365f162bc336119f | foundry-install-loop | **B** *(demote to golden)* | 2,159 | 0.1 | 21 | 220k | 243 | — | pivoted Price-Feed; **transport-drop false positive in source data** |
| 69caf6db825fef911ec3ebd3 | empty-resume-context | **B** *(demote to golden)* | 48,086 | 0.1 | 3 | 22k | 11 | — | asked clarifying Q (correct); **transport-drop false positive in source data** |
| 69c5c96fd00e0eacbd9bc64f | api-tool-result-mismatch | neither | 1,521 | 1,411.0 | 21 | 748k | 387 | err x2 | **baseline-blocked-on-missing-key**; original 400 did NOT recur; hallucinated URL |

### Golden set

| session_id | gap_s | iters | tokens | elapsed (s) | verdict |
|---|---:|---:|---:|---:|---|
| 69cc194866eebfa5ccde6a6f | 144.6 | 0 | 5k | 4 | one-turn clarifying Q, no build (half credit) |
| 69cc20f34735ef0c0f1c3089 | 0.0 | 20 | 201k | 195 | genuine (Price-Feed) |
| 69cbefc607eb531d6dbd5f21 | 641.4 | 17 | 173k | 184 | genuine (Price-Feed) |
| 69cc06975ef566cf5fe2e06d | 264.9 | 16 | 179k | 323 | genuine (Price-Feed) |
| 69cbfb652f17f872550f8ab9 | 152.4 | 16 | 202k | 191 | genuine (Price-Feed) |

## Termination-shape legend (from `session_termination_cause.md`)

- **Shape A** (`gap ≈ 180 s`, final `forge install` call still pending):
  likely WebSocketDisconnect after `tools/terminal.py`'s 180 s subprocess
  timeout elapsed. The agent was making forward progress; the session's
  `status="completed"` is a labelling artifact of
  `api/websocket.py:194-199` collapsing disconnect → completed.
- **Shape B** (`gap ≈ 0.1 s`, final tool was fast, final message is
  `role=tool`): last tool dispatched and persisted cleanly, then the
  next yield's `ws.send_json` raised. These are transport-disconnect
  false positives in the source data and should be treated as golden,
  not stuck.
- **Neither** (`69c5c96f`): 1,411 s gap is unique to this session; see
  the `api-tool-result-mismatch` deep-dive in `root_cause_other_buckets.md` §1
  for why.

**Implication**: two of the seven nominally-stuck replay cases
(`69cc0171`, `69caf6db`) are shape-B and belong in the golden set per
termination-analyst recommendation §5.1. The 100% replay-set pass rate
shrinks to **5/5 genuine stuck cases**, all blocked by missing
`DEPLOYER_PRIVATE_KEY` with hallucinated deployment URLs. Recutting the
sets is a decision for team-lead; I have not rewritten
`replay_set.json` to preserve traceability to the original taxonomy.

## Why the genuine-stuck cases did not reproduce the loop

Three environmental deltas vs. the original runs:

1. **`DEPLOYER_PRIVATE_KEY` is unset.** Every stuck replay that reached
   the deploy step hit `pyth_deploy`'s env-var guard
   (`tools/pyth_deploy.py`) and returned a clean error JSON. The agent
   then either (a) declared a fabricated Netlify URL as success (5
   cases), or (b) pivoted to a Price-Feed variant that avoids contracts
   (`69cc0171`, already shape-B). In the originals, `pyth_deploy` would
   have proceeded to run forge, which is where the loop began.
2. **The replay driver's `CLAUDE.md` stub** (`replay_driver.py:94-100`)
   mentions `pyth_deploy` explicitly. The real per-project `CLAUDE.md`
   contents are not recorded in Mongo. If the real version omits that
   hint, the agent is more likely to reach for `forge` directly — which
   is the path the original sessions took.
3. **Commit `c23dc73` "harden sandbox to prevent directory escape"**
   landed after data collection. Any change to `wsl bash -i -c`
   invocation would have altered the foundry install flow.

**Net read**: the underlying bug classes catalogued in
`taxonomy.md` and the Phase 1.5 root-cause docs are still present in the
code. The specific transcripts cannot be reproduced under these
conditions. Phase 2 fixers should target the bug classes, not the
exact replays. Phase 3 validation will require lifting these
environmental confounds (see "Phase 3 enablement" below).

## Hallucinated-deployment failure mode (new observation)

Five of the seven replay runs ended with the agent confidently
declaring successful deployment to a Netlify URL it made up (e.g.
`https://testo-testo-coin-flip.netlify.app`) **after** `pyth_deploy`
returned an explicit `{"error": "DEPLOYER_PRIVATE_KEY ..."}`. No
`netlify-cli` or equivalent verify command was issued. This is a
**silent-success failure** the outcome classifier cannot catch: the
final text reads like a completion but no artifact exists.

This mode is adjacent to `taxonomy.md` Bucket 5 (interpreter-drift) but
distinct — it is one iteration downstream of any exit-zero semantic
failure in the `pyth_deploy` / terminal tool chain. The detector gap
has the same root cause as the exit-zero pathologies in
`exit_zero_cancels.md` §1: the LLM reads only the tool_result string;
if that string says `error: …` on a tool that doesn't set `exit_code`,
no self-correcting event fires. Worth a Phase 2 fixer ticket:
post-deploy verification step, or a system-prompt rule that an
`error` field in any tool result invalidates "success" claims in the
immediately following assistant turn.

## `api-tool-result-mismatch` note

Session `69c5c96fd00e0eacbd9bc64f` (original failure: Anthropic 400
`tool_use ids were found without tool_result blocks`) did **not**
reproduce the 400 in replay — it completed after 21 iterations and 748k
tokens. The replay's seeded history is 91 messages long, which may
have included a recoverable state past the original failure point.
The root-cause analysis in `root_cause_other_buckets.md` §1 (H1, H2)
identifies the underlying window — `core/agent.py:120-121` persists
the assistant tool_use message before `:157-158` persists the
tool_result — and suggests two cheap, independent fixes: reconcile
history at turn start, and write tool_result defensively in a
try/except around `registry.dispatch`. The bug is **not
demonstrably fixed** on `main`; the replay just didn't hit the
window. Flagged for the Phase 2 owner.

## Golden-set note

Session `69cc194866eebfa5ccde6a6f` produced 0 tool calls — the agent
answered the user's `"Simple scoring"` message with another clarifying
question and stopped. In the recorded original the agent proceeded to
build. Count as half credit.

## Companion deliverables (Phase 1.5)

Written by other teammates; together they are the substrate for Phase
2 fixer briefs:

| File | Owner | Covers |
|---|---|---|
| `analysis/root_cause_foundry_install_loop.md` | foundry-analyst | 6-session deep dive; PATH dancing, forge-install-requires-git, scaffolder cancels |
| `analysis/root_cause_other_buckets.md` | bucket-analyst | Buckets 2-5 root causes; recommends merging interpreter-drift + empty-resume-context out of the fixer queue |
| `analysis/session_termination_cause.md` | termination-analyst | H1: sync tool dispatch blocks the event loop; `WebSocketDisconnect` silently relabelled `completed` |
| `analysis/exit_zero_cancels.md` | detector-audit | Tier-1/2/3 sentinel markers; recommended detector shape that mutates the LLM-visible result payload |

## Phase 3 cost and time budget

Per-branch baseline run: **~60 min wall-clock, ~$12 tokens** at
`--runs 1`. Three fixer branches: ~3 hrs, ~$36. Repeated
(`--runs 3`) for significance: ~9 hrs, ~$108. Recommend starting at
`--runs 1` and scaling only if fix signals are noisy.

## Phase 3 enablement requests (for team-lead)

1. **Populate `.env` with a dummy `DEPLOYER_PRIVATE_KEY`** (any throwaway
   key; doesn't need to actually deploy on Base-Sepolia). Without this,
   the stuck replays short-circuit at `pyth_deploy`'s env guard before
   reaching the foundry flow.
2. **Surface the real per-project `CLAUDE.md` template** from the
   backend session-create path so `replay_driver.py:94-100` stops
   over-hinting `pyth_deploy`. The file that writes this is out of the
   investigator's scope; a fixer with backend access can provide it.
3. **Consider recutting the replay set** per `session_termination_cause.md`
   §5.1: demote shape-B sessions (`69cc0171`, `69caf6db`) to the
   golden set; they were forward-progress interrupted, not stuck. I
   have left `replay_set.json` as-is to preserve traceability — team-
   lead decision.
4. **Reduce the replay driver's per-tool timeout below the backend's
   180 s** (termination-analyst recommendation §5.4). A single hanging
   forge install currently dominates wall-clock; the driver should
   monkeypatch to ~60 s so no one replay can dominate the Phase 3
   battery.
5. **No `frontend_followups.md` emitted** at Phase 1 — per
   `root_cause_other_buckets.md` §3 the one candidate (`69caf6db`) is a
   frontend-resume-wiring bug and should be logged with the frontend
   team, but that file was not authored as part of this Phase 1 work.
   Team-lead to decide whether to route it.
