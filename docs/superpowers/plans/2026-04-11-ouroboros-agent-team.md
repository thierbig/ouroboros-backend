# Ouroboros Agent-Quality Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Important:** This plan is for a **leader orchestrator**, not a solo coder. Most of the actual code (analysis scripts, fixes, tests) is written by teammate agents spawned into psmux panes. Leader tasks are: scaffold the workspace, create the team, seed tasks, wait for teammate completion, run review gates, and review diffs. Orchestration tasks do not follow TDD — they are "setup → spawn → monitor → verify → gate" loops.
>
> **Never run git write commands.** User handles all git operations manually. Every task ends with "**STOP — user commits manually**" instead of a `git commit` step.

**Goal:** Spin up a multi-pane agent team that measurably reduces the ouroboros agent's "stuck / gave up" rate on real MongoDB-logged sessions, landing the result as a reviewable diff the user merges by hand.

**Architecture:** Fan-out/fan-in team in psmux mode. Phase 1 = 1 investigator pane mines `db.sessions` + `db.chunks`, produces taxonomy + replay set + baseline. Phase 2 = up to 5 fixer panes in parallel (with a file-collision lock on `core/agent.py` and `core/prompt.py`). Phase 3 = 1 validator pane reruns the replay set 3× per case and reports deltas. The leader is the user's existing Claude Code session and holds the shared task list.

**Tech Stack:** Python 3.11 (FastAPI backend), Motor (async Mongo), pytest, Claude Code `TeamCreate`/`TaskCreate`/`TaskList`/`TaskUpdate`/`SendMessage`, psmux on Windows.

**Spec:** `docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md` (the authoritative source for mission, success criteria, phase definitions, and review gates).

---

## File Structure

**Files the leader writes directly (this plan):**

| Path | Action | Responsibility |
|---|---|---|
| `.gitignore` | Modify | Exclude `analysis/dumps/` and `analysis/runs/` from git |
| `analysis/README.md` | Create | Directory layout so fresh teammates know where things go |
| `docs/superpowers/plans/2026-04-11-ouroboros-agent-team.md` | Already created | This plan |

**Files teammate agents write during execution (expected outputs, not leader code):**

| Path | Writer | Phase |
|---|---|---|
| `analysis/dump_stuck_sessions.py` | Investigator | 1 |
| `analysis/dumps/<session_id>.json` (gitignored) | Investigator | 1 |
| `analysis/taxonomy.md` | Investigator | 1 |
| `analysis/replay_set.json` | Investigator | 1 |
| `analysis/baseline.md` | Investigator | 1 |
| `analysis/replay_driver.py` | Investigator | 1 (reused by validator) |
| `analysis/frontend_followups.md` (conditional) | Investigator | 1 |
| `analysis/fixes/<bucket>.md` | Each fixer | 2 |
| `tests/test_*.py` (new) | Fixers | 2 |
| Diffs in `core/agent.py`, `core/prompt.py`, `tools/*.py`, etc. | Fixers | 2 |
| `analysis/runs/<case>_<run>.json` (gitignored) | Validator | 3 |
| `analysis/validation.md` | Validator | 3 |

**Files explicitly off-limits to fixers:** Anything under `c:\Users\thier\ouroboros-frontend\`. The investigator may read backend-side symptoms of frontend issues but files them under `analysis/frontend_followups.md` — no code edits to the frontend repo.

---

## Task 1: Scaffold the workspace (gitignore + analysis/README.md)

**Files:**
- Modify: `.gitignore`
- Create: `analysis/README.md`

- [ ] **Step 1.1: Add `analysis/dumps/` and `analysis/runs/` to `.gitignore`**

Open `.gitignore` and append the following block at the end of the file (after the HuggingFace section):

```
# Agent-quality team (2026-04) — raw session dumps and replay run outputs
# These contain potentially sensitive user prompts and generated code.
# The taxonomy, replay_set.json, and validation.md ARE tracked;
# only the raw per-session/per-run JSON blobs are ignored.
analysis/dumps/
analysis/runs/
```

- [ ] **Step 1.2: Verify the gitignore addition**

Run: `git status --short`
Expected: `.gitignore` shows as modified (`M .gitignore`). `analysis/` directory does not yet exist — this is correct; it's created implicitly when the investigator writes its first file. If you see the full `analysis/` dir already, something is out of order — stop and investigate.

- [ ] **Step 1.3: Create `analysis/README.md`**

Create the file `analysis/README.md` with exactly this content:

```markdown
# analysis/

Working directory for the ouroboros agent-quality team (see
`docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md`).

## Layout

| Path | Phase | Writer | Tracked in git? |
|---|---|---|---|
| `dump_stuck_sessions.py` | 1 | Investigator | Yes |
| `dumps/<session_id>.json` | 1 | Investigator | **No** (gitignored) |
| `taxonomy.md` | 1 | Investigator | Yes |
| `replay_set.json` | 1 | Investigator | Yes |
| `replay_driver.py` | 1 | Investigator | Yes |
| `baseline.md` | 1 | Investigator | Yes |
| `frontend_followups.md` | 1 | Investigator (if any) | Yes |
| `fixes/<bucket>.md` | 2 | Each fixer | Yes |
| `runs/<case>_<run>.json` | 3 | Validator | **No** (gitignored) |
| `validation.md` | 3 | Validator | Yes |

## Rules for teammates working in here

1. Read `../docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md`
   before writing anything. It is the authoritative spec.
2. Raw session dumps and replay runs are PII-adjacent. Do not commit them.
   Do not paste their contents into chat messages outside the team.
3. The frontend repo at `c:\Users\thier\ouroboros-frontend\` is off-limits
   to fixers. The investigator may only read it to rule out frontend-caused
   false positives; any findings go in `frontend_followups.md`.
4. `replay_set.json` and `baseline.md` are written once by the investigator
   and are treated as read-only by fixers. Only the validator reads them
   in Phase 3.
```

- [ ] **Step 1.4: Verify files**

Run: `git status --short`
Expected: `M .gitignore` and `?? analysis/README.md`.

- [ ] **Step 1.5: STOP — user commits manually**

Do not run `git commit` or `git add`. The user handles git themselves. Tell the user: "Task 1 done — `.gitignore` updated and `analysis/README.md` created. Commit when ready."

---

## Task 2: Load deferred tool schemas for orchestration

**Files:** None (tool-loading only)

The leader uses `TeamCreate`, `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, and `SendMessage` during orchestration. `TaskCreate`/`TaskUpdate`/`TaskList` may already be loaded from earlier in the session; `TeamCreate` and `SendMessage` are deferred tools that must be loaded via `ToolSearch` before first use.

- [ ] **Step 2.1: Load TeamCreate, TeamDelete, and SendMessage schemas**

Call `ToolSearch` with:
```
query: "select:TeamCreate,TeamDelete,SendMessage,TaskGet"
max_results: 5
```

Expected: 4 `<function>{...}</function>` definitions returned. After this call, all four tools are callable in subsequent turns.

- [ ] **Step 2.2: Verify the tools are usable**

No tool call needed — just confirm the schemas appeared in the ToolSearch result. If `TeamCreate` is missing from the response, rerun the ToolSearch with `query: "team create"` and `max_results: 3`.

---

## Task 3: Create the team and seed the Phase 1 (investigator) task

**Files:** None (orchestration only — tasks live in the shared task list, not on disk)

- [ ] **Step 3.1: Create the team**

Call `TeamCreate` with:
- name: `ouroboros-agent-quality`
- description: `Reduce the ouroboros agent's stuck-session rate via evidence-based fixes (Phase 1 investigator → Phase 2 fixers → Phase 3 validator). See docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md.`

Record the returned team identifier — all subsequent `TaskCreate`/`SendMessage` calls scope to this team.

- [ ] **Step 3.2: Seed the investigator task**

Call `TaskCreate` with the following fields:

**subject:** `[PHASE 1] Mine Mongo for stuck sessions, produce taxonomy + replay set + baseline`

**activeForm:** `Mining stuck sessions`

**description:** (copy verbatim into the task)

```
You are the INVESTIGATOR agent in the ouroboros-agent-quality team.

## First actions (do these in order)
1. Read the spec: docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md
2. Read analysis/README.md
3. Read core/agent.py, core/prompt.py, db/models.py, db/connection.py
4. Read README.md for the ouroboros project context

## Your mission
Produce ALL of the following deliverables under analysis/. Do NOT modify
any file outside analysis/. Do NOT propose or apply fixes — that is the
fixers' job.

### Deliverables

1. analysis/dump_stuck_sessions.py
   A standalone Python script that uses the existing db/ helpers (or a
   direct Motor client with MONGODB_URI from .env) to query:

   - sessions where error_message is set
   - sessions with chunks having status != "success" OR a non-null error
   - sessions where chunk count >= max_iterations and the final chunk has
     tool_calls (i.e., hit the wall without a terminal assistant message)
   - sessions where status == "running" but last_activity is >24h old

   For each match, write analysis/dumps/<session_id>.json containing the
   full session document plus all its chunks. These files are gitignored.

2. analysis/taxonomy.md
   A ranked list of failure modes. For each bucket, include:
   - Bucket name (short, hyphenated)
   - Definition (what makes a session land in this bucket)
   - Count
   - 3+ example session IDs
   - 1-2 illustrative chunk excerpts (trim prompts to <500 chars)
   - One-line hypothesis about the cause (not a fix proposal)

3. analysis/replay_set.json
   10-15 hard sessions covering the taxonomy. Each entry:
   {
     "session_id": "...",
     "initial_user_message": "...",
     "bucket": "...",
     "baseline_outcome": "stuck|error|abandoned",
     "notes": "..."
   }
   Pick cases that reliably reproduce stuckness — prefer repeatable failures
   over one-off flakes. Do NOT cherry-pick the easy ones.

4. analysis/replay_driver.py
   A standalone Python script that, given a session_id from the replay set,
   reconstructs initial conditions (isolated working directory, the same
   provider+model the original session used) and calls
   core.agent.Agent.run(initial_user_message, history=[]) to completion or
   failure. Writes the full event stream + timing + final status to
   analysis/runs/<session_id>_<run_idx>.json. Accepts --runs N (default 1)
   for replay multiplicity. The validator will reuse this script in Phase 3.

5. analysis/baseline.md
   Run replay_driver.py once per session in the replay set against current
   HEAD. Report a per-session pass/fail table and the aggregate pass rate.
   Also include a "golden set" of 5 sessions the agent currently handles
   well, measured the same way. Both sets are inputs to Phase 3 validation.

6. analysis/frontend_followups.md (CONDITIONAL)
   During classification, if you find sessions where the backend looks
   stuck but the real cause is frontend/transport (WS disconnect, UI render
   bug, abandoned tab), list them here. Do NOT file these in the taxonomy
   — the fixers won't touch frontend code. This file is a follow-up
   deliverable to raise with the user if it's non-trivial (>10% of stuck
   sessions).

## Hard constraints
- You may NOT modify any file outside analysis/
- You may NOT edit the frontend repo at c:\Users\thier\ouroboros-frontend\
- You may NOT propose fixes — one-line hypotheses only
- You may NOT commit; the leader tells the user when to commit
- Raw dumps under analysis/dumps/ are PII-adjacent — do not paste their
  contents in task comments or SendMessage calls

## Environment
- MONGODB_URI is in .env (already used by the backend)
- pytest.ini already exists at repo root — do not touch it
- The replay driver runs on Windows (psmux); isolated working dirs should
  live under a temp path like C:/Users/thier/ouroboros-temp/replay/<id>/
- Check the README.md claim of "25 iteration budget" vs core/agent.py:22
  (default max_iterations=100) — this discrepancy is interesting data, not
  something to fix

## Done criteria
All six deliverables exist, baseline.md has real numbers (not TBD), and
the replay driver has been smoke-tested against at least one replay-set
case. Mark this task completed via TaskUpdate and notify the leader
via SendMessage: "Phase 1 complete — ready for review gate 1."
```

- [ ] **Step 3.3: Assign the task (leave unassigned for now)**

Do not set an `owner`. The investigator pane will claim this task itself when it boots. Leaving it unowned is correct — the pane's first action is `TaskList` to find pending work.

- [ ] **Step 3.4: Verify the task is in the list**

Call `TaskList`. Expected: the PHASE 1 task appears with status `pending`, no owner, no `blockedBy`.

- [ ] **Step 3.5: Instruct the user to open the investigator pane**

Write exactly this message to the user (replace `<team-id>` with the actual team id from Step 3.1):

> Team created: `ouroboros-agent-quality` (id: `<team-id>`). Phase 1 task is seeded. Please open a new psmux pane and start a Claude Code teammate in it joined to this team. The teammate will pick up the Phase 1 task on its own. Let me know when the pane is open; I'll monitor for completion.

Wait for the user to confirm the pane is open before proceeding to Task 4.

---

## Task 4: Phase 1 — Monitor investigator, run review gate 1

**Files:** None directly; leader reviews the investigator's output under `analysis/`.

- [ ] **Step 4.1: Wait for the investigator to complete**

Poll by calling `TaskList` or `TaskGet` on the Phase 1 task. Do not aggressively poll — check back when the user tells you the pane has been idle, or when you receive a `SendMessage` from the investigator saying "Phase 1 complete — ready for review gate 1."

If the investigator goes quiet for more than 30 minutes with no status change, `TaskGet` the task and read any comments. If genuinely stuck, `SendMessage` the investigator asking for a status update rather than killing the pane.

- [ ] **Step 4.2: Verify all six deliverables exist**

Run these reads in parallel (one `Read` per file, one `Glob` for the dumps):

- `Read analysis/dump_stuck_sessions.py`
- `Read analysis/taxonomy.md`
- `Read analysis/replay_set.json`
- `Read analysis/replay_driver.py`
- `Read analysis/baseline.md`
- `Glob analysis/dumps/*.json` (expect ≥10 matches)
- `Read analysis/frontend_followups.md` (may not exist — that's fine)

Expected: the first five files exist and are non-empty. `dumps/` contains at least 10 JSON files.

- [ ] **Step 4.3: Run the taxonomy quality check**

Open `analysis/taxonomy.md` and verify:
- ≥3 distinct buckets
- Each bucket has a count, a definition, ≥3 example session IDs, and a one-line hypothesis
- Counts sum to a believable fraction of total stuck sessions (not 100% — some will be uncategorized or frontend-followup)
- No bucket is "miscellaneous" or "other" (≥30% of count) — that means classification is too coarse

If any of these fail, `SendMessage` the investigator with the specific gap and wait for a fix. Do not proceed to Phase 2 with a weak taxonomy.

- [ ] **Step 4.4: Run the replay set quality check**

Open `analysis/replay_set.json` and verify:
- 10-15 entries
- Buckets represented span the taxonomy (not all from one bucket)
- Each entry has all five fields: `session_id`, `initial_user_message`, `bucket`, `baseline_outcome`, `notes`
- `baseline_outcome` is one of `stuck|error|abandoned`

- [ ] **Step 4.5: Run the baseline sanity check**

Open `analysis/baseline.md`. Verify:
- Per-session pass/fail table is filled in
- Aggregate pass rate on the replay set is ≤20% (if it's higher, the "hard" cases aren't actually hard — send it back)
- Aggregate pass rate on the golden set is ≥80% (if it's lower, the golden set isn't actually golden — send it back)

- [ ] **Step 4.6: Human review gate 1**

Present to the user exactly this summary:

> **Phase 1 complete. Review gate 1.**
>
> - Taxonomy: N buckets, [list bucket names + counts]
> - Replay set: M sessions covering [list buckets]
> - Baseline: replay set passes X/M (Y%), golden set passes A/5 (B%)
> - Frontend followups: [count, or "none"]
>
> Please review `analysis/taxonomy.md` and `analysis/replay_set.json`. Approve to proceed to Phase 2, or tell me what to re-cut.

Wait for explicit user approval ("approved", "go", "proceed", etc.) before Task 5. If the user asks for re-cuts, `SendMessage` the investigator with the specific changes and loop back to Step 4.1.

- [ ] **Step 4.7: Close the investigator pane**

Tell the user: "Phase 1 done — you can close the investigator pane. I'm about to seed Phase 2 tasks."

---

## Task 5: Phase 2 — Seed fixer tasks with collision control

**Files:** None directly; leader creates tasks in the shared task list.

- [ ] **Step 5.1: Determine the fixer set from the taxonomy**

Open `analysis/taxonomy.md`. Count the buckets. Apply the spec's capping rule:
- If buckets > 5: merge the lowest-count buckets until exactly 5 remain. Note the merges in a task comment.
- If buckets ≤ 5: one fixer per bucket.

- [ ] **Step 5.2: Classify each fixer's expected file footprint**

For each fixer, predict which files it will touch based on the bucket's hypothesis. Reference this list:

- **Prompt-level fixes** → `core/prompt.py`
- **Agent-loop fixes (retry, iter budget, error recovery)** → `core/agent.py`
- **Tool error shaping** → specific `tools/*.py` file(s)
- **Tool registry / dispatch** → `core/registry.py`
- **New helper modules** → new file, no collision
- **Tests** → `tests/test_<bucket>.py` (new file per fixer, no collision)

Build a collision graph: if two fixers both list `core/agent.py` or `core/prompt.py`, they conflict. Collisions on the same `tools/*.py` or `core/registry.py` also count.

- [ ] **Step 5.3: Seed a fixer task per bucket**

For each fixer, call `TaskCreate` with:

**subject:** `[PHASE 2] Fix: <bucket-name>`

**activeForm:** `Fixing <bucket-name>`

**description:** (template — substitute `<bucket-name>` and `<predicted-files>`)

```
You are a FIXER agent in the ouroboros-agent-quality team, assigned to
the <bucket-name> failure mode.

## First actions (do these in order)
1. Read docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md
2. Read analysis/README.md
3. Read analysis/taxonomy.md — focus on YOUR bucket: <bucket-name>
4. Read analysis/dumps/ for sessions listed under your bucket
5. Read the predicted files: <predicted-files>

## Your mission
Ship a minimal, focused diff that addresses the <bucket-name> failure
mode. Write at least one test that would have failed before your fix.

### Scope rules (these are hard constraints)
- Touch ONLY files relevant to your bucket. No opportunistic refactors.
- No changes outside ouroboros-backend/. Frontend is OFF LIMITS.
- Do NOT touch analysis/replay_set.json or analysis/baseline.md — those
  are the validator's input.
- Do NOT touch any file another fixer is working on without first
  claiming a lock (see Collision rule below).

### Collision rule
If your bucket hypothesis points to core/agent.py or core/prompt.py
(the hot-spot shared files), TaskList to check whether another fixer
has already claimed a task touching that file. If yes, you are
BLOCKED — wait for that task to complete before starting yours. Tell
the leader via SendMessage: "Blocked on core/<file>.py, waiting for
task <other-task-id>."

### Deliverables
1. The minimal code diff, in the backend repo
2. At least one test under tests/ (new or extended file). The test must
   fail on current main and pass after your fix. Reuse existing pytest
   patterns — pytest.ini already exists.
3. analysis/fixes/<bucket-name>.md, containing:
   - 1-paragraph explanation of the change
   - Which replay_set.json sessions this targets
   - How to verify manually (commands + expected output)
4. Run pytest locally and paste the result in a task comment.

## Hard constraints
- No commits. Ever. The user handles git.
- No changes to MAX_ITERATIONS default without a strong taxonomy case.
  The README says 25 but core/agent.py:22 defaults to 100 — if your
  bucket hinges on this, say so explicitly in your fix.md.
- Do not rewrite the system prompt wholesale. Surgical additions only.
- No new dependencies in requirements.txt without the leader's approval.

## Done criteria
Diff is minimal and focused, test passes, analysis/fixes/<bucket-name>.md
is written, task comment contains the pytest output. Mark this task
completed via TaskUpdate and notify the leader via SendMessage:
"Fix ready for review: <bucket-name>."
```

- [ ] **Step 5.4: Apply collision locks via `addBlockedBy`**

From the collision graph in Step 5.2: for each pair of conflicting fixers, pick one to run first (arbitrary — the order doesn't matter as long as it's serialized). Call `TaskUpdate` on the second fixer with `addBlockedBy: ["<id-of-first-fixer>"]`. Repeat for every conflict pair.

Verify by calling `TaskList`: each blocked task should show the blocker in its `blockedBy` array. Independent fixers have empty `blockedBy`.

- [ ] **Step 5.5: Instruct the user to open fixer panes**

Count the independent (unblocked) fixers. Tell the user:

> Phase 2 tasks seeded. K fixers are unblocked and ready to run in parallel; the remaining (N-K) are serialized behind file-collision locks and will unblock automatically as earlier fixers complete. Please open K new psmux panes for parallel fixer teammates. I'll monitor and tell you when to open more panes as blocked tasks unblock.

- [ ] **Step 5.6: Monitor fixer panes**

Loop:
1. Call `TaskList`.
2. For each fixer task in `in_progress`: check if it's been updated recently (`TaskGet` to read comments).
3. For each fixer task in `completed`: proceed to Task 6 for that one fixer.
4. For each task that just unblocked (blocker went `completed`): tell the user "Pane for <bucket> now unblocked — open a new pane if you want to run it."
5. If a fixer reports via SendMessage that it's stuck, respond with specific guidance or ask the user to intervene.

Continue until all fixer tasks are `completed`.

---

## Task 6: Phase 2 — Review fixer diffs (soft gate)

**Files:** Whatever each fixer touched — reviewed one fixer at a time.

- [ ] **Step 6.1: Per fixer, verify scope compliance**

For each completed fixer, run `git status --short` and `git diff --stat` (read-only git, allowed). Verify:
- Files touched are consistent with the fixer's task description (its `<predicted-files>` + new tests + `analysis/fixes/<bucket-name>.md`)
- No files in `ouroboros-frontend/` were touched
- No `analysis/replay_set.json` or `analysis/baseline.md` edits
- No unrelated file edits (e.g., `requirements.txt` unexpectedly bumped)

If scope was violated, `SendMessage` the fixer asking for a revert of the out-of-scope changes, and wait for them to redo. Do not unilaterally revert — let the fixer correct.

- [ ] **Step 6.2: Per fixer, verify test existence**

Verify the fixer's new test file exists, and that `pytest tests/test_<bucket>.py -v` passes. If it doesn't, `SendMessage` the fixer with the failure output.

- [ ] **Step 6.3: Per fixer, verify `analysis/fixes/<bucket>.md` exists**

`Read analysis/fixes/<bucket>.md`. It must have a non-empty explanation, a list of targeted replay sessions, and a manual-verification command. If any of these are missing, send it back.

- [ ] **Step 6.4: After all fixers pass review, close the panes**

Tell the user: "All Phase 2 fixers done. You can close the fixer panes. I'm about to seed Phase 3 (validator)."

---

## Task 7: Phase 3 — Seed the validator task

**Files:** None directly; leader seeds the validator task.

- [ ] **Step 7.1: Seed the validator task**

Call `TaskCreate` with:

**subject:** `[PHASE 3] Run replay harness, emit validation.md, check success criteria`

**activeForm:** `Validating replay set`

**description:** (copy verbatim)

```
You are the VALIDATOR agent in the ouroboros-agent-quality team.

## First actions (do these in order)
1. Read docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md
   (focus on Phase 3 and Success criteria)
2. Read analysis/README.md
3. Read analysis/replay_set.json
4. Read analysis/baseline.md
5. Read analysis/fixes/*.md to understand what changed

## Your mission
Rerun the replay set against current HEAD (post-fixer main) and emit
analysis/validation.md with a pass/fail verdict against the spec's
success criteria.

## Steps

1. For each session in analysis/replay_set.json:
   - Run analysis/replay_driver.py with --runs 3
   - Collect the three run outcomes from analysis/runs/<id>_<0..2>.json
   - Mark the case PASS if ≥2 of 3 runs finished cleanly (no error,
     reached a terminal assistant-without-tool-calls message)

2. Rerun the 5-session golden set the same way, 3 runs each, same
   majority-rules scoring.

3. Emit analysis/validation.md with:
   - Per-case table: session_id, bucket, baseline outcome, post-fix
     outcome, verdict (PASS/FAIL/NOISY)
   - Replay set aggregate: X/M cases passing (Y%)
   - Golden set aggregate: A/5 cases passing (B%)
   - Cost delta: total cost of 3x replay run vs. baseline 1x cost
   - Iteration-count delta: median iterations per case vs. baseline
   - Explicit check against each spec success criterion 1-5:
     - Criterion 1 (taxonomy exists): N/A — already verified at gate 1
     - Criterion 2 (replay set exists): N/A — already verified at gate 1
     - Criterion 3 (≥60% success rate, stretch ≥75%): PASS/FAIL with numbers
     - Criterion 4 (no regression on golden set): PASS/FAIL with numbers
     - Criterion 5 (reviewable diff): N/A — leader verifies

4. If criterion 3 or 4 fails, add a "Failure analysis" section naming
   which fixers' changes are implicated (cross-reference against
   analysis/fixes/*.md) and file a new TaskCreate:
   "[PHASE 2 REDO] Re-fix <bucket-name>"
   with a description of what broke and which replay cases regressed.
   Do NOT attempt to fix it yourself.

## Hard constraints
- Do NOT modify any source file outside analysis/
- Do NOT commit
- Run all three replays per case, even if the first one fails — the
  spec requires majority-rules scoring over 3 runs
- Use ONE provider/model combination across all runs for comparability
  (match whatever baseline.md used)

## Done criteria
analysis/validation.md exists with per-case table, aggregates, and
explicit criterion checks. Mark this task completed via TaskUpdate and
notify the leader via SendMessage: "Phase 3 complete — ready for
review gate 2."
```

- [ ] **Step 7.2: Instruct the user to open the validator pane**

Tell the user:

> Phase 3 task seeded. Please open a new psmux pane for the validator teammate. It will rerun the replay set 3× per case (so this phase is the longest — expect it to take a while). I'll monitor and run review gate 2 when it finishes.

- [ ] **Step 7.3: Monitor the validator**

Same pattern as Task 4.1 — don't over-poll. Wait for `SendMessage` from the validator or a user prompt. `TaskGet` for status when checking in.

---

## Task 8: Review gate 2 — final diff presentation

**Files:** Read-only review of everything produced by the team.

- [ ] **Step 8.1: Verify validator deliverables**

Read:
- `analysis/validation.md` (must exist, must have criterion 3 and 4 verdicts)
- `Glob analysis/runs/*.json` (must have 3 × replay_set_size + 3 × 5 golden entries)

- [ ] **Step 8.2: Decide outcome**

Three possible paths from the validation:

**Path A — All criteria pass.** Proceed to Step 8.3.

**Path B — Criterion 3 fails (success rate <60%).** The validator should already have filed a PHASE 2 REDO task. Loop back to Task 5 Step 5.3 *for that one fixer only*, targeting the specific failing replay cases. When the redo fixer is done, return to Task 7 and rerun the validator.

**Path C — Criterion 4 fails (golden set regressed).** Identify which fixer's change caused the regression from the validator's failure analysis. Loop back to Task 5 for that fixer with the regression as context. Return to Task 7 after the redo.

- [ ] **Step 8.3: Final combined diff presentation**

Run `git status --short` and `git diff --stat main` to get the combined footprint. Present to the user:

> **Phase 3 complete. Review gate 2 — final.**
>
> **Replay set result:** X/M passing (Y%) — spec requires ≥60%, stretch ≥75%. [PASS/FAIL]
>
> **Golden set result:** A/5 passing (B%) — spec requires no regression. [PASS/FAIL]
>
> **Cost delta per case:** [from validation.md]
>
> **Combined diff footprint:** [files touched, lines added/removed from git diff --stat]
>
> Full report in `analysis/validation.md`. Combined diff is staged for your review. **I will not commit or merge.** When you're ready, commit and merge manually.

- [ ] **Step 8.4: Close the team**

After the user acknowledges the final review (merged or deferred), tell the user: "Validator pane can be closed. Team `ouroboros-agent-quality` is done. The shared task list remains for reference — I can `TeamDelete` it if you want a clean slate."

Do not `TeamDelete` unless the user asks. The task history may be useful for a retro.

- [ ] **Step 8.5: STOP — user commits manually**

Final reminder: do not run `git commit`, `git push`, `git add`, `git merge`, or any other git write command. Ever. The user does all git operations.

---

## Self-Review Results

**Spec coverage check:**

| Spec requirement | Plan task |
|---|---|
| Mission (reduce stuck rate) | Implicit across all tasks; explicit in Task 7 validator criteria |
| Stuck session definition (4 cases) | Task 3 Step 3.2 investigator brief, verbatim |
| Success criterion 1 (taxonomy) | Task 3 + Task 4 Step 4.3 |
| Success criterion 2 (replay set) | Task 3 + Task 4 Step 4.4 |
| Success criterion 3 (≥60% stretch 75%) | Task 7 + Task 8 Step 8.2 |
| Success criterion 4 (no golden-set regression) | Task 7 + Task 8 Step 8.2 Path C |
| Success criterion 5 (reviewable diff, user merges) | Task 8 Step 8.3 + "STOP, user commits" on every task |
| psmux execution mode | Task 3 Step 3.5, Task 5 Step 5.5, Task 7 Step 7.2 |
| Leader = user's existing CC session | Plan header |
| 7-pane peak | Task 5 Step 5.5 (notes parallel K + serialized N-K) |
| Phase 1 investigator deliverables (6 items) | Task 3 Step 3.2 (verbatim list) |
| Phase 2 fixer contract | Task 5 Step 5.3 (verbatim template) |
| Phase 2 file-collision rule | Task 5 Steps 5.2 + 5.4 |
| Phase 3 validator contract | Task 7 Step 7.1 (verbatim template) |
| Review gate 1 | Task 4 Step 4.6 |
| Per-fixer diff review (soft gate) | Task 6 |
| Review gate 2 | Task 8 Step 8.3 |
| Frontend off-limits for fixers | Task 5 Step 5.3 template + analysis/README.md Task 1.3 |
| Investigator rules out frontend false positives | Task 3 Step 3.2 (frontend_followups.md) |
| Replay harness bypasses frontend | Task 3 Step 3.2 (calls `core.agent.Agent.run` directly) |
| `analysis/dumps/` + `analysis/runs/` gitignored | Task 1 Step 1.1 |
| User handles git | Every task ends with "STOP — user commits manually" |

No gaps.

**Placeholder scan:** No TBD/TODO/placeholder strings. All templates are filled in verbatim. Every step that asks for a decision (fixer count, collision graph, review gate verdict) defines the decision criteria explicitly.

**Type/name consistency:** `TeamCreate`, `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `SendMessage` are used consistently. `analysis/replay_set.json` schema is defined once in Task 3 and referenced (not redefined) in Tasks 5, 7. `analysis/taxonomy.md` structure is defined once in Task 3 and referenced in Task 4.3 and 5.1.

**Scope check:** Plan is one phase chain (1→2→3) with one review cycle per phase. It produces a working, testable improvement on its own. No decomposition needed.

Self-review passes.
