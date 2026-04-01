"""Execute shell commands with timeout and output capture + live streaming."""

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Callable

# On Windows, use WSL bash for a real Linux environment (bun, forge, etc.)
_USE_WSL = False
_WSL_EXE: str | None = None
if os.name == "nt":
    _WSL_EXE = shutil.which("wsl")
    if _WSL_EXE:
        _USE_WSL = True


def _win_to_wsl_path(win_path: str) -> str:
    """Convert a Windows path to a WSL /mnt/ path."""
    # C:\Users\foo\bar -> /mnt/c/Users/foo/bar
    path = win_path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        path = f"/mnt/{drive}{path[2:]}"
    return path

SCHEMA = {
    "name": "terminal",
    "description": (
        "Execute shell commands in a Linux (WSL) environment. "
        "Captures stdout and stderr separately. "
        "Returns JSON with output, stderr, exit_code, and error fields. "
        "IMPORTANT: Commands run non-interactively (no stdin). Always use "
        "non-interactive flags: --yes, -y, --no-input, --default, etc. "
        "Use `bun` (not npm/yarn) for all JS/TS work. "
        "Use timeout to prevent long-running commands from blocking."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default: 180)",
                "default": 180,
            },
            "workdir": {
                "type": "string",
                "description": "Working directory for the command",
            },
        },
        "required": ["command"],
    },
}

MAX_OUTPUT_CHARS = 50_000

# Global callback for streaming terminal output lines
_stream_callback: Callable[[str], None] | None = None


def set_stream_callback(cb: Callable[[str], None] | None):
    global _stream_callback
    _stream_callback = cb


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = int(MAX_OUTPUT_CHARS * 0.4)
    tail = MAX_OUTPUT_CHARS - head
    return (
        text[:head]
        + f"\n\n[... truncated {len(text) - MAX_OUTPUT_CHARS:,} chars ...]\n\n"
        + text[-tail:]
    )


import re

_SECRET_CMDS = re.compile(
    r"\bcat\b.*\.env|"
    r"\bprintenv\b|"
    r"\b(echo|printf)\b.*\$\w*(KEY|TOKEN|SECRET|PRIVATE|PASSWORD|URI)\b|"
    r"\benv\b\s*$|"
    r"\bset\b\s*$",
    re.IGNORECASE,
)


def handle(args: dict, working_dir: str | None = None) -> str:
    command = args["command"]
    if _SECRET_CMDS.search(command):
        return json.dumps({
            "output": "",
            "stderr": "Blocked: this command may expose secrets",
            "exit_code": 1,
            "error": "Command blocked by security policy",
        })
    timeout = args.get("timeout", 180)
    workdir = working_dir or args.get("workdir", None)

    env = os.environ.copy()
    # Force non-interactive mode — but NOT CI=true which breaks create-vite/scaffolders
    env["NO_COLOR"] = "1"
    env["NONINTERACTIVE"] = "1"
    env["BUN_NO_INSTALL_SIGNAL"] = "1"
    env["npm_config_yes"] = "true"  # auto-yes for npm prompts
    netlify_token = os.environ.get("NETLIFY_AUTH_TOKEN")
    if netlify_token:
        env["NETLIFY_AUTH_TOKEN"] = netlify_token
    netlify_slug = os.environ.get("NETLIFY_ACCOUNT_SLUG")
    if netlify_slug:
        env["NETLIFY_ACCOUNT_SLUG"] = netlify_slug

    # Env vars to forward into WSL via WSLENV (WSL ignores parent env vars
    # unless they're listed in WSLENV).
    _WSL_FORWARD_VARS = [
        "NETLIFY_AUTH_TOKEN", "NETLIFY_ACCOUNT_SLUG",
        "MONGODB_URI", "NO_COLOR", "NONINTERACTIVE",
        "BUN_NO_INSTALL_SIGNAL", "npm_config_yes",
        "DEPLOYER_PRIVATE_KEY", "BASE_SEPOLIA_RPC",
    ]

    # Convert workdir to WSL path if needed
    if _USE_WSL and workdir:
        workdir = _win_to_wsl_path(workdir)

    try:
        # On Windows, run commands inside WSL for real Linux environment.
        # bash -i sources .bashrc (which has bun/forge PATH exports).
        # WSL only forwards env vars listed in WSLENV, so we register ours.
        if _USE_WSL:
            # Build WSLENV list — only include vars that are actually set
            wslenv_parts = []
            for var in _WSL_FORWARD_VARS:
                if env.get(var):
                    wslenv_parts.append(var)
            # Append to any existing WSLENV value
            existing_wslenv = env.get("WSLENV", "")
            if wslenv_parts:
                new_wslenv = ":".join(wslenv_parts)
                env["WSLENV"] = f"{existing_wslenv}:{new_wslenv}" if existing_wslenv else new_wslenv

            shell_cmd = command
            if workdir:
                shell_cmd = f'cd "{workdir}" && {command}'
                workdir = None  # handled inside the shell command
            proc_args = [_WSL_EXE, "bash", "-i", "-c", shell_cmd]
            use_shell = False
        else:
            proc_args = command
            use_shell = True

        proc = subprocess.Popen(
            proc_args,
            shell=use_shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=env,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def read_stream(stream, lines_list, is_stderr=False):
            for line in stream:
                lines_list.append(line)
                if _stream_callback:
                    _stream_callback(line)

        # Read stdout and stderr in parallel threads
        stdout_thread = threading.Thread(target=read_stream, args=(proc.stdout, stdout_lines))
        stderr_thread = threading.Thread(target=read_stream, args=(proc.stderr, stderr_lines, True))
        stdout_thread.start()
        stderr_thread.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            return json.dumps({
                "output": _truncate("".join(stdout_lines)),
                "stderr": _truncate("".join(stderr_lines)),
                "exit_code": 124,
                "error": f"Command timed out after {timeout} seconds",
            })

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        return json.dumps({
            "output": _truncate("".join(stdout_lines)),
            "stderr": _truncate("".join(stderr_lines)),
            "exit_code": proc.returncode,
            "error": None,
        })

    except Exception as e:
        return json.dumps({
            "output": "",
            "stderr": "",
            "exit_code": -1,
            "error": f"{type(e).__name__}: {e}",
        })


def register(reg):
    reg.register("terminal", SCHEMA, handle)
