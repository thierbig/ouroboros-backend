# tests/test_tools/test_read_file.py
import os
import pytest
from core.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    from tools import read_file
    read_file.register(reg)
    return reg


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("line one\nline two\nline three\nline four\nline five\n")
    return str(f)


class TestReadFile:
    def test_read_full_file(self, registry, sample_file):
        result = registry.dispatch("read_file", {"path": sample_file})
        assert "1|line one" in result
        assert "5|line five" in result

    def test_read_with_offset_and_limit(self, registry, sample_file):
        result = registry.dispatch("read_file", {"path": sample_file, "offset": 2, "limit": 2})
        assert "2|line two" in result
        assert "3|line three" in result
        assert "1|line one" not in result
        assert "4|line four" not in result

    def test_read_missing_file(self, registry):
        result = registry.dispatch("read_file", {"path": "/nonexistent/file.txt"})
        assert "error" in result.lower() or "not found" in result.lower()

    def test_read_empty_file(self, registry, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = registry.dispatch("read_file", {"path": str(f)})
        assert isinstance(result, str)

    def test_line_numbers_are_correct(self, registry, sample_file):
        result = registry.dispatch("read_file", {"path": sample_file})
        lines = [l for l in result.strip().split("\n") if l]
        for i, line in enumerate(lines, 1):
            assert line.startswith(f"{i}|")
