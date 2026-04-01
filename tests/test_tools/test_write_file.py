# tests/test_tools/test_write_file.py
import os
import pytest
from core.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    from tools import write_file
    write_file.register(reg)
    return reg


class TestWriteFile:
    def test_write_new_file(self, registry, tmp_path):
        path = str(tmp_path / "new.txt")
        result = registry.dispatch("write_file", {"path": path, "content": "hello world"})
        assert "ok" in result.lower() or "wrote" in result.lower() or "\u2713" in result
        assert open(path).read() == "hello world"

    def test_overwrite_existing_file(self, registry, tmp_path):
        path = str(tmp_path / "existing.txt")
        with open(path, "w") as f:
            f.write("old content")
        registry.dispatch("write_file", {"path": path, "content": "new content"})
        assert open(path).read() == "new content"

    def test_creates_parent_directories(self, registry, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "dir" / "file.txt")
        result = registry.dispatch("write_file", {"path": path, "content": "nested"})
        assert os.path.exists(path)
        assert open(path).read() == "nested"

    def test_write_empty_content(self, registry, tmp_path):
        path = str(tmp_path / "empty.txt")
        registry.dispatch("write_file", {"path": path, "content": ""})
        assert open(path).read() == ""
