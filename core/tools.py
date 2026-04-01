"""Tool discovery -- creates a registry with all tools registered."""

from core.registry import ToolRegistry
from tools import (
    read_file, write_file, patch, terminal, search_files,
    pyth_price, pyth_search, pyth_history, pyth_candles, pyth_deploy,
)


def create_tool_registry() -> ToolRegistry:
    """Create a fresh registry with all tools registered."""
    reg = ToolRegistry()
    read_file.register(reg)
    write_file.register(reg)
    patch.register(reg)
    terminal.register(reg)
    search_files.register(reg)
    pyth_price.register(reg)
    pyth_search.register(reg)
    pyth_history.register(reg)
    pyth_candles.register(reg)
    pyth_deploy.register(reg)
    return reg
