# Root cause: remaining 4 taxonomy buckets

Analyst deliverable for Phase 1.5. Covers every bucket in
`analysis/taxonomy.md` **other than** `foundry-install-loop` (which has its
own deep-dive at `analysis/root_cause_foundry_install_loop.md`). Sources: the
taxonomy, the session dumps under `analysis/dumps/` named per bucket, and
the backend code at `core/agent.py`, `core/prompt.py`, `tools/terminal.py`,
`api/websocket.py` on `main` as of commit `c23dc73`.

One important corpus note up front: the WSL terminal shim was added in
commit `edaae32` on 2026-04-01. Sessions dated **before** that (notably
`69c5c96f…` on 2026-03-27) ran commands on the host Windows shell, not WSL.
Several of the behaviors tagged "interpreter drift" below are actually the
agent *correctly* adapting to a pre-WSL environment, not agent
misbehavior — called out in §4.

---

## 1. `api-tool-result-mismatch` (1 session)

### 1.1 Trigger

One session: `69c5c96f…`, a 41-chunk / $2.54 Entropy coin-flip project.
Triggering event is not the initial user prompt — the session starts from
the same scaffold template that drives the foundry bucket. The mismatch
appears at message index 32, partway through scaffolding: the agent emits
an assistant message with `tool_calls=[{id:"toolu_01L7ExZhZQGj1NFNhEQ7YwPt",
name:"terminal", args:{command:"bun add react react-dom vite @vitejs/plugin-react ..."}}]`,
and the **next message in the persisted history is a plain `{role:"user",
content:"u got stuck it seems"}`** — no `{role:"tool", tool_call_id: "toolu_01L7…"}`
in between.

Every LLM call from that point on 400s on
`messages.32: tool_use ids were found without tool_result blocks immediately
after: toolu_01L7ExZhZQGj1NFNhEQ7YwPt`.

### 1.2 Loop anatomy

Persisted messages #32–#34 (verbatim, shortened):

```
[32] assistant tool_calls=[{id:"toolu_01L7ExZhZ…", name:"terminal",
     args:{"command":"bun add react react-dom vite ..."}}]
[33] user "u got stuck it seems"
[34] user "[SYSTEM] LLM call failed: BadRequestError: 400 -
     'messages.32: tool_use ids were found without tool_result blocks
     immediately after: toolu_01L7ExZhZ…'. Try to continue your task…"
[35] user "[SYSTEM] LLM call failed: 400 - toolu_01L7ExZhZ… …"
[36] user "[SYSTEM] LLM call failed: 400 - toolu_01L7ExZhZ… …"
… 25 more identical [SYSTEM] retries (one per LLM call) …
```

27 consecutive `[SYSTEM] LLM call failed` retries, each one spending
`total_tokens` re-submitting the same broken history to Anthropic and
pocketing the same 400 back. The loop ate ~$2.30 of the session's $2.54.

### 1.3 Root hypothesis

Two orthogonal agent-loop bugs chain together.

**(H1) The assistant tool_use message is persisted before its tool_result
exists.** `core/agent.py:120–121` appends `assistant_msg` (including
`tool_calls`) to `history` *before* any tool is dispatched. The per-tool
`history.append(tool_msg)` happens inside the for-loop at
`core/agent.py:157–158`. Between those two lines, three things can leave
the history dangling:

1. The WS client disconnects or the backend raises — the `WebSocketDisconnect`
   handler at `api/websocket.py:194–198` unconditionally `update_session_messages`
   with the *current* `messages_history`, freezing the orphan tool_use into
   Mongo.
2. Incremental save at `api/websocket.py:178–180` only fires on
   `tool_result` events — so the window "assistant tool_call persisted,
   tool_result not yet" is bounded but not zero; a crash in
   `registry.dispatch` (line 127) within that window persists the orphan.
3. A new user message arrives at `api/websocket.py:86` *after* a session
   that ended mid-tool-call — the handler does not reconcile history,
   just calls `agent.run(user_content, messages_history)` which appends
   the user message at `core/agent.py:50`, producing the exact
   `assistant(tool_use) → user(text)` sequence the API rejects.

The last path fits this session: `last_activity` is ~4 days after
`created_at`, and message #33 reads like a fresh user turn after a
reconnect, not an LLM output. The user hit "send" on a session whose
persisted history already had an orphan tool_use from a prior
disconnect.

**(H2) Self-correction on LLM failure compounds the problem instead of
healing it.** When the LLM call raises, `core/agent.py:82–92` appends
*another* `{role:"user", content: "[SYSTEM] LLM call failed: …"}` to
`messages`/`history` and continues. That does nothing to repair the
orphan; it just grows the user-message tail. Every subsequent iteration
re-sends the same broken prefix and the same orphan tool_use at index
32 — so the retry is deterministic. The loop only stops when
`max_iterations=100` is reached (this session burned ~27 retries before
some other terminating condition, likely a WS-side timeout, kicked in).

### 1.4 What a fix would look like

Two independent, small changes:

- **Reconcile history at turn start.** Before `history.append(user_msg)`
  in `core/agent.py:50`, scan the tail of `history` for any assistant
  message whose `tool_calls` ids are not all followed by a matching
  `{role:"tool", tool_call_id: …}`. Synthesize
  `{role:"tool", tool_call_id: <id>, content: "[interrupted: no result
  recorded]"}` for each missing one. Same reconciliation should run in
  `api/websocket.py` on the "resume" path (line 70–84) and on the
  mid-stream save path (line 178–180) — any code that re-hydrates
  `messages_history` into a new agent call is a correct place to heal.
- **Write the tool_result row defensively.** In
  `core/agent.py:124–158`, wrap the `registry.dispatch` call in `try:
  … except Exception as e: result = json.dumps({..., "error": str(e)})`,
  and then *always* append the `tool_msg` with that error content. That
  closes the in-process window even without reconciliation.

The reconciliation fix is broader and covers the multi-turn /
cross-restart case; the defensive write is a one-file change that
catches the crash-in-dispatch case. Both are cheap; ship both.

### 1.5 Open questions

1. Was this session's dangling `toolu_01L7ExZhZ…` caused by a WS
   disconnect mid-dispatch, or by a subsequent user turn appended on top
   of an already-broken history? The `last_activity` delta suggests the
   latter, but Mongo doesn't record per-chunk timestamps against
   message-index boundaries, so a replay of the exact scenario is the
   only way to be sure.
2. When the reconciler synthesizes a tool_result, what content yields the
   best agent recovery? "[interrupted: no result recorded]" vs.
   "[tool_error: retry the command]" vs. showing the args back to the
   agent. Needs an A/B on the replay set.
3. Does Sonnet actually recover from a synthesized "[interrupted]"
   tool_result, or does it restart scaffolding from scratch (eating
   iterations)? If restart-from-scratch dominates, the reconciler
   should probably prepend a user message explaining *why* the
   interrupt happened so the agent can skip already-completed steps.

---

## 2. `bun-vite-scaffold-fallback` (2 sessions)

### 2.1 Trigger

Both sessions (`69cc0171…` Price Feeds memory game, `69c5c96f…` Entropy
coin flip) follow the same template prompt and both reach a point where
the agent tries `bun create vite . --template react` against a directory
that already contains `CLAUDE.md`, `tasks/todo.md`, `tasks/lessons.md`,
and (in `69c5c96f`) a `bun init`-generated `package.json`/`index.ts` from
a few iterations prior.

### 2.2 Loop anatomy

From `69cc0171…`, steps #11–#17 (`69c5c96f` shows the same pattern at a
different chunk index, also cross-referenced under foundry-loop Excerpt D):

```
[11] terminal: bun create vite . --template react
[12] tool: exit=0 stdout="└  Operation cancelled\n\n" stderr="Resolving..."
[13] terminal: bun install
[14] tool: exit=1 stderr="Bun could not find a package.json file to install from"
[15] terminal: bun init -y        # ← prompt.py:24 explicitly forbids this
[16] tool: exit=0 (writes package.json, index.ts, tsconfig.json)
[17] terminal: rm -rf * && bun create vite . --template react
[18] tool: exit=0 stdout="└  Operation cancelled\n\n"
[19 → 30] write_file: package.json, vite.config.js, index.html, main.jsx, ...
```

Two signatures to notice:

- `bun create vite` exits **zero** when it can't prompt, emitting
  `└  Operation cancelled` on stdout. The agent can't tell from the
  tool_result that anything failed.
- `rm -rf *` at step 17 is a glob that skips dotfiles (`.gitignore`,
  `CLAUDE.md` is not dotfile but survives a re-read, `bun.lock` survives,
  `tsconfig.json` survives). The prompt at `core/prompt.py:23`
  prescribes `rm -rf .[!.]* * 2>/dev/null` specifically to handle this,
  but the agent drops the dotfile glob in practice.

### 2.3 Root hypothesis

Three agent-facing problems, ranked by effect size.

**(H1) Exit-zero-but-cancelled is invisible to the self-correcting
signal.** `core/agent.py:141–149` only yields a `self_correcting` event
when `stderr and exit_code != 0`. `bun create vite`'s cancel path fails
both conditions — stdout contains the "cancelled" sentinel, exit_code
is 0, and stderr contains only progress noise (`"Resolving..."`). The
agent sees a clean exit and proceeds, which is why it takes a step or
two to realize scaffolding didn't happen (usually only after the next
`bun install` fails). This is the same signal the termination-analyst
is investigating under task #5.

**(H2) The prompt's `bun create vite` guidance is not sticky under
failure.** `core/prompt.py:23–24` forbids `bun init` before `bun create
vite`, and prescribes the `rm -rf .[!.]* *` recipe for clearing the
directory. Both sessions violate both rules (`69cc0171` runs `bun init`
then tries `bun create vite`; `69c5c96f` runs `bun init` *first*). The
rules are buried mid-bullet in a list item about `terminal` and don't
carry enough weight against "oh, the scaffolder cancelled, let me try
something else" — same sticky-prompt problem flagged in foundry-loop §3
H2. A more declarative block with its own heading ("## Scaffolding a
new Vite project") would probably stick better than an inline bullet.

**(H3) The fallback is a feature, not a bug.** Once the agent gives up
on `bun create vite`, it writes `package.json`, `vite.config.js`,
`index.html`, `src/main.jsx` by hand and the resulting project works.
In `69cc0171` the fallback reaches `bun run dev` and a runnable app
before the session ends; in `69c5c96f` the fallback cohabits with the
api-tool-result-mismatch bug covered in §1, which is why it gets
counted as stuck rather than recovered. **The bug tagged by the
taxonomy is really "scaffolder silent-cancels," not "agent can't
scaffold"** — the fallback path is working.

### 2.4 What a fix would look like

Three candidates, in order of cheapness:

- Widen the self-correction detector at `core/agent.py:141–149` to flag
  stdout-sentinel failures: specifically the string
  `"Operation cancelled"` in a `bun create vite` result. Terminal tool
  could also emit a structured flag so the agent doesn't need to pattern-
  match on free-form stdout.
- Prefer manual scaffold. Add a short prompt block (under a dedicated
  "## Scaffolding" heading) instructing the agent to skip
  `bun create vite` entirely and write `package.json` + `vite.config.js`
  + `index.html` + `src/main.jsx` directly. This is what the fallback
  already does successfully; making it the default path skips a failure
  mode.
- Harder, slower: pre-seed the project directory without `CLAUDE.md` /
  `tasks/` at the root, so `bun create vite` doesn't see them. But
  `CLAUDE.md` injection is load-bearing for the system prompt at
  `core/prompt.py:146–153`, so this trades one problem for another.

### 2.5 Open questions

1. Is `└  Operation cancelled` stable across bun versions? The sessions
   observed `1.3.11`. A regex detector could drift; a stdout-sentinel
   detector is only as good as bun's UX choices.
2. Is there a way to pass the `bun create vite` CLI a non-interactive
   flag that actually produces a scaffold instead of cancelling?
   `--yes` is not respected here. If no such flag exists, "prefer
   manual" is the right long-term answer.
3. Should the prompt's `rm -rf .[!.]* *` recipe be promoted to a tool
   (`terminal` subcommand or dedicated `clear_dir` tool)? Every time
   the agent types this glob by hand it risks dropping the dotfile
   half — a single-intent tool would close the surface.

---

## 3. `empty-resume-context` (1 session)

### 3.1 Trigger

Session `69caf6db…`: initial user message is the single word `"resume"`.
No prior `history`, fresh session_id, `working_dir` points at an existing
demo directory (`demos/test`) that already contains the bun/ts scaffold
from a previous session.

### 3.2 Loop anatomy

Messages #1–#5:

```
[1] user "resume"
[2] assistant "I need to understand what you'd like me to resume or work
     on. Could you tell me: 1. What specific task... 2. What would you
     like me to help... I see this is a test directory for an on-chain
     game using Pyth Entropy, but I want to make sure..."
[3] user "u started doing it the work and now doesnt work, dont u have
     the context of our session?"
[4] assistant (tool_call: search_files)
[5] tool: ".gitignore, CLAUDE.md, README.md, bun.lock, index.ts,
     package.json, tasks/lessons.md, tasks/todo.md, tsconfig.json"
```

The agent correctly recognizes `CLAUDE.md` is present and infers "Entropy
game" — because `build_system_prompt` at `core/prompt.py:146–153` reads
`CLAUDE.md` into the system message. But no chat history is loaded, so
the agent improvises a Coin Flip from scratch and enters
`foundry-install-loop` by chunk 10 (this session is double-counted in
bucket 1).

### 3.3 Root hypothesis

**This is a frontend/transport bug, not an agent bug.** The backend's WS
handler has a proper resume path at `api/websocket.py:70–84`: the client
is meant to send `{"type":"resume", "session_id":<prior>}`, which causes
`messages_history.clear(); messages_history.extend(prev["messages"])`.
But this session has:

- A freshly created `session._id = 69caf6db…` (not the prior session's
  id) — see the session doc itself.
- `messages[0] == {role:"user", content:"resume"}`.

That combination means the frontend sent `{"type":"message",
"content":"resume"}` to a new session instead of using the resume
protocol. The backend has no way to distinguish "user literally wanted
to send the word 'resume'" from "the resume button failed to wire". The
agent's heuristic (ask for clarification, fall back on `CLAUDE.md`) is
reasonable — but it still ends up entering a foundry install loop
because the improvised task hits the same underlying environment
problems.

Per the spec (see `docs/superpowers/specs/2026-04-11-ouroboros-agent-team-design.md:131–136`),
frontend-caused artifacts belong in `analysis/frontend_followups.md` and
are out of scope for fixers. Filing this bucket there is the right move.

### 3.4 What a fix would look like

Belongs on the frontend team, not this workstream. Backend-side
defensive measures that might reduce damage without needing a frontend
change:

- Treat a single control word (`"resume"`, `"continue"`, `"retry"`,
  `"pick up"`) as the first user message with zero prior history as
  a suspicious signal and have the agent explicitly surface it: "I
  don't have prior session context. Your client may not have loaded
  the previous conversation." Handled in the prompt, not the code.
- On the backend, add a warning log when `data["type"] == "message"`
  arrives with `content == "resume"` against a freshly-created session
  so the frontend issue is observable.

Neither is a "fix" in the replay-set sense — the replay harness at
`analysis/replay_driver.py` already calls `Agent.run(first_user_message, [])`
directly, which reproduces the empty-history condition exactly. If the
replay set's baseline for this case is "agent improvises and ends up in
foundry-install-loop," the agent-side fixes for bucket 1 transitively
help this bucket.

### 3.5 Open questions

1. Does the ouroboros-frontend repo have a "resume" button that wires
   to `{"type":"resume", "session_id": ...}` or to
   `{"type":"message", "content":"resume"}`? A 2-line check in that
   repo confirms whether this bucket is a true singleton or the tip
   of an iceberg.
2. How often in production does the word "resume" appear as a first
   user message vs. mid-conversation? If it's a real word users type,
   the defensive prompt above would false-positive on them.
3. Is the session-creation path at `api/websocket.py:105–111` also
   called by a potential frontend "restore" flow that's meant to use
   the existing session_id? If so, that's a second frontend wiring
   bug adjacent to this one.

---

## 4. `interpreter-drift-shell-mixing` (3 sessions, cross-cutting)

### 4.1 Trigger

Taxonomy flags three sessions: `69c5c96f…`, `69cb2806…`, `69cafdd3…`.
Drift manifests as the agent cycling through Unix / cmd / PowerShell /
WSL invocations of roughly the same command within a single session.

### 4.2 Loop anatomy

Two distinct sub-patterns that the taxonomy lumped together.

**Pattern A — pre-WSL environment (session `69c5c96f…`, 2026-03-27).**
This session ran before commit `edaae32` (2026-04-01), which introduced
the WSL shim at `tools/terminal.py:14–17`. At that time,
`subprocess.Popen(command, shell=True)` ran on the Windows host. The
agent's cycling is factually *correct* for that environment:

```
[13] forge init --no-git .
     → exit=1 "'forge' is not recognized as an internal or external command"
[14] curl -L https://foundry.paradigm.xyz | bash
     → exit=0 (but: curl: (35) schannel failure)
[15] powershell -c "iwr -useb https://... | iex"
     → exit=1 PowerShell parsing the bash install script
[16] winget install --id Foundry.Foundry
     → exit=2316632084 "No package found matching input criteria"
[17] mkdir foundry-temp
[18] powershell -c "Invoke-WebRequest -Uri '...foundry_nightly_windows_amd64.tar.gz'..."
     → 404 (URL doesn't exist)
[19] bun create vite . --template react
     → exit=0 "Operation cancelled"
```

Against a Windows shell, `powershell -c` and `winget` are the right
tools. The agent is doing environment discovery — not drifting. Today's
prompt at `core/prompt.py:20–21` says "Commands run in Linux (WSL)" and
explicitly forbids `powershell -c` / `cmd /c`; if this session were
replayed against current `main`, that prompt change would prevent the
cycling entirely (the agent would stay in bash).

**Pattern B — WSL-era bash quoting churn (sessions `69cb2806…`,
`69cafdd3…`).** These are already covered in detail under H1 of
`analysis/root_cause_foundry_install_loop.md`. The drift is bash-
internal: `source ~/.bashrc`, `export PATH=…`, `PATH=… cmd`,
`bash -c "..."`, with JSON-escaped-quote syntax errors mixed in.
Nothing shell-paradigm about it — it's one shell (bash) with PATH
contortions.

### 4.3 Root hypothesis

Drift-bucket is mostly a corpus artifact, not a load-bearing failure
mode on current `main`:

- **Pattern A is stale.** Pre-WSL sessions won't recur; the
  environment the agent was adapting to no longer exists.
- **Pattern B is not drift.** It's PATH dancing inside bash and is
  already explained and addressed by H1 of the foundry doc
  (bash-i-c doesn't persist PATH across tool calls, combined with
  foundryup needing a PATH append that the next shell doesn't see).

The prompt guidance at `core/prompt.py:20–24` ("Commands run in Linux
(WSL). CRITICAL RULES: Just pass raw commands… NEVER wrap in
powershell -c, cmd /c…") is correct and appears effective on all
WSL-era sessions in the corpus — no post-edaae32 session in the dumps
cycles through cmd or PowerShell invocations.

The only residual agent-side signal worth naming: **JSON-escaped
quotes produce bash syntax errors.** In excerpts A and B of the
foundry doc, the agent emits `export PATH=\"$HOME/.foundry/bin:$PATH\"`
which arrives at `bash -i -c` as literal `\"` (because the adapter
layer's JSON serialization of `tool_call.args` puts the command as a
JSON string, and the agent over-escapes when it pictures the command
being JSON-quoted once more). One wasted iteration per occurrence,
recoverable.

### 4.4 What a fix would look like

Short version: don't write a fixer for this bucket. Merge it into the
foundry-loop fixer (H1 of that doc) and the termination-analyst's
task #3 work, because everything left after removing the pre-WSL
artifact and the PATH dance is a rounding error.

If a prompt nudge is wanted anyway, a single sentence in the `terminal`
bullet of `core/prompt.py:20–24` would do it: *"Don't JSON-escape
quotes — pass commands in their natural shell form. If your command
contains a double-quote, use single-quotes on the outside (or
vice-versa)."*

### 4.5 Open questions

1. Are there any post-`edaae32` sessions in production (outside the
   19-session corpus) that actually mix `cmd /c` / `powershell -c`
   into WSL bash? The corpus says no, but the corpus is 19 sessions.
   A one-off Mongo query (`db.chunks.find({prompt.content: /powershell
   -c|cmd \/c/})`) would either confirm the bucket is dead on
   current main or surface a real residual.
2. Is the `\"` escaping bug a prompt issue, an LLM-side issue, or a
   JSON encoding issue in `tools/terminal.py` or the adapter layer?
   Worth a one-off test: feed the agent a command with an embedded
   double-quote and see which layer double-escapes.
3. If `interpreter-drift` is merged into other buckets' fixes, does
   the taxonomy's 5-bucket count collapse to 4? The spec's
   "cap fixers at 5, merge lowest-count ones" rule suggests re-
   grouping — `empty-resume-context` (out of scope, frontend) and
   `interpreter-drift` (artifact + overlap) both fold cleanly,
   leaving 3 load-bearing buckets (`foundry-install-loop`,
   `api-tool-result-mismatch`, `bun-vite-scaffold-fallback`).
