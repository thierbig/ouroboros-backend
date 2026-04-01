# tests/test_registry.py
import pytest
from core.registry import ToolRegistry


class TestToolRegistry:
    def setup_method(self):
        """Fresh registry for each test."""
        self.registry = ToolRegistry()

    def test_register_and_dispatch(self):
        schema = {
            "name": "greet",
            "description": "Say hello",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        self.registry.register("greet", schema, lambda args: f"Hello, {args['name']}!")

        result = self.registry.dispatch("greet", {"name": "Thierry"})
        assert result == "Hello, Thierry!"

    def test_dispatch_unknown_tool(self):
        result = self.registry.dispatch("nonexistent", {})
        assert "error" in result.lower() or "unknown" in result.lower()

    def test_get_definitions_returns_schemas(self):
        schema = {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {}},
        }
        self.registry.register("test_tool", schema, lambda args: "ok")

        definitions = self.registry.get_definitions()
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "test_tool"
        assert definitions[0]["type"] == "function"

    def test_get_definitions_openai_format(self):
        schema = {
            "name": "my_tool",
            "description": "Does stuff",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        }
        self.registry.register("my_tool", schema, lambda args: "ok")

        definitions = self.registry.get_definitions()
        tool_def = definitions[0]
        assert tool_def["type"] == "function"
        assert "function" in tool_def
        assert tool_def["function"]["name"] == "my_tool"
        assert tool_def["function"]["description"] == "Does stuff"
        assert "parameters" in tool_def["function"]

    def test_register_multiple_tools(self):
        for i in range(3):
            schema = {
                "name": f"tool_{i}",
                "description": f"Tool {i}",
                "parameters": {"type": "object", "properties": {}},
            }
            self.registry.register(f"tool_{i}", schema, lambda args, i=i: f"result_{i}")

        assert len(self.registry.get_definitions()) == 3
        assert self.registry.dispatch("tool_1", {}) == "result_1"

    def test_dispatch_catches_handler_exception(self):
        def bad_handler(args):
            raise ValueError("Something broke")

        schema = {
            "name": "bad_tool",
            "description": "Breaks",
            "parameters": {"type": "object", "properties": {}},
        }
        self.registry.register("bad_tool", schema, bad_handler)

        result = self.registry.dispatch("bad_tool", {})
        assert "error" in result.lower()
        assert "Something broke" in result

    def test_get_tool_names(self):
        for name in ["alpha", "beta", "gamma"]:
            schema = {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            }
            self.registry.register(name, schema, lambda args: "ok")

        names = self.registry.get_tool_names()
        assert set(names) == {"alpha", "beta", "gamma"}
