"""Guards against the hallucinated-deployment-success failure mode.

Five of seven Phase 1 replay runs ended with the agent declaring a
Netlify URL "deployed" after `pyth_deploy` returned an explicit error
and without running any verification command. See
`analysis/baseline.md` §"Hallucinated-deployment failure mode" and
`analysis/fixes/hallucinated_deploy.md`.

These tests assert that the rendered system prompt contains the
markers we added to `core/prompt.py` to block that failure mode.
"""

from core.prompt import build_system_prompt


def test_prompt_forbids_claiming_success_after_tool_error():
    prompt = build_system_prompt()
    assert "MUST NOT claim" in prompt, (
        "Prompt must explicitly forbid claiming deploy/build success when the "
        "preceding tool call returned an error."
    )


def test_prompt_forbids_fabricating_urls():
    prompt = build_system_prompt()
    assert "fabricate a URL" in prompt, (
        "Prompt must forbid fabricating URLs/site names/addresses — the agent "
        "may only report values observed in a tool result."
    )


def test_prompt_requires_url_verification():
    prompt = build_system_prompt()
    assert "verify any URL" in prompt, (
        "Prompt must require verifying any reported URL with a subsequent tool "
        "call (curl, netlify-cli status, sites:list) before claiming success."
    )


def test_prompt_mentions_pyth_deploy_error_implication():
    prompt = build_system_prompt()
    assert "pyth_deploy" in prompt and "error" in prompt, (
        "Prompt must tell the agent that a pyth_deploy error means no contract "
        "was deployed — it should not pivot to fabricating a frontend URL."
    )


def test_prompt_treats_error_field_as_authoritative_over_exit_code():
    prompt = build_system_prompt()
    assert "exit_code" in prompt and '"error"' in prompt, (
        "Prompt must call out that a JSON tool result with an `error` field is "
        "a failure even when exit_code is 0 (exit-zero-cancels pathology)."
    )
