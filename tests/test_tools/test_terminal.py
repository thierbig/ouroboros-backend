# tests/test_tools/test_terminal.py
import json
import os
import pytest
from core.registry import ToolRegistry
from tools import terminal


@pytest.fixture
def registry():
    reg = ToolRegistry()
    terminal.register(reg)
    return reg


class TestTerminal:
    def test_run_simple_command(self, registry):
        result = registry.dispatch("terminal", {"command": "echo hello"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0
        assert "hello" in parsed["output"]

    def test_captures_stderr(self, registry):
        result = registry.dispatch("terminal", {"command": "echo error >&2"})
        parsed = json.loads(result)
        assert "error" in parsed.get("stderr", "") or "error" in parsed.get("output", "")

    def test_returns_exit_code(self, registry):
        result = registry.dispatch("terminal", {"command": "exit 42"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 42

    def test_timeout(self, registry):
        result = registry.dispatch("terminal", {"command": "sleep 30", "timeout": 2})
        parsed = json.loads(result)
        assert parsed["exit_code"] != 0
        assert "timeout" in parsed.get("error", "").lower() or "timed out" in parsed.get("error", "").lower()

    def test_workdir(self, registry, tmp_path):
        result = registry.dispatch("terminal", {"command": "pwd", "workdir": str(tmp_path)})
        parsed = json.loads(result)
        # WSL converts Windows paths to /mnt/c/..., compare the final dir name
        assert tmp_path.name in parsed["output"]

    def test_multiline_output(self, registry):
        result = registry.dispatch("terminal", {"command": "echo line1 && echo line2"})
        parsed = json.loads(result)
        assert "line1" in parsed["output"]
        assert "line2" in parsed["output"]

    def test_result_json_fields(self, registry):
        """Result JSON must use 'output' (not 'stdout') for frontend compatibility."""
        result = registry.dispatch("terminal", {"command": "echo test"})
        parsed = json.loads(result)
        assert "output" in parsed
        assert "exit_code" in parsed
        assert "stderr" in parsed
        assert "error" in parsed


class TestWSL:
    """Tests that commands run in WSL with proper path translation."""

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only")
    def test_uses_wsl(self):
        """On Windows, terminal should use WSL."""
        assert terminal._USE_WSL is True
        assert terminal._WSL_EXE is not None

    def test_runs_in_linux(self, registry):
        """Commands should execute in a Linux environment."""
        result = registry.dispatch("terminal", {"command": "uname -s"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0
        assert "Linux" in parsed["output"]

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only")
    def test_win_to_wsl_path(self):
        """Windows paths should convert to /mnt/ paths."""
        assert terminal._win_to_wsl_path(r"C:\Users\foo\bar") == "/mnt/c/Users/foo/bar"
        assert terminal._win_to_wsl_path(r"D:\projects") == "/mnt/d/projects"

    def test_workdir_translation(self, registry, tmp_path):
        """Windows workdir should be accessible via WSL /mnt/ path."""
        # Create a marker file via Windows
        marker = tmp_path / "wsl_test.txt"
        marker.write_text("found_it")
        result = registry.dispatch("terminal", {
            "command": "cat wsl_test.txt",
            "workdir": str(tmp_path),
        })
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, f"Failed: {parsed['stderr']}"
        assert "found_it" in parsed["output"]

    def test_no_ci_env_var(self, registry):
        """CI=true should NOT be set — it breaks create-vite."""
        result = registry.dispatch("terminal", {"command": "echo $CI"})
        parsed = json.loads(result)
        assert parsed["output"].strip() != "true"


class TestBunInWSL:
    """End-to-end tests that bun works via WSL."""

    def test_bun_found(self, registry):
        """bun should be available in WSL."""
        result = registry.dispatch("terminal", {"command": "which bun"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, f"bun not found: {parsed.get('stderr', '')}"

    def test_bun_runs(self, registry):
        """bun should execute and return a version."""
        result = registry.dispatch("terminal", {"command": "bun --version"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, f"bun failed: {parsed.get('stderr', '')}"
        assert parsed["output"].strip()[0].isdigit()

    def test_forge_found(self, registry):
        """forge should be available in WSL."""
        result = registry.dispatch("terminal", {"command": "which forge"})
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, f"forge not found: {parsed.get('stderr', '')}"

    def test_bun_create_vite(self, registry, tmp_path):
        """bun create vite should scaffold a project in a Windows tmp dir via WSL."""
        workdir = str(tmp_path)
        result = registry.dispatch("terminal", {
            "command": "bun create vite . --template react",
            "workdir": workdir,
            "timeout": 30,
        })
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, (
            f"bun create vite failed (exit {parsed['exit_code']}):\n"
            f"stdout: {parsed['output']}\n"
            f"stderr: {parsed['stderr']}"
        )
        # Verify package.json was created (check from Windows side)
        assert (tmp_path / "package.json").exists(), f"No package.json in {tmp_path}"

    def test_bun_create_vite_in_dirty_dir(self, registry, tmp_path):
        """bun create vite should work even after bun init left dotfiles behind.

        Reproduces the real bug: agent runs bun init, then switches to bun create vite.
        rm -rf * doesn't remove dotfiles, so create-vite sees a non-empty dir and cancels.
        The correct approach is rm -rf .[!.]* * to clear everything.
        """
        workdir = str(tmp_path)
        # Simulate: agent ran bun init first (creates .gitignore, etc.)
        registry.dispatch("terminal", {
            "command": "bun init -y",
            "workdir": workdir,
            "timeout": 15,
        })
        assert (tmp_path / ".gitignore").exists(), "bun init should have created .gitignore"
        # Now clean properly and scaffold — this is the correct command
        result = registry.dispatch("terminal", {
            "command": 'rm -rf .[!.]* * 2>/dev/null; bun create vite . --template react',
            "workdir": workdir,
            "timeout": 30,
        })
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, (
            f"bun create vite in dirty dir failed (exit {parsed['exit_code']}):\n"
            f"stdout: {parsed['output']}\n"
            f"stderr: {parsed['stderr']}"
        )
        assert "cancelled" not in parsed["output"].lower(), "create-vite was cancelled"
        assert (tmp_path / "package.json").exists()

    def test_bun_install(self, registry, tmp_path):
        """bun install should work in a scaffolded project."""
        workdir = str(tmp_path)
        result = registry.dispatch("terminal", {
            "command": "bun create vite . --template react && bun install",
            "workdir": workdir,
            "timeout": 60,
        })
        parsed = json.loads(result)
        assert parsed["exit_code"] == 0, (
            f"bun create + install failed (exit {parsed['exit_code']}):\n"
            f"stderr: {parsed['stderr']}"
        )
        assert (tmp_path / "node_modules").is_dir(), "node_modules not created"
