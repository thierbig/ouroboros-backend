"""Fetch historical price data from Pyth Network via MCP server."""

import json
from datetime import datetime, timezone

SCHEMA = {
    "name": "pyth_history",
    "description": (
        "Get historical price data for assets at a specific point in time. "
        "Useful for comparing past prices, building historical charts, or "
        "checking what an asset was worth at a given moment. "
        "Powered by the official Pyth MCP Server."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of Pyth symbols to look up, e.g. ['Crypto.BTC/USD', 'Crypto.ETH/USD']. "
                    "Use pyth_search first to find the exact symbol format. Max 50."
                ),
            },
            "timestamp": {
                "type": "integer",
                "description": "Unix timestamp for the historical point in time",
            },
        },
        "required": ["symbols", "timestamp"],
    },
}


def handle(args: dict, working_dir: str | None = None) -> str:
    from tools.pyth_mcp import call_tool

    symbols = args.get("symbols", [])
    timestamp = args.get("timestamp")

    if not symbols:
        return "Error: symbols list is required"
    if not timestamp:
        return "Error: timestamp is required"

    try:
        data = call_tool("get_historical_price", {
            "symbols": symbols[:50],
            "timestamp": int(timestamp),
        })
    except Exception as e:
        return f"Error fetching historical prices: {e}"

    if not data or (isinstance(data, list) and len(data) == 0):
        return "No historical data returned"

    entries = data if isinstance(data, list) else [data]
    time_str = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"Pyth Historical Prices @ {time_str}:"]
    lines.append("")

    for entry in entries:
        price = entry.get("display_price") or entry.get("price", "N/A")
        bid = entry.get("display_bid", "")
        ask = entry.get("display_ask", "")
        feed_id = entry.get("price_feed_id", "?")

        # Try to match symbol from input
        symbol = symbols[entries.index(entry)] if entries.index(entry) < len(symbols) else f"Feed #{feed_id}"

        lines.append(f"  {symbol}")
        lines.append(f"    Price: ${price:,.2f}" if isinstance(price, (int, float)) else f"    Price: {price}")
        if bid:
            lines.append(f"    Bid:   ${bid:,.2f}" if isinstance(bid, (int, float)) else f"    Bid:   {bid}")
        if ask:
            lines.append(f"    Ask:   ${ask:,.2f}" if isinstance(ask, (int, float)) else f"    Ask:   {ask}")
        lines.append("")

    return "\n".join(lines)


def register(reg):
    reg.register("pyth_history", SCHEMA, handle)
