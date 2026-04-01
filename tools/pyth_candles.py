"""Fetch OHLC candlestick data from Pyth Network via MCP server."""

import json
from datetime import datetime, timezone

SCHEMA = {
    "name": "pyth_candles",
    "description": (
        "Fetch OHLC candlestick data for charting and technical analysis. "
        "Returns open, high, low, close prices at specified time intervals. "
        "Useful for building price charts, detecting trends, or analyzing volatility. "
        "Powered by the official Pyth MCP Server."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Pyth symbol, e.g. 'Crypto.BTC/USD'. Use pyth_search to find symbols.",
            },
            "resolution": {
                "type": "string",
                "description": (
                    "Candle interval: '1' (1min), '5', '15', '30', '60' (1h), "
                    "'120' (2h), '240' (4h), '360' (6h), '720' (12h), 'D' (day), 'W' (week), 'M' (month)"
                ),
            },
            "hours_back": {
                "type": "integer",
                "description": "How many hours of data to fetch (default 24). Alternative to from/to timestamps.",
            },
            "from_timestamp": {
                "type": "integer",
                "description": "Start time as Unix timestamp (optional, overrides hours_back)",
            },
            "to_timestamp": {
                "type": "integer",
                "description": "End time as Unix timestamp (optional, defaults to now)",
            },
        },
        "required": ["symbol", "resolution"],
    },
}

VALID_RESOLUTIONS = {"1", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}


def handle(args: dict, working_dir: str | None = None) -> str:
    import time
    from tools.pyth_mcp import call_tool

    symbol = args.get("symbol", "")
    resolution = str(args.get("resolution", "60"))

    if not symbol:
        return "Error: symbol is required"
    if resolution not in VALID_RESOLUTIONS:
        return f"Error: invalid resolution '{resolution}'. Valid: {', '.join(sorted(VALID_RESOLUTIONS))}"

    to_ts = args.get("to_timestamp", int(time.time()))
    if args.get("from_timestamp"):
        from_ts = args["from_timestamp"]
    else:
        hours = args.get("hours_back", 24)
        from_ts = to_ts - (hours * 3600)

    try:
        data = call_tool("get_candlestick_data", {
            "symbol": symbol,
            "resolution": resolution,
            "from": int(from_ts),
            "to": int(to_ts),
        })
    except Exception as e:
        return f"Error fetching candles: {e}"

    if not isinstance(data, dict) or data.get("s") != "ok":
        return f"No candlestick data returned for {symbol}"

    timestamps = data.get("t", [])
    opens = data.get("o", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    closes = data.get("c", [])

    if not timestamps:
        return f"No candles returned for {symbol} with resolution {resolution}"

    res_label = {
        "1": "1min", "5": "5min", "15": "15min", "30": "30min",
        "60": "1h", "120": "2h", "240": "4h", "360": "6h", "720": "12h",
        "D": "daily", "W": "weekly", "M": "monthly",
    }.get(resolution, resolution)

    lines = [f"Pyth {res_label} Candles: {symbol} ({len(timestamps)} candles)"]
    lines.append("")
    lines.append(f"  {'Time':<20} {'Open':>12} {'High':>12} {'Low':>12} {'Close':>12}")
    lines.append(f"  {'─'*20} {'─'*12} {'─'*12} {'─'*12} {'─'*12}")

    for i in range(len(timestamps)):
        ts = datetime.fromtimestamp(timestamps[i], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        o = opens[i] if i < len(opens) else 0
        h = highs[i] if i < len(highs) else 0
        l = lows[i] if i < len(lows) else 0
        c = closes[i] if i < len(closes) else 0
        lines.append(f"  {ts:<20} ${o:>11,.2f} ${h:>11,.2f} ${l:>11,.2f} ${c:>11,.2f}")

    # Summary
    if closes:
        first_open = opens[0] if opens else 0
        last_close = closes[-1] if closes else 0
        change = last_close - first_open
        pct = (change / first_open * 100) if first_open else 0
        high_max = max(highs) if highs else 0
        low_min = min(lows) if lows else 0

        lines.append("")
        lines.append(f"  Period Change: ${change:+,.2f} ({pct:+.2f}%)")
        lines.append(f"  Period High:   ${high_max:,.2f}")
        lines.append(f"  Period Low:    ${low_min:,.2f}")

    return "\n".join(lines)


def register(reg):
    reg.register("pyth_candles", SCHEMA, handle)
