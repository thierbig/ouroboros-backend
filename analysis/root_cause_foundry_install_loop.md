# Root cause: `foundry-install-loop`

Analyst deliverable for Phase 1.5. Sources: `analysis/taxonomy.md` (bucket 1),
the 6 session dumps under `analysis/dumps/` listed in that bucket, and the
backend code at `core/agent.py`, `core/prompt.py`, `core/registry.py`,
`tools/terminal.py`, `tools/pyth_deploy.py` on `main` as of
commit `c23dc73`.

## 1. Trigger

All 6 sessions originate from the same scaffold-and-build flow the frontend
sends when a user creates a demo project:

- 5/6 begin with the template message:
  *"I just created a project called `<NAME>`. Read the CLAUDE.md for stack
  and rules. I want to build a mini game that uses Pyth Entropy for on-chain
  randomness on Base Sepolia. Do NOT mention the stack, CLAUDE.md, or
  internal details in your response..."*
  (`69cafdd3…`, `69cb2806…`, `69cc5c54…`, `69cc5d25…`, `69cc0171…` —
  last one uses Pyth Price Feeds instead of Entropy).
- 1/6 (`69caf6db…`) starts with the single word `resume` against an existing
  `test` demo directory that had only a bun/ts scaffold — no prior Solidity
  state — and the agent improvises a Coin Flip anyway.

After 2–5 turns of Q&A to pick a game type and betting mechanics, the agent
transitions into tooling on the empty project directory. The directory on
disk contains only `CLAUDE.md` and `tasks/*.md` at this point. The agent's
first tool call in this phase is always either `forge init …` (for Entropy
games) or `bun create vite …` (for Price Feed games).

## 2. Loop anatomy

The bucket name is slightly misleading: of the 6 sessions, **2** exhibit a
true multi-iteration loop on PATH/install, **1** is a bun-scaffold fallback
that ended up tagged to this bucket via mixed-tool overlap, **1** is a
broken-WSL resume case, and **2** are short forward-progress sessions whose
stream terminated mid-tool-call with no loop at all. The "stuck" signal
here is `stuck_reason=ended_mid_loop` (the investigator's expanded criterion
of "last chunk has `tool_calls`"), not an agent-observable loop in 4 of 6
cases. The sessions that do loop loop on the same small set of mistakes.

### Excerpt A — session `69cafdd3…`, the canonical PATH dance
Steps #13–#23 of `session.messages`. The agent is trying to get `foundryup`
on PATH after `curl | bash` installed only the bootstrapper.

```
[13] CALL terminal: forge init --force .
[14] TOOL: exit=127 stderr='/bin/bash: line 1: forge: command not found\n'
[15] CALL terminal: curl -L https://foundry.paradigm.xyz | bash
[16] TOOL: exit=0 out="Installing foundryup... added foundryup to PATH. Run 'source ~/.bashrc' ..."
[17] CALL terminal: source ~/.bashrc && foundryup
[18] TOOL: exit=127 stderr='/bin/bash: line 1: foundryup: command not found\n'
[19] CALL terminal: export PATH=\"$HOME/.foundry/bin:$PATH\" && foundryup
[20] TOOL: exit=2 stderr="syntax error near unexpected token \`(\'"
[21] CALL terminal: export PATH="$HOME/.foundry/bin:$PATH" && foundryup
[22] TOOL: exit=0 out="foundryup installed ..."
[23] CALL terminal: export PATH="$HOME/.foundry/bin:$PATH" && forge init --force .
```
Four separate per-iteration mistakes layered on top of each other:
(a) `source ~/.bashrc` doesn't restore the PATH update in the next tool
call; (b) the first `export PATH` is emitted with JSON-escaped quotes
(`\"`), producing a bash syntax error; (c) the agent then correctly
prepends PATH on every subsequent command, which works but burns an extra
iteration per call.

### Excerpt B — session `69cb2806…`, same PATH dance + forge install's git dependency
Steps #19–#33.

```
[19] CALL terminal: source ~/.bashrc && foundryup
[20] TOOL: exit=127 'foundryup: command not found'
[21] CALL terminal: export PATH=\"$PATH:/home/pstar/.foundry/bin\" && foundryup  # JSON-escaped
[22] TOOL: exit=2 syntax error
[23] CALL terminal: bash -c "export PATH=\"$PATH:$HOME/.foundry/bin\" && foundryup"
[24] TOOL: exit=0  # foundryup finally runs
[25] CALL terminal: PATH="$PATH:$HOME/.foundry/bin" forge init --no-git --force
[26] TOOL: exit=0
[27] CALL terminal: PATH="..." forge install pythnet/pyth-crosschain --no-commit
[28] TOOL: exit=2 "error: unexpected argument '--no-commit' found"
[29] CALL terminal: PATH="..." forge install pythnet/pyth-crosschain
[30] TOOL: exit=1 "fatal: not a git repository (or any parent up to mount point /mnt)"
[31] CALL terminal: git init
[32] TOOL: exit=0
[33] CALL terminal: PATH="..." forge install pythnet/pyth-crosschain  # session ends here
```
Note that `forge init --no-git` created the project but left it outside a
git repo, so `forge install` (a `git submodule add`) then fails until the
agent runs `git init`. The `--no-commit` flag is a stale v0 flag that no
longer exists in current forge. Each of these is recoverable in one step,
and the agent does recover — but the session ends *at the recovery*, not
on another mistake.

### Excerpt C — session `69caf6db…`, broken WSL shell invocation
Every single `terminal` call in this session returns the same error:

```
[18] CALL terminal: forge init --force
[19] TOOL: exit=127 stderr='/bin/bash: /c: No such file or directory\n'
[20] CALL terminal: which forge
[21] TOOL: exit=127 stderr='/bin/bash: /c: No such file or directory\n'
[22] CALL terminal: foundryup
[23] TOOL: exit=127 stderr='/bin/bash: /c: No such file or directory\n'
```
No command can reach bash at all — this is a shell-invocation failure
upstream of the agent, not a foundry problem. The agent, unable to use
`terminal`, pivots to `write_file` for the entire scaffold and hits the
25-iteration budget while still writing boilerplate. `tools/terminal.py:170`
builds the proc args as `[_WSL_EXE, "bash", "-i", "-c", shell_cmd]`; the
`/c` error suggests this session was run on an environment where
`_WSL_EXE` resolved to Windows `cmd.exe` (which interprets `/c` as a
switch) or `_win_to_wsl_path` produced a literal `/c/…` cwd that confused
WSL. Not an agent bug.

### Excerpt D — session `69cc0171…`, `bun create vite` silent cancel
Steps #11–#17.

```
[11] CALL terminal: bun create vite . --template react
[12] TOOL: exit=0 stderr='Resolving dependencies...' out='└  Operation cancelled\n\n'
[13] CALL terminal: bun install
[14] TOOL: exit=1 stderr="Bun could not find a package.json file to install from"
[15] CALL terminal: bun init -y   # ← prompt explicitly forbids this
[16] TOOL: exit=0 (writes package.json, index.ts, tsconfig.json)
[17] CALL terminal: rm -rf * && bun create vite . --template react
[18] TOOL: exit=0 out='└  Operation cancelled\n\n'
```
`bun create vite` cancels on missing stdin but returns **exit 0** — the
self-correcting detector in `core/agent.py:141–149` only fires on
`stderr and exit_code != 0`, so the failure is invisible to the agent
until the next `bun install` fails. The agent then tries `bun init -y`
(forbidden by `core/prompt.py:24`) and finally gives up on the scaffolder
and writes files by hand from step #21 onward.

### Excerpt E — sessions `69cc5c54…` and `69cc5d25…`, forward-progress truncation
`69cc5c54…` (7 chunks total), last four steps:
```
[7]  CALL terminal: forge init --no-git --force .   # exit=0
[9]  CALL terminal: forge install pythnet/pyth-crosschain
[10] TOOL: exit=1 "fatal: not a git repository"
[11] CALL terminal: git init                         # exit=0
[13] CALL terminal: forge install pythnet/pyth-crosschain  # session ends
```
No loop. Agent hits the git-repo gotcha once, fixes it, retries — session
terminates before the retry result is written. Same shape in `69cc5d25…`
(4 chunks, session ends on the second `forge install`). The fact that
these land in the "loop" bucket is a consequence of the `ended_mid_loop`
criterion, not agent misbehavior.

## 3. Root hypothesis

Three orthogonal problems sit under this bucket. Ordered by share of
affected sessions:

**(H1) WSL sandbox lacks foundry pre-installed; `bash -i -c` doesn't
preserve PATH across tool calls.**  Affects 2/6 strongly (`69cafdd3`,
`69cb2806`) and is the origin of the bucket name. `tools/terminal.py:174`
starts a fresh `bash -i -c` for each call. foundryup's installer appends
an `export PATH=".../.foundry/bin:$PATH"` line to `~/.bashrc`, but a
default Ubuntu `~/.bashrc` short-circuits early for non-interactive shells
via `case $- in *i*) ;; *) return;; esac`. `bash -i` flips that bit, but
many `.bashrc` versions *also* check `[ -z "$PS1" ] && return` which is
true for `-c` even with `-i`. Net result: foundryup's PATH edit never
takes effect in subsequent tool calls, and the agent has to prepend PATH
manually every single iteration. The agent *can* recover — it just costs
3–5 iterations of reshaping `export PATH=…`, some of which it wastes on
its own quoting mistakes.

**(H2) The prompt has no Foundry-specific guidance and hides
`pyth_deploy`.**  `core/prompt.py:30` mentions `pyth_deploy` as a one-line
tool description but never tells the agent to prefer it over raw `forge`.
`pyth_deploy` in `tools/pyth_deploy.py:57–73` runs `forge build` and
`forge create` directly, with a clear error path if forge is missing
(*"Install it: curl -L https://foundry.paradigm.xyz | bash && foundryup"*).
But the agent is never told that (a) a Pyth-branded deploy tool exists
specifically so it doesn't have to bootstrap forge manually, (b) `forge
install` requires a git repo and `forge init --no-git` is therefore
incompatible with installing dependencies, (c) the `--no-commit` flag was
removed in modern forge. Each gotcha above is one prompt paragraph away
from being a non-issue.

**(H3) Tool-result shaping: exit-zero failures are invisible to the
self-correcting signal.**  `bun create vite`'s "Operation cancelled"
returns exit 0 (excerpt D). The stderr heuristic in
`core/agent.py:141–149` only flags `stderr and exit_code != 0`, so the
agent downstream has no hint that scaffolding failed. 1/6 sessions
(`69cc0171`) is directly driven by this, and it co-occurs with the
foundry flow in `69c5c96f` (bucket 3, not in this set but cross-cuts
here).

Underlying all three: the `ended_mid_loop` criterion sweeps genuine
loops (H1), genuine recoveries-in-progress (Excerpt E), and environment
failures (Excerpt C) into one bucket. 4 of 6 sessions in this bucket are
not actually mis-reasoning in their final iteration — they are making
correct next moves that never got to run. Any fix measurement has to
separate "agent got smarter" from "agent had fewer reasons to still be
mid-loop when the WS dropped."

## 4. What a fix would look like

A minimal, tightly-scoped fix is a prompt addition to `core/prompt.py`'s
`TOOL_GUIDANCE` block naming the full forge/foundry bootstrap as one
canonical recipe (`curl | bash` → `~/.foundry/bin/foundryup` → prepend
`$HOME/.foundry/bin` to PATH on every subsequent forge call OR persist
it via a `.bashrc` append that survives `bash -i -c`) plus two sentences
on forge's git requirement and the preferred use of `pyth_deploy`. A
second, independent fix is hardening the terminal tool to pre-install
foundry into the WSL image once (moving H1 out of the agent's concern
entirely). A third, orthogonal fix is widening the self-correcting
detector in `core/agent.py` to also flag known exit-zero-but-cancelled
sentinels like `"Operation cancelled"` in bun output. These three are
independently valuable and can be sequenced by cost; the prompt patch
ships first because it needs no environment change.

## 5. Open questions

1. What exactly terminates these sessions? 5/6 have `status=completed`
   with `error_message=None` but `last chunk has tool_calls` — is this
   WS disconnect (frontend), backend exception swallowed somewhere in
   `/api/agent`, or chunk-writer race? Without this, "did the fix
   help" is hard to measure — Excerpt E sessions would be counted as
   successes for *any* prompt change because they were already on the
   right path.
2. Is foundry pre-installable in the sandbox without widening the attack
   surface? The sandbox hardening at `c23dc73` was the most recent work
   on `tools/terminal.py`; pre-installing a binary that downloads more
   binaries at runtime is a meaningful trust decision.
3. Does `bash -i -c` actually re-source `.bashrc` on every invocation in
   this WSL setup? The evidence in Excerpt A (#18 vs. #22) says no.
   Reproducing that in a one-off test would either justify
   pre-installation or unlock a much smaller fix (`env["PATH"] += ...`
   in `tools/terminal.py:128`).
4. Should `pyth_deploy` absorb the `forge install pythnet/pyth-crosschain`
   step too, so agents never need to touch forge directly for the
   happy-path Entropy deploy? That would be a tool-surface change, not
   a prompt change.
5. Is `bun create vite .`'s "Operation cancelled" stable across bun
   versions (1.3.11 observed), or is this a moving target that would
   make a string-match detector brittle? Alternative: always scaffold
   vite manually via `write_file` and skip `bun create vite` entirely.
