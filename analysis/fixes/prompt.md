# Fix: prompt — Foundry / Solidity deploy recipe

## What changed

Added a "Foundry / Solidity deploy recipe" section to `TOOL_GUIDANCE` in `core/prompt.py`, slotted between the "Common Feed IDs" block and the "Workflow" block. The section tells the agent to (1) prefer `pyth_deploy` over raw forge for Entropy deploys, (2) install foundry via `curl | bash` → `$HOME/.foundry/bin/foundryup` and prepend `$HOME/.foundry/bin` to PATH on every subsequent forge/cast call because the sandbox shell is non-persistent, (3) run `git init` before `forge install` (which uses `git submodule add` under the hood and therefore requires a repo), and (4) avoid the removed-in-modern-forge `--no-commit` flag. One sentence also warns against JSON-escaped quotes in terminal commands — a concrete mistake observed in replay session 69cafdd3.

## Replays targeted

- `analysis/dumps/69cafdd3…` — PATH dance + JSON-escaped quotes syntax error (excerpt A in root cause doc).
- `analysis/dumps/69cb2806…` — PATH dance + `forge install --no-commit` stale flag + `forge init --no-git` → `forge install` fails on missing git repo (excerpt B).

Both sessions burned 3–5 turns on these avoidable gotchas; each gotcha is now one prompt paragraph away from being a non-issue (per root-cause §4, H2).

## Manual verification

Pre-fix `grep` of the four markers in the rendered prompt returns 0 hits:

```
"Prefer `pyth_deploy`"   → absent
"$HOME/.foundry/bin"     → absent
"--no-commit"            → absent
"forge install" + "git"  → "git" absent from the prompt entirely
```

Post-fix diff of the rendered `TOOL_GUIDANCE` block (only the additive hunk shown):

```
+## Foundry / Solidity deploy recipe
+
+**Prefer `pyth_deploy` over raw forge** for Entropy deployments. It wraps `forge build` + `forge create`, targets Base Sepolia, and knows the Pyth Entropy contract address — you do not need to bootstrap forge yourself for the happy path.
+
+If you must drive forge directly, the sandbox does not have it pre-installed and each `terminal` call runs in a fresh non-persistent shell — PATH edits written by the foundry installer to `~/.bashrc` do NOT survive to the next tool call. Canonical recipe:
+
+1. `curl -L https://foundry.paradigm.xyz | bash` (installs the `foundryup` bootstrapper into `$HOME/.foundry/bin`).
+2. `$HOME/.foundry/bin/foundryup` (installs `forge`, `cast`, `anvil`).
+3. On EVERY subsequent forge/cast command, prepend PATH inline: `PATH="$HOME/.foundry/bin:$PATH" forge …`. Do NOT rely on `source ~/.bashrc` — it will not stick.
+
+Gotchas that burn iterations:
+- `forge install <dep>` runs `git submodule add` under the hood — it requires a git repo. If you used `forge init --no-git` (or just don't have `.git/`), run `git init` first, otherwise install fails with *"fatal: not a git repository"*.
+- The `--no-commit` flag was REMOVED in modern forge. Do not pass it — `forge install pythnet/pyth-crosschain` is the current form, not `forge install pythnet/pyth-crosschain --no-commit`.
+- Never emit JSON-escaped quotes (`\"`) inside a terminal command. Use plain `"` — `PATH="$HOME/.foundry/bin:$PATH" forge …`.
```

## Tests

`tests/test_prompt.py` — 4 assertions that the rendered prompt contains each of the four markers. Would have failed on `main` prior to this change (none of the four strings were present), passes after the edit.

```
$ python -m pytest tests/test_prompt.py -v
tests/test_prompt.py::test_foundry_recipe_mentions_pyth_deploy_preference PASSED
tests/test_prompt.py::test_foundry_recipe_mentions_path_prepend            PASSED
tests/test_prompt.py::test_foundry_recipe_mentions_git_requirement         PASSED
tests/test_prompt.py::test_foundry_recipe_warns_no_commit_flag_removed     PASSED
============================== 4 passed in 0.04s ==============================
```

## Non-goals / left for later

- H1 (pre-install foundry in the WSL image) — environment change, not a prompt change. Tracked in root-cause §5 Q2.
- H3 (widen self-correcting detector for exit-zero-but-cancelled bun output) — `core/agent.py` change, out of scope for this fix (separate fixer owns agent.py).
- Absorbing `forge install pythnet/pyth-crosschain` into `pyth_deploy` — tool-surface change, root-cause §5 Q4.
