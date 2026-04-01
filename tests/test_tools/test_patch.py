import pytest
from core.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    from tools import patch
    patch.register(reg)
    return reg


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def hello():\n    print('hello')\n\ndef goodbye():\n    print('goodbye')\n")
    return str(f)


class TestPatch:
    def test_replace_string(self, registry, sample_file):
        result = registry.dispatch("patch", {
            "path": sample_file,
            "old_string": "print('hello')",
            "new_string": "print('hi there')",
        })
        assert "✓" in result or "applied" in result.lower()
        content = open(sample_file).read()
        assert "print('hi there')" in content
        assert "print('hello')" not in content

    def test_old_string_not_found_returns_hint(self, registry, sample_file):
        result = registry.dispatch("patch", {
            "path": sample_file,
            "old_string": "this does not exist",
            "new_string": "replacement",
        })
        assert "not found" in result.lower()
        assert "hint" in result.lower() or "read_file" in result.lower()

    def test_file_not_found(self, registry):
        result = registry.dispatch("patch", {
            "path": "/nonexistent/file.py",
            "old_string": "x",
            "new_string": "y",
        })
        assert "error" in result.lower() or "not found" in result.lower()

    def test_delete_text(self, registry, sample_file):
        registry.dispatch("patch", {
            "path": sample_file,
            "old_string": "\ndef goodbye():\n    print('goodbye')\n",
            "new_string": "",
        })
        content = open(sample_file).read()
        assert "goodbye" not in content
        assert "hello" in content

    def test_preserves_rest_of_file(self, registry, sample_file):
        registry.dispatch("patch", {
            "path": sample_file,
            "old_string": "print('hello')",
            "new_string": "print('hi')",
        })
        content = open(sample_file).read()
        assert "def hello():" in content
        assert "def goodbye():" in content
        assert "print('goodbye')" in content

    def test_multiple_occurrences_errors(self, registry, tmp_path):
        f = tmp_path / "dups.py"
        f.write_text("x = 1\nx = 1\n")
        result = registry.dispatch("patch", {
            "path": str(f),
            "old_string": "x = 1",
            "new_string": "x = 2",
        })
        assert "multiple" in result.lower() or "ambiguous" in result.lower() or "unique" in result.lower()
