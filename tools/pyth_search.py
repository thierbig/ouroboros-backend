"""Search available Pyth Network price feeds via MCP server."""

import json

SCHEMA = {
    "name": "pyth_search",
    "description": (
        "Search available Pyth Network price feeds. "
        "Returns matching feeds with symbol, asset type, feed ID, and description. "
        "Useful for discovering which assets are available on Pyth. "
        "Powered by the official Pyth MCP Server."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, e.g. 'bitcoin', 'ETH', 'gold', 'nvidia', 'forex'",
            },
            "asset_type": {
                "type": "string",
                "description": "Optional filter: 'crypto', 'equity', 'fx', 'metal', 'rates'",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10, max 50)",
            },
        },
        "required": ["query"],
    },
}

MAX_RESULTS = 15


def handle(args: dict, working_dir: str | None = None) -> str:
    from tools.pyth_mcp import call_tool

    query = args.get("query", "")
    if not query:
        return "Error: query is required"

    mcp_args = {"query": query, "limit": min(args.get("limit", MAX_RESULTS), 50)}
    if args.get("asset_type"):
        mcp_args["asset_type"] = args["asset_type"]

    try:
        data = call_tool("get_symbols", mcp_args)
    except Exception as e:
        return f"Error querying Pyth MCP: {e}"

    feeds = data.get("feeds", []) if isinstance(data, dict) else []
    total = data.get("count", len(feeds)) if isinstance(data, dict) else 0

    if not feeds:
        return f"No Pyth price feeds found for: '{query}'"

    lines = [f"Pyth Price Feeds matching '{query}' ({total} total, showing {len(feeds)}):"]
    lines.append("")

    for i, feed in enumerate(feeds, 1):
        symbol = feed.get("symbol", "N/A")
        desc = feed.get("description", "N/A")
        a_type = feed.get("asset_type", "N/A")
        hermes_id = feed.get("hermes_id", "")
        lines.append(f"  {i}. {symbol}")
        lines.append(f"     {desc}")
        lines.append(f"     Type: {a_type}  |  Feed ID: 0x{hermes_id}")
        lines.append("")

    return "\n".join(lines)


def register(reg):
    reg.register("pyth_search", SCHEMA, handle)
