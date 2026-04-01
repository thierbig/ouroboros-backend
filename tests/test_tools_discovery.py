# tests/test_tools_discovery.py
import pytest
from core.tools import create_tool_registry


class TestToolDiscovery:
    def test_all_tools_registered(self):
        registry = create_tool_registry()
        names = registry.get_tool_names()
        expected = {"read_file", "write_file", "patch", "terminal", "search_files", "update_lessons"}
        assert set(names) == expected

    def test_all_tools_have_definitions(self):
        registry = create_tool_registry()
        definitions = registry.get_definitions()
        assert len(definitions) == 6
        for defn in definitions:
            assert defn["type"] == "function"
            assert "name" in defn["function"]
            assert "description" in defn["function"]
            assert "parameters" in defn["function"]
