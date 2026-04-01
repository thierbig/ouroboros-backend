"""Tool registry -- singleton that holds tool schemas and dispatches calls."""

from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}

    def register(self, name: str, schema: dict, handler: Callable) -> None:
        self._tools[name] = ToolEntry(name=name, schema=schema, handler=handler)

    def get_definitions(self) -> list[dict]:
        """Return tool schemas in OpenAI function-calling format."""
        definitions = []
        for entry in self._tools.values():
            definitions.append({
                "type": "function",
                "function": {
                    "name": entry.schema["name"],
                    "description": entry.schema.get("description", ""),
                    "parameters": entry.schema.get("parameters", {}),
                },
            })
        return definitions

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        """Execute a tool handler by name. Extra kwargs passed to handler if it accepts them."""
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'. Available tools: {', '.join(self._tools.keys())}"
        try:
            import inspect
            handler = self._tools[name].handler
            sig = inspect.signature(handler)
            # Pass kwargs only if the handler accepts them
            accepted = {}
            for k, v in kwargs.items():
                if k in sig.parameters:
                    accepted[k] = v
            result = handler(args, **accepted)
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            return f"Error executing tool '{name}': {type(e).__name__}: {e}"

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())


# Module-level singleton
registry = ToolRegistry()
