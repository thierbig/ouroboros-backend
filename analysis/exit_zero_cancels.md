# Audit: exit-zero-but-failed tool outcomes

Scope: the self-correcting detector in `core/agent.py` and every tool in
`tools/`. Builds on the H3 hypothesis in
`analysis/root_cause_foundry_install_loop.md` §3.

## 1. Detector surface today

From `core/agent.py:140–149`:

```
if tc.name == "terminal":
    try:
        parsed_result = json.loads(result)
        stderr = parsed_result.get("stderr", "")
        exit_code = parsed_result.get("exit_code", 0)
        if stderr and exit_code != 0:
            yield {"type": "self_correcting", "error": stderr.strip()}
    except (json.JSONDecodeError, TypeError):
        pass
```

**What it does.** Parses the `terminal` tool's JSON response, and if
**both** (`stderr` is non-empty AND `exit_code` is non-zero), yields a
`self_correcting` frontend event with the trimmed stderr.

**Who sees it.** The event goes out on the async iterator consumed by
`/api/agent` and rendered as a yellow "self-correcting" status in the UI.
**The LLM does not see this event** — it only reads the literal tool
result string. Widening the detector alone won't change LLM behavior.
The LLM-visible path is the `result` string (`{"output", "stderr",
"exit_code", "error"}`); any detection that should change agent reasoning
has to be reflected in that JSON body **before** it's appended to
`history` at `core/agent.py:157`.

**What it catches.** Textbook shell failures: `exit_code=127` with
`command not found` stderr, `exit_code=1` with a real error message, etc.
Covers the "forge: command not found" branch of the foundry bucket.

**What it misses.**
- Exit-zero semantic failures (the H3 hypothesis). See §3 for the
  enumerated markers.
- Any tool other than `terminal`. The detector is gated on
  `tc.name == "terminal"`; `pyth_deploy`, `pyth_price`, `pyth_search`,
  `read_file`, `write_file`, `patch`, `search_files`, `pyth_candles`,
  `pyth_history` all return unstructured error strings that yield no
  self-correcting event and are not uniformly parsed anywhere else.
- `stderr` is required non-empty, so pure-stdout failures (like
  `bun create vite` → `"└  Operation cancelled\n\n"` on stdout,
  empty stderr) are double-invisible: wrong exit code AND wrong stream.

## 2. Per-tool audit

### `tools/terminal.py` — `terminal`
- Shells out: yes, into WSL `bash -i -c <cmd>` on Windows, raw shell
  elsewhere (`tools/terminal.py:170–178`).
- Return shape: JSON `{output, stderr, exit_code, error}`.
- Exit-0 semantic failures observed in dumps:
  - **`bun create vite` / `npx create-vite` cancel under no-stdin.** Exit
    0, stdout ends with `"└  Operation cancelled\n\n"`, stderr benign
    `"Resolving dependencies\n..."`. 11 occurrences across 7 of 19
    sessions. Sessions: `69c5c96f…`, `69cbefc6…`, `69cbf985…` (×3),
    `69cbfb65…`, `69cc0171…` (×2), plus mixed cases.
  - **`foundryup` installer self-backgrounds its download.** Exit 0 with
    the Foundry ASCII banner on stdout, but forge/cast binaries may still
    not be on PATH next call because `~/.bashrc` edits don't survive
    `bash -i -c`. Sessions: `69cafdd3…`, `69cb2806…`. (Not strictly a
    tool-level exit-0 failure — the command did succeed — but the next
    invocation of forge will fail for a state reason the agent can't see
    from this result.)
  - **`forge init --force` on non-empty dir.** Exit 0, stderr prints
    `"Warning: Target directory is not empty, but --force was
    specified"`. This is a **benign** warning, not a failure — forge
    does the right thing. Don't flag. 7 sessions show it.
- Exit-0 noise to NOT flag:
  - `"wsl: Failed to start the systemd user session for 'pstar'"`
    appears in 7 sessions on commands that fully succeeded
    (`bun install`, `vite build`, `forge build`). WSL daemon noise.
  - `"bash: warning: setlocale: LC_ALL: cannot change locale"` — locale
    warning under Netlify build, always benign.
  - `"Target directory is not empty, but --force was specified"` —
    forge telling you `--force` worked as intended.
  - `"Warning: btc-price-predictor.netlify.app already exists. Trying
    ...-508..."` — Netlify CLI successful collision recovery.
- Severity: **HIGH.** This tool is used in 19/19 sessions, and the
  `create-vite`/`bun create` cancel sentinel alone affects 7 sessions.

### `tools/pyth_deploy.py` — `pyth_deploy`
- Shells out: yes, `subprocess.run(["forge", "build"|"create", ...])`
  (`tools/pyth_deploy.py:59, 91`).
- Return shape: inconsistent. Success → plain string. Failure → JSON
  with `error` key (`tools/pyth_deploy.py:47, 53, 66, 73, 75, 99, 103,
  119`). No `exit_code` field.
- Exit-0 semantic failures:
  - Forge is missing on PATH → exits cleanly with `{"error": "Foundry
    (forge) is not installed..."}` but this is the tool's own framing,
    not the subprocess exit code. The tool hides the subprocess
    `FileNotFoundError` entirely.
  - Forge compiled but `forge create` didn't print a parseable
    `Deployed to:` line → returns JSON with `{"error": "Could not parse
    deployed address..."}` even if forge's own exit code was 0.
  - Observed in `69caf6db…[41]`: tool result is `{"exit_code": null,
    "stderr": "", "output": ""}` — the tool swallowed something. Root
    cause unclear from the tool alone; may be that forge blocked
    indefinitely and hit the 120s timeout, emitting an empty response.
- Severity: **MEDIUM.** Only 1 session in the corpus invokes
  `pyth_deploy`, but every failure mode here is exit-0 from the agent's
  point of view because the tool never surfaces the subprocess return
  code.

### `tools/pyth_price.py`, `pyth_search.py`, `pyth_history.py`, `pyth_candles.py`
- Shells out: no. Each makes an HTTP request via `urllib.request`.
- Return shape: **plain strings on success or failure**, except
  `pyth_price` (JSON-in-a-string on some paths, plain string on others).
- Exit-0 semantic failures:
  - `"No candlestick data returned for {symbol}: {errmsg}"`
    (`pyth_candles.py:88`)
  - `"No Pyth price feeds found for: '{query}'"` (`pyth_search.py:62`)
  - `"No historical data returned"` (`pyth_history.py:67`)
  - `"Error fetching candles: {e}"` / `"Error querying Pyth Hermes:
    {e}"` / `"Error fetching historical prices: {e}"` / `"Request
    failed: {e}"` — on network errors.
- Severity: **LOW** for the current replay set — the corpus does not
  show any pyth_*-tool loops, but the detector misses them completely,
  so a future taxonomy bucket could form here undetected.

### `tools/read_file.py`, `tools/write_file.py`, `tools/patch.py`
- Shells out: no, direct filesystem I/O.
- Return shape: plain strings. Successes start with `"✓"` (write_file,
  patch) or numbered content (read_file). Failures start with
  `"Error: "` or `"Error executing tool..."` via the registry's generic
  exception handler (`core/registry.py:50`).
- Exit-0 semantic failures:
  - `"Error: File not found: …"` / `"Error: Permission denied: …"` /
    `"Error: old_string not found in …"` / `"Error: old_string found N
    times in …"` — these ARE errors but are invisible to the terminal
    detector.
  - Observed in dumps: `69cafdd3…[10]` returned `"Error: Permission
    denied: C:\Users\thier\ouroboros-backend\demos\try"` in response to
    `read_file({"path": "."})`. No self-correcting signal fired.
- Severity: **LOW-MEDIUM.** File-I/O errors are usually LLM-legible
  because of the `"Error: "` prefix, and observed sessions recover in
  one step. Mostly a detector-coverage concern, not a loop driver.

### `tools/search_files.py` — `search_files`
- Shells out: no, walks the filesystem.
- Return shape: plain strings. `"No matches found."` / `"No files
  found."` are legitimate zero-result responses, not failures.
- A built-in rate-limiter returns `"BLOCKED: You have run this same
  search {count} times."` after 4 repeats (`search_files.py:132`) — this
  IS a semantic failure signal the agent should react to, but it's
  invisible to the terminal detector.
- Severity: **LOW.**

### Registry-level
`core/registry.py:50` wraps every handler in `try/except` and returns
`f"Error executing tool '{name}': {type(e).__name__}: {e}"` on any
uncaught exception. These too are exit-0 from the detector's
perspective. Not in the dumps, but a class of silent failure worth
noting.

## 3. Canonical string markers

Ranked by precision (higher = fewer false positives when used alone).
Each marker below is suggested for stdout OR stderr of the `terminal`
tool result, with `exit_code == 0`. Evidence counts are from
`analysis/dumps/`.

### Tier 1 — high-confidence, ship as hard failure
| Marker | Scope | Evidence | Notes |
|---|---|---|---|
| `└  Operation cancelled` | stdout | 11 hits / 7 sessions | `@clack/prompts` cancel sentinel. Used by `create-vite` and `bun create`. The box-drawing `└` prefix makes this uniquely theirs — almost no risk of false positive. |
| `Operation cancelled` (no prefix) | stdout | same | Slightly broader; still very safe as a scaffolder-specific sentinel. |

### Tier 2 — medium-confidence, context-dependent
| Marker | Scope | Evidence | Notes |
|---|---|---|---|
| `Bun could not find a package.json file to install from` | stderr | observed after Tier-1 cancel in `69cc0171…[14]` | Follow-on signal that the previous scaffolder cancel left the tree empty. Only useful if the previous-call context is available to the detector. |

### Tier 3 — DO NOT flag (false-positive traps)
| Marker | Scope | Evidence | Why not |
|---|---|---|---|
| `Warning:` (any) | any | 8 sessions | Generic. forge, bash, Netlify, curl all emit it benignly. |
| `Target directory is not empty, but --force was specified` | stderr | 7 sessions | This is forge confirming `--force` worked. Pure success. |
| `wsl: Failed to start the systemd user session` | stderr | 7 sessions on successful commands (e.g. `bun install`, `vite build`) | WSL daemon-init noise unrelated to the command's outcome. |
| `bash: warning: setlocale: LC_ALL` | stderr | Netlify build sessions | Locale init warning, not a command failure. |
| `npm warn exec The following package was not found and will be installed` | stderr | `69cb2d47…[68]`, `69cbf985…[22]` | `npx` install-on-demand; a success path. |
| `already exists. Trying ...-508...` | stdout | `69cc20f3…[36]` | Netlify CLI collision recovery, succeeded. |
| `Failed to start` (as a substring) | anywhere | 10+ | Too broad; catches WSL noise above. |

### Future-proofing (not yet observed in corpus)
Add as Tier-1 if they ever show up in replay runs:
- `Build failed` / `build failed` in stdout with exit 0 (some bundlers
  exit 0 on build errors).
- `Command cancelled` (variant wording).
- Gum / charm-style `Aborted!` prefix.

## 4. Recommended detector shape

Intent: mutate the LLM-visible tool result (so the model reasons about
the failure) AND yield the existing frontend telemetry event (so the UI
stays honest). Pseudocode only.

```
def classify_terminal_result(parsed):
    # parsed is the JSON payload from tools/terminal.py
    stdout = parsed.get("output", "") or ""
    stderr = parsed.get("stderr", "") or ""
    exit_code = parsed.get("exit_code", 0)

    if exit_code != 0 and stderr:
        return FAIL, stderr.strip()      # current detector case

    # Tier-1 sentinels: exit 0 but semantically failed
    for marker in TIER_1_STDOUT_MARKERS:  # e.g. "└  Operation cancelled"
        if marker in stdout:
            return FAIL, f"scaffolder cancelled (marker: {marker!r})"

    for marker in TIER_1_STDERR_MARKERS:  # currently empty
        if marker in stderr:
            return FAIL, f"failure marker in stderr: {marker!r}"

    return OK, None

# in core/agent.py, after dispatch, BEFORE history.append(tool_msg):
if tc.name == "terminal":
    status, synthesized_err = classify_terminal_result(json.loads(result))
    if status == FAIL:
        # 1. rewrite the JSON so the LLM sees an error field populated
        patched = json.loads(result)
        if not patched.get("error"):
            patched["error"] = synthesized_err
        result = json.dumps(patched)
        # 2. keep the existing frontend event
        yield {"type": "self_correcting", "error": synthesized_err}
```

Optional extensions (out of scope for the minimum fix, worth flagging
for the Phase 2 fixer):
- Apply the same `error`-field synthesis to `pyth_deploy` results so the
  tool contract becomes uniform JSON `{output, exit_code, error}` for
  all shell-invoking tools.
- Expose one `[SYSTEM]` user message appended to `messages` after a
  Tier-1 match (like `core/agent.py:82–88`'s adapter-error inject), so
  the scaffolder-cancel case gets an explicit "don't retry
  `create-vite`; write files manually" hint.

## 5. Open questions

1. **What exact exit code does `@clack/prompts` cancel emit across bun
   and npx versions?** The corpus shows exit 0 on bun 1.3.11 and npx
   `create-vite@9.0.3`. If upstream flips to a non-zero exit at some
   future version, the Tier-1 sentinel stays correct but becomes
   redundant — no harm. But a fixer should verify the sentinel survives
   a `bun upgrade`/`npm upgrade` by spot-checking in the sandbox.
2. **Should the detector modify the LLM-visible payload or only emit a
   frontend event?** My read of §1 is that modifying the payload is
   necessary to change agent behavior. The existing detector deliberately
   only emits telemetry. The fixer should get explicit sign-off on the
   payload-mutation approach before shipping.
3. **Where does `pyth_deploy`'s empty `{"exit_code": null, "stderr": "",
   "output": ""}` in `69caf6db…[41]` come from?** Pyth_deploy never
   returns that shape from its own code paths — it returns either a
   success string or a JSON `{error: ...}`. Something upstream
   (registry exception wrapping? frontend serialization?) is reshaping
   the result. Needs 10 minutes of tracing before a fixer can rely on
   the shape of that response.
4. **Is there value in a Tier-2 "chained scaffolder-cancel" detector?**
   The sequence `bun create vite → bun install fails → agent runs `bun
   init` → agent runs `rm -rf *`` only triggers the *second* time the
   agent lands on this. Flagging the first `Operation cancelled` should
   break the chain on its own, but the second-order markers
   (`"Bun could not find a package.json"`) might catch cases we haven't
   seen yet.
5. **Does the detector belong in `core/agent.py` or in each tool?**
   Pushing this into `tools/terminal.py` keeps `core/agent.py` free of
   tool-specific string matching. The tradeoff is that extending to
   other tools later (pyth_deploy, etc.) either duplicates the registry
   pattern or requires a shared helper. Architectural call for the
   fixer.
