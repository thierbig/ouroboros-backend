# Fix: hallucinated-deployment-success guard

## What changed

Added a new `TRUTHFUL_REPORTING` section to `core/prompt.py` and wired
it into `build_system_prompt()` between `SECURITY_RULES` and
`TOOL_GUIDANCE`. The section forbids claiming deploy/build/site
success when the immediately-preceding tool result carried an error
(non-empty `error` field, non-zero `exit_code`, or a known failure
sentinel such as `DEPLOYER_PRIVATE_KEY`), forbids fabricating URLs /
site names / contract addresses / tx hashes, and requires the agent
to verify any URL it reports with a subsequent tool call
(`npx netlify-cli sites:list`, `netlify-cli status`, or `curl -sI`)
before declaring success. A final bullet calls out the
exit-zero-cancels pathology from `analysis/exit_zero_cancels.md` §1:
a JSON tool result containing `"error"` is authoritative even when
`exit_code == 0`.

Approach A (prompt-only) was sufficient — no `core/agent.py` change
was needed. The Foundry recipe added by Task #7 was left untouched.

## Replays targeted

Per `analysis/baseline.md` §"Hallucinated-deployment failure mode",
all five replays that ended with a fabricated Netlify URL after a
`pyth_deploy` env-var error:

- `69cafdd3c9ee05a19b45638a` — `pyth_deploy` err x2, hallucinated URL
- `69cb280662972386aaf55ff4` — `pyth_deploy` err x2, hallucinated URL
- `69cc5c542447cfb1b234d419` — `pyth_deploy` err x4, hallucinated URL
- `69cc5d252447cfb1b234d422` — `pyth_deploy` err x2, hallucinated URL
- `69c5c96fd00e0eacbd9bc64f` — `pyth_deploy` err x2, hallucinated URL

Each of these sessions had a final assistant message that read like a
completion ("Deployed to `https://testo-testo-coin-flip.netlify.app`")
with no preceding `netlify-cli` invocation and no successful
`pyth_deploy` return. The classifier cannot detect this kind of
silent-success failure from the transcript shape alone — the only
leverage is keeping the failure from being emitted in the first place.

## Manual verification

The easiest repro is the one called out in the task brief: stub
`pyth_deploy` to return `{"error": "DEPLOYER_PRIVATE_KEY is not set"}`
and prompt the agent to deploy a coin-flip contract. Pre-fix, the
final assistant turn contained `deployed` and a fabricated
`.netlify.app` URL. Post-fix, the rendered system prompt includes
four hard guardrails the agent must apply on that turn:

1. MUST NOT claim the deploy succeeded when the last tool result
   carried an error.
2. Never fabricate a URL / site name / address / tx hash.
3. Must verify any reported URL with a subsequent tool call before
   claiming success.
4. A JSON `error` field overrides a zero exit code.

End-to-end validation against the live replay driver is a Phase 3
activity (see `baseline.md` §"Phase 3 enablement requests") and
requires `DEPLOYER_PRIVATE_KEY` to be populated so the deploy path is
actually reached; the prompt-text guardrails encoded here are what
Phase 2 is accountable for.

## Tests

`tests/test_hallucination_guard.py` — five assertions against the
rendered prompt, each of which fails on `main` (pre-fix) because the
required markers were absent, and each of which passes after the
edit. All four Task #7 `tests/test_prompt.py` assertions continue
to pass (the Foundry recipe is untouched).

```
$ python -m pytest tests/test_hallucination_guard.py tests/test_prompt.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\thier\ouroboros-backend
configfile: pytest.ini
collected 9 items

tests/test_hallucination_guard.py::test_prompt_forbids_claiming_success_after_tool_error PASSED
tests/test_hallucination_guard.py::test_prompt_forbids_fabricating_urls                    PASSED
tests/test_hallucination_guard.py::test_prompt_requires_url_verification                   PASSED
tests/test_hallucination_guard.py::test_prompt_mentions_pyth_deploy_error_implication      PASSED
tests/test_hallucination_guard.py::test_prompt_treats_error_field_as_authoritative         PASSED
tests/test_prompt.py::test_foundry_recipe_mentions_pyth_deploy_preference                  PASSED
tests/test_prompt.py::test_foundry_recipe_mentions_path_prepend                            PASSED
tests/test_prompt.py::test_foundry_recipe_mentions_git_requirement                         PASSED
tests/test_prompt.py::test_foundry_recipe_warns_no_commit_flag_removed                     PASSED

============================== 9 passed in 0.02s ==============================
```

## Non-goals / left for later

- Approach B (agent-loop tagging of assistant messages that follow a
  tool error) was not implemented — Approach A covers the five
  replays on a prompt-only basis, and the task brief specifies "Pick
  A unless you find a reason in the replay logs." No such reason
  surfaced.
- An integration-style test that stubs a tool to return an error and
  asserts the final assistant text does not contain "deployed" was
  NOT wired up here: the agent loop is non-deterministic against a
  live LLM and would require a mocked Anthropic client with a scripted
  response sequence to be both fast and stable. Flagged for Phase 3
  alongside the replay-driver work once `DEPLOYER_PRIVATE_KEY` is
  populated.
- The per-project `CLAUDE.md` template issue flagged in `baseline.md`
  §"Phase 3 enablement requests" item 2 is still outstanding and is
  not affected by this fix.
