# Why do sessions terminate mid-tool-call?

Analyst deliverable for Phase 1.5. Read-only investigation. Sources:
`analysis/dumps/` (6 foundry-install-loop sessions), `api/websocket.py`,
`core/agent.py`, `core/registry.py`, `tools/terminal.py`, `db/models.py`
on `main @ c23dc73`.

## 1. Shape of the data

All 6 sessions in scope share the same DB-level signature — `session.status
== "completed"`, `error_message is None`, and the final chunk's `response`
still carries `tool_calls`. Two distinct timing shapes emerge when the last
chunk's `created_at` is compared to `session.last_activity`:

| Session ID | chunks | msgs | last msg role | last-chunk latency | gap last_chunk → last_activity | last chunk command | shape |
|---|---|---|---|---|---|---|---|
| `69cafdd3c9ee05a19b45638a` | 13 | 26 | assistant | 1.9 s | **169.0 s** | `forge install pythnet/pyth-crosschain` | A |
| `69cb280662972386aaf55ff4` | 17 | 34 | assistant | 3.6 s | **197.8 s** | `forge install pythnet/pyth-crosschain` | A |
| `69cc5c542447cfb1b234d419` | 7 | 14 | assistant | 1.5 s | **180.2 s** | `forge install pythnet/pyth-crosschain` | A |
| `69cc5d252447cfb1b234d422` | 4 | 8 | assistant | 1.8 s | **180.2 s** | `forge install pythnet/pyth-crosschain --no-git` | A |
| `69caf6db825fef911ec3ebd3` | 24 | 48 | tool | 48 s | 0.1 s | `write_file` | B |
| `69cc0171365f162bc336119f` | 19 | 37 | tool | 2.2 s | 0.1 s | `bun run dev` | B |

Message-count arithmetic: for every **shape A** session, `msgs = 1 + 2·(chunks−1) + 1`,
i.e. `[user, (asst, tool) × (chunks−1), asst]`. The final `tool` message
for the last chunk is **missing from Mongo**. The last role is `assistant`
with unresolved `tool_calls`.

For **shape B** sessions, the gap collapses to ~100 ms and the last role is
`tool`, meaning the final tool dispatch completed and its `tool_msg` was
appended before the session terminated.

The four shape-A gaps cluster tightly around **180 s ± 20 s**. That is the
hard-coded default timeout in `tools/terminal.py:121` (`timeout = args.get("timeout", 180)`).
All four final tool calls are `forge install pythnet/pyth-crosschain` — a
`git submodule add` of a large repo. Forge install routinely exceeds 180 s
on cold caches.

## 2. Write path audit

**Chunk write (`api/websocket.py:117-157`, `chat_with_logging`).**  For each
LLM response the handler: (1) starts a heartbeat task that pings every
10 s, (2) awaits `adapter.chat`, (3) cancels the heartbeat, (4) calls
`add_chunk(..., status="ok")` which also `$set`s `session.last_activity`
(`db/models.py:153-156`). The heartbeat **only covers the LLM call** — it
is **not** running while tools execute.

**Per-tool-call loop (`core/agent.py:124-158`).**  The agent appends
`assistant_msg` to `history` (`:121`), then for each tool call:

```
yield {"type": "tool_call", ...}
result = self.registry.dispatch(...)          # SYNCHRONOUS  (:127)
# truncation (:129-136)
yield {"type": "tool_result", "result": result}  # :138
if tc.name == "terminal":
    ... json.loads(result); yield self_correcting (:141-149)
tool_msg = {...}                              # :151-156
messages.append(tool_msg)
history.append(tool_msg)                      # :158
```

Two things about this sequence matter:

1. **`registry.dispatch` is synchronous** (`core/registry.py:48`:
   `result = handler(args, **accepted)`). For the `terminal` tool the
   handler is `tools/terminal.py:handle`, which calls
   `subprocess.Popen(...)` and `proc.wait(timeout=timeout)` at line 210 —
   a plain blocking call. While it runs, the asyncio event loop is
   frozen. No heartbeat fires (even if one were scheduled), no inbound
   WS frames are read, no uvicorn ping/pong is answered. The same
   pattern exists in `tools/pyth_deploy.py:59,91` with a 120 s timeout.
2. **`tool_msg` is appended AFTER `yield {"type": "tool_result"}`**
   (`:138` vs `:157-158`). The WS handler's save path triggers on the
   tool_result event (`api/websocket.py:178-180`), so the save captures
   `history` **before** the new tool_msg exists. This is the "one tool
   message behind" skew that matches the shape-A message counts.

**Send + save (`api/websocket.py:166-180`).**  For every yielded event:

```
await ws.send_json(event)
if event.get("type") == "tool_result" and len(messages_history) > last_save_len:
    await update_session_messages(session_id, messages_history)
    last_save_len = len(messages_history)
```

If `ws.send_json` raises `WebSocketDisconnect`, the save never runs on
this yield; instead the exception escapes the `async for`.

**Termination paths (`api/websocket.py:194-222`).**  Three end-states:

| Branch | Entry condition | `session.status` written | `error_message` written |
|---|---|---|---|
| Normal completion (`:190-192`) | `async for` loop exits naturally (no-tool response breaks in agent, or max_iterations) | `"completed"` | — |
| `except WebSocketDisconnect` (`:194-199`) | Any `await ws.send_json` raises WebSocketDisconnect | **`"completed"`** | — |
| `except Exception` (`:200-207`) | Any other exception from within the agent loop | `"error"` | `str(e)` |

**The WebSocketDisconnect branch is semantically indistinguishable from
clean completion at the DB level.**  No `terminated_reason`, no flag,
no hint. The outer-loop counterpart at `:211-214` does the same thing.
Because both branches also re-save `messages_history`, they refresh
`session.last_activity` — which is how the ~180 s gap appears in shape A.

**There is no other place that sets `session.status` to `"completed"` or
`"error"`.**  There is no code path that flags a session as "disconnected
mid-tool-call" or "tool still pending."

## 3. Hypotheses (ranked)

### H1 — Synchronous tool dispatch blocks the event loop past WS liveness, and `WebSocketDisconnect` is silently relabelled as `completed`. (High confidence)

**Mechanism.** `tools/terminal.py:210` runs `proc.wait(timeout=180)` on the
event-loop thread. While blocked: uvicorn's WebSocket ping (default
`ws_ping_interval=20`, `ws_ping_timeout=20`) cannot be sent or ack'd, and
on timeout uvicorn closes the WS (seen from the server as "client gone").
The client-side `useAgent.ts` does not itself close the WS on idle, but
`ws.onclose` triggers the browser's default keepalive handling and our own
auto-reconnect-after-2s path (`useAgent.ts:139-141`) — which fires a brand
new socket while the old server-side handler is still mid-`proc.wait`.
When `proc.wait` finally returns (completion or the 180 s TimeoutExpired
branch at `terminal.py:211-220`), the next line in the handler is
`await ws.send_json(event)` for the `tool_result`. That raises
`WebSocketDisconnect`, which is caught at `api/websocket.py:194` and
unconditionally writes `status="completed"` with no `error_message`.

**Evidence.**
- 4/6 sessions show `last_activity − last_chunk.created_at ∈ [169, 198]` s,
  clustered on the 180 s terminal timeout.
- 4/4 final commands are `forge install pythnet/pyth-crosschain` variants
  (known to exceed 180 s on cold caches of a large repo).
- Per-session message arithmetic matches "the tool_msg for the final
  chunk was never appended" → WebSocketDisconnect raised at the
  `yield tool_result` send, before `core/agent.py:157-158` ran.
- For the 2 shape-B sessions (`69caf6db`, `69cc0171`), the final tool
  was fast (`write_file`, `bun run dev` returning quickly because
  vite-dev daemonised) and the tool_msg **was** appended. The drop
  must have happened on a subsequent yield (`status` for iteration+1,
  or the next `tool_call`), so the gap collapses to ~100 ms because
  `add_chunk` and the disconnect-handler save happen back-to-back.

### H2 — Heartbeat coverage is too narrow. (High confidence, subordinate to H1)

The `_heartbeat` task (`api/websocket.py:18-28`) is created inside
`chat_with_logging` at `:123` and cancelled in the `finally` at `:127-131`.
It runs only during the LLM call — not during the tool-dispatch window,
which is where the real multi-minute blocks occur. Even if the event loop
weren't blocked, no heartbeat would be sent during a long `forge install`.
Under H1 the event loop *is* blocked, so even if the heartbeat task were
scheduled it could not fire; but widening the heartbeat to cover tool
calls would still not fix the underlying block — it would need an async
tool runtime first.

### H3 — Save skew: the final tool_result is written to Mongo "one step behind." (High confidence, independent)

`agent.py:138` yields `tool_result` **before** `agent.py:157-158` appends
`tool_msg`. The WS handler's save at `websocket.py:178-180` therefore
always writes a `messages` array that ends on `assistant` while tool_msg
is still in flight. For sessions that terminate mid-tool-call, the
final tool result is permanently missing from Mongo **even when
dispatch succeeded**. This is not a termination cause by itself, but it
makes post-mortem analysis misleading: reading `session.messages` alone
one cannot tell whether the agent got a tool result at all — the answer
lives in `chunks[-1].prompt` of the *next* (never-written) chunk.

### H4 — Uvicorn/ASGI disconnection silently aborts the inner try without error_message. (Medium, restatement of H1's "and")

Independent of *why* the WS dropped, the inner try at `websocket.py:164`
treats `WebSocketDisconnect` and `Exception` asymmetrically: the former
writes `"completed"`, the latter `"error"`. That asymmetry is the reason
stuck-detection criteria #1–#4 in the spec miss these sessions entirely.
Fixing only the block (H1) without fixing this mislabelling would make
honest session-outcome accounting still difficult, because we would lose
the signal that "the agent was interrupted" once the fix lands.

### H5 — Client-initiated drop via auto-reconnect on `onclose`. (Low, contributing)

`useAgent.ts:129-142` fires `reloadFromApi()` + a 2 s `setTimeout` →
`connect()` on every `onclose`. If the browser or an intermediary proxy
closes the old socket for any transient reason during a long
tool-dispatch, the frontend silently spins up a second WS that the
server treats as a distinct connection — the first server-side handler
is still blocked and will, on resumption, raise WebSocketDisconnect on
its first send. This is a contributor, not an origin: the disconnect
event itself is from the server's perspective the ASGI-level close,
but client-initiated reconnect attempts during the block can accelerate
it and means the recorded session always ends on the *first* handler,
never the reconnected one.

---

**Not supported** by this corpus (rejected):

- A backend exception during chunk persistence. The `except Exception`
  branch at `:200-207` writes `error_message=str(e)`; all 6 sessions
  have `error_message=None`.
- Max-iterations force-summary. That path writes an extra final
  assistant chunk without tool_calls (`core/agent.py:163-166`); none of
  the 6 sessions show that signature.
- User-initiated interrupt (`agent.interrupt()` via `type=="stop"`).
  That yields a terminal response and cleanly breaks the loop; none of
  the 6 sessions end on a response chunk.

## 4. Recommended verification (cheapest first)

1. **Static confirmation.** Grep for other synchronous `subprocess.run` /
   `proc.wait` callsites in `tools/`. Besides `terminal.py` and
   `pyth_deploy.py` there should be none — if there are, they share the
   same bug. Cost: ~5 min.
2. **Local repro, no LLM.** Write a 20-line script that connects a
   WebSocket client to `ws://localhost:8000/api/agent`, sends a
   fake message, then has the server-side tool-handler `time.sleep(200)`
   inline (monkeypatch or a temporary fixture). Observe whether the WS
   drops during the sleep and what `session.status` ends up as. If it
   ends up `"completed"` with no error_message, H1+H4 are confirmed.
   Cost: 15 min, no LLM spend.
3. **Inspect `uvicorn` startup flags.** Confirm `ws_ping_interval` and
   `ws_ping_timeout` are at default (20 s each). If they are, any tool
   call exceeding ~40 s on a blocked event loop will trigger WS
   termination. Cost: 1 min.
4. **Add a one-line probe before each `update_session_status` call.**
   In a throwaway branch, pass a `terminated_reason` field through
   `update_session_status` (`disconnect`, `error`, `completed_clean`,
   `max_iter`) and re-run any live traffic for a day. The Mongo
   field distribution answers the question in production.
5. **Only if 1–4 are inconclusive:** instrument `registry.dispatch` to
   emit an `asyncio.get_running_loop().time()` before and after each
   call, and compare against chunk timestamps in Mongo. This is
   expensive (requires writing through prod) and should not be needed.

## 5. Implication for Phase 2 measurement

Phase 2 and Phase 3 cannot use "session ended with `status=completed` and
no `error_message`" as a success criterion, because that is exactly what
a disconnect-in-the-middle-of-forward-progress looks like today. The
validator's replay harness is already decoupled from the frontend (it
calls `core.agent.Agent.run` directly, per the design spec), so the WS
transport issue does not reappear there — but the **classification of
replay outcomes** needs care for these specific cases.

**Recommendation for the validator's scoring rules:**

1. **Exclude shape-B sessions from the stuck replay set, move them to
   the golden set.** `69caf6db` and `69cc0171` were making forward
   progress and the agent only stopped because the socket dropped. They
   are not stuck; they are interrupted. Treating them as "stuck"
   inflates the baseline failure rate and will cause any prompt change
   to look like a win on those cases even if it changed nothing. Put
   them in the golden set with expected behavior = "reaches working
   frontend" rather than in the stuck replay set.

2. **For shape-A sessions, score by forward-progress criteria, not by
   completion.** The definition of "passed" for these cases should be:
   *the agent reaches the same recovery move the original session was
   about to make, in ≤N iterations, without re-entering the PATH/forge
   loop.* For `69cafdd3` / `69cb2806` that move is `forge install
   pythnet/pyth-crosschain` with PATH set; for `69cc5c54` / `69cc5d25`
   it is `git init` then `forge install`. A baseline run scored this
   way will *also* show the original sessions failing (which they did),
   so the comparison is honest.

3. **Do not rely on `session.status` for replay-outcome classification.**
   The validator should read the replay's `final_messages` list and
   classify by (a) whether a terminal assistant-without-tool-calls
   message exists, (b) how many tool iterations were used, and (c)
   whether the final assistant-without-tool-calls contains a Netlify
   URL / BaseScan URL / "deployed to" string matching the task type.
   The replay driver writes its own success record and is not subject
   to the WS disconnect labelling bug.

4. **Cap the replay's per-tool-call timeout below the backend's.** The
   replay driver in `analysis/replay_driver.py` should set
   `timeout=60` on terminal calls or monkeypatch `proc.wait` to
   shorter, so that a single hanging forge install cannot dominate a
   replay's wall clock. A fix landing in Phase 2 may or may not change
   the dispatch semantics; the replay harness should not wait 3 min
   per hang regardless.

5. **Record `last_chunk_latency_ms` and `gap_last_chunk_to_last_activity`
   in `baseline.md` for every replay case.** These two numbers are the
   cheapest available discriminator between "agent got smarter" and
   "agent happened to finish before the socket dropped." Publishing
   them makes scorecard reads auditable.

Net: the stuck replay set should be recut with shape-B cases demoted to
the golden set, and shape-A cases scored by "did the agent make the right
next move inside iteration N" rather than "did the session status read
`completed`." The fixer teams do not need to fix the termination bug
itself to hit the 60% success bar — but the validator's scoring must be
blind to it to give them an honest measurement.
