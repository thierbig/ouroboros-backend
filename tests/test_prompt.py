"""Tests for core/prompt.py system prompt assembly."""

from core.prompt import build_system_prompt


def test_foundry_recipe_mentions_pyth_deploy_preference():
    prompt = build_system_prompt()
    assert "Prefer `pyth_deploy`" in prompt, (
        "Prompt must steer agents toward pyth_deploy for Entropy deploys "
        "instead of driving forge manually."
    )


def test_foundry_recipe_mentions_path_prepend():
    prompt = build_system_prompt()
    assert "$HOME/.foundry/bin" in prompt, (
        "Prompt must tell the agent to prepend $HOME/.foundry/bin to PATH "
        "on every forge/cast call — the sandbox shell is non-persistent."
    )


def test_foundry_recipe_mentions_git_requirement():
    prompt = build_system_prompt()
    assert "forge install" in prompt and "git" in prompt, (
        "Prompt must warn that forge install requires a git repo "
        "(incompatible with `forge init --no-git`)."
    )


def test_foundry_recipe_warns_no_commit_flag_removed():
    prompt = build_system_prompt()
    assert "--no-commit" in prompt, (
        "Prompt must warn that the --no-commit flag was removed in modern forge."
    )
