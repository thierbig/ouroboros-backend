# Fix: session termination (async dispatch + disconnect labeling + save-skew)

## Summary

Three surgical changes eliminate the shape-A cluster of "silent 180 s
termination" sessions documented in `analysis/session_termination_cause.md`.
Root cause: `registry.dispatch` ran on the asyncio event-loop thread, so
blocking `subprocess.wait` calls in `tools/terminal.py:210` and
`tools/pyth_deploy.py:59,91` starved uvicorn's 20 s WS ping. When the
ping timed out, uvicorn closed the socket; the next `await ws.send_json`
raised `WebSocketDisconnect`, which the handler silently relabeled as
`status="completed"`. Independently, `tool_msg` was appended to history
AFTER `yield {"type": "tool_result", ...}`, so incremental saves
triggered by the yield were permanently one tool message behind.

## Changes

- **`core/agent.py`** — wrap `registry.dispatch` in `asyncio.to_thread`
  so blocking tool handlers run on a worker thread and the event loop
  keeps servicing WS pings. Also reorder: build and append `tool_msg`
  to `messages`/`history` BEFORE yielding `tool_result`, so the WS
  handler's save at `api/websocket.py:178-180` always captures the
  tool message that corresponds to the event the frontend just received.
- **`db/models.py`** — add `mark_disconnected(session_id, ...)` helper
  with filter `{"_id": ..., "status": "running"}` so it can't clobber a
  prior `"completed"` or `"error"` state.
- **`api/websocket.py`** — both `except WebSocketDisconnect` branches
  (inner at `:194`, outer at `:211`) now call `mark_disconnected` instead
  of `update_session_status(..., "completed", ...)`.

## Replay sessions this targets

All 6 foundry-install-loop sessions in the Phase 1.5 corpus:

- `69cafdd3c9ee05a19b45638a` — shape A, 169 s gap, `forge install` final
- `69cb280662972386aaf55ff4` — shape A, 198 s gap, `forge install` final
- `69cc5c542447cfb1b234d419` — shape A, 180 s gap, `forge install` final
- `69cc5d252447cfb1b234d422` — shape A, 180 s gap, `forge install --no-git` final
- `69caf6db825fef911ec3ebd3` — shape B, made progress; WS drop late
- `69cc0171365f162bc336119f` — shape B, made progress; WS drop late

After the fix, all six would produce a terminal assistant-without-tool-calls
message for the actual agent outcome, and sessions that still disconnect
would be labeled `status="disconnected"` — distinguishable from clean
finishes in the validator's outcome classifier.

## Manual verification

The repro from `session_termination_cause.md §4.2` is now also encoded as
the first unit test. To reproduce end-to-end against a running backend:

1. Patch any registered tool to `time.sleep(200)` inline (e.g. the `echo`
   tool).
2. Start the backend, connect a WS client to `ws://localhost:8000/api/agent`,
   send a message that triggers that tool.
3. Observe: heartbeats continue to arrive every 10 s (proves the event
   loop is unblocked), and when the tool eventually returns, the session
   finishes cleanly with `status="completed"`. Before the fix the
   session ended at ~40 s with no trailing heartbeats and
   `status="completed"` despite being interrupted.
4. Force a disconnect mid-tool by killing the client: the session will
   now show `status="disconnected"`, not `"completed"`.

## Test output

```
$ python -m pytest tests/test_termination.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\thier\ouroboros-backend
configfile: pytest.ini
plugins: asyncio-1.3.0, anyio-4.12.1
collected 4 items

tests/test_termination.py::TestEventLoopUnblocked::test_blocking_tool_does_not_freeze_event_loop PASSED
tests/test_termination.py::TestDisconnectLabeling::test_mark_disconnected_writes_disconnected_status PASSED
tests/test_termination.py::TestDisconnectLabeling::test_mark_disconnected_does_not_overwrite_completed PASSED
tests/test_termination.py::TestSaveSkewFixed::test_tool_msg_appended_before_tool_result_yield PASSED

============================== 4 passed in 0.65s ==============================
```

## Notes for downstream consumers

- The validator's replay-outcome classifier should now treat
  `status="disconnected"` as a distinct outcome category, not collapse
  it with `"completed"`.
- Session schema gains an implicit new status value `"disconnected"`.
  No explicit schema/migration needed because Mongo is schemaless and
  existing "completed" docs remain untouched.
- The shape-B replay sessions (`69caf6db`, `69cc0171`) were making
  forward progress — per the analyst's §5 recommendation they should be
  moved from the stuck replay set to the golden set. That's a validator
  change, not in scope for this fix.
