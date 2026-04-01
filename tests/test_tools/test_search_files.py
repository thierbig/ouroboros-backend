import os
import json
import pytest
from core.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    from tools import search_files
    # Reset module-level search history between tests
    search_files._search_history.clear()
    search_files.register(reg)
    return reg


@pytest.fixture
def project_dir(tmp_path):
    """Create a small project structure for testing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "README.md").write_text("# My Project\n\nA test project.\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")
    return str(tmp_path)


class TestSearchFiles:
    def test_content_search(self, registry, project_dir):
        result = registry.dispatch("search_files", {
            "pattern": "def main",
            "path": project_dir,
        })
        assert "main.py" in result
        assert "def main" in result

    def test_content_search_no_match(self, registry, project_dir):
        result = registry.dispatch("search_files", {
            "pattern": "nonexistent_function",
            "path": project_dir,
        })
        assert "no matches" in result.lower() or result.strip() == ""

    def test_file_search_by_glob(self, registry, project_dir):
        result = registry.dispatch("search_files", {
            "pattern": "*.py",
            "target": "files",
            "path": project_dir,
        })
        assert "main.py" in result
        assert "utils.py" in result

    def test_file_search_by_glob_md(self, registry, project_dir):
        result = registry.dispatch("search_files", {
            "pattern": "*.md",
            "target": "files",
            "path": project_dir,
        })
        assert "README.md" in result
        assert "main.py" not in result

    def test_content_search_with_file_glob(self, registry, project_dir):
        result = registry.dispatch("search_files", {
            "pattern": "def",
            "path": project_dir,
            "file_glob": "*.py",
        })
        assert "main.py" in result
        assert "README.md" not in result

    def test_repeated_search_detection(self, registry, project_dir):
        """After 4 identical searches, should return a block message."""
        for _ in range(3):
            registry.dispatch("search_files", {
                "pattern": "def main",
                "path": project_dir,
            })
        result = registry.dispatch("search_files", {
            "pattern": "def main",
            "path": project_dir,
        })
        assert "blocked" in result.lower() or "already" in result.lower() or "same search" in result.lower()
