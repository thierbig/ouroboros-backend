"""Fetch real-time prices from Pyth Network via Hermes API."""

import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

SCHEMA = {
    "name": "pyth_price",
    "description": (
        "Fetch real-time asset prices from Pyth Network. "
        "Provide a symbol like 'BTC/USD' or 'BTC' to get the latest price, "
        "confidence interval, EMA price, and feed metadata. "
        "Uses Pyth Hermes API for reliable, low-latency price data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "Asset symbol to look up, e.g. 'BTC/USD', 'ETH', 'SOL/USD'. "
                    "Common symbols are resolved instantly; others are searched via Hermes."
                ),
            },
        },
        "required": ["symbol"],
    },
}

# Common Pyth price feed IDs (mainnet/stable)
COMMON_FEEDS = {
    "BTC/USD":  "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH/USD":  "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "SOL/USD":  "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "BNB/USD":  "0x2f95862b045670cd22bee3114c39763a4a08beeb663b145d283c31d7d1101c4f",
    "DOGE/USD": "0xdcef50dd0a4cd2dcc17e45df1676dcb336a11a61c69df7a0299b0150c672d25c",
    "AVAX/USD": "0x93da3352f9f1d105fdfe4971cfa80e9dd777bfc5d0f683ebb6e1571f73c88f49",
    "LINK/USD": "0x8ac0c70fff57e9aefdf5edf44b51d62c2d433653cbb2cf5cc06bb115af04d221",
    "PYTH/USD": "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff",
    "ARB/USD":  "0x3fa4252848f9f0a1480be62745a4629d9eb1322aebab8a791e344b3b9c1adcf5",
    "OP/USD":   "0x385f64d993f7b77d8182ed5003d97c60aa3361f3cecfe711544d2d59165e9bdf",
}

HERMES_BASE = "https://hermes.pyth.network"


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to 'XXX/USD' format."""
    s = symbol.strip().upper()
    if "/" not in s:
        s = f"{s}/USD"
    return s


def _resolve_feed_id(symbol: str) -> str | None:
    """Resolve a symbol to a Pyth feed ID, searching Hermes if needed."""
    normalized = _normalize_symbol(symbol)

    # Check common feeds first
    if normalized in COMMON_FEEDS:
        return COMMON_FEEDS[normalized]

    # Search Hermes for the feed
    base_symbol = normalized.split("/")[0]
    search_url = f"{HERMES_BASE}/v2/price_feeds?query={urllib.parse.quote(base_symbol)}"
    try:
        req = urllib.request.Request(search_url, headers={"Accept": "application/json", "User-Agent": "Ouroboros/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            feeds = json.loads(resp.read().decode())
            # Look for exact match on the symbol
            for feed in feeds:
                attrs = feed.get("attributes", {})
                feed_symbol = attrs.get("symbol", "").upper()
                if feed_symbol == normalized or feed_symbol == base_symbol:
                    return "0x" + feed["id"]
            # If no exact match, return first result
            if feeds:
                return "0x" + feeds[0]["id"]
    except Exception:
        pass
    return None


def _format_price(price_obj: dict, expo: int) -> str:
    """Format a Pyth price value with its exponent."""
    raw = int(price_obj.get("price", "0"))
    value = raw * (10 ** expo)
    if expo < 0:
        decimals = abs(expo)
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


def handle(args: dict, working_dir: str | None = None) -> str:
    symbol = args.get("symbol", "")
    if not symbol:
        return json.dumps({"error": "symbol is required"})

    normalized = _normalize_symbol(symbol)
    feed_id = _resolve_feed_id(symbol)

    if not feed_id:
        return json.dumps({"error": f"Could not find Pyth price feed for '{symbol}'"})

    # Strip 0x prefix for the API call
    feed_id_bare = feed_id[2:] if feed_id.startswith("0x") else feed_id
    url = f"{HERMES_BASE}/v2/updates/price/latest?ids[]={feed_id_bare}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Ouroboros/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"Hermes API error: {e.code} {e.reason}"})
    except Exception as e:
        return json.dumps({"error": f"Request failed: {e}"})

    parsed = data.get("parsed", [])
    if not parsed:
        return json.dumps({"error": "No price data returned from Hermes"})

    entry = parsed[0]
    price_data = entry.get("price", {})
    ema_data = entry.get("ema_price", {})
    expo = int(price_data.get("expo", 0))

    price_str = _format_price(price_data, expo)
    conf_raw = int(price_data.get("conf", "0"))
    conf_val = conf_raw * (10 ** expo)
    ema_str = _format_price(ema_data, expo)

    ts = int(price_data.get("publish_time", 0))
    time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "N/A"

    result = (
        f"Pyth Price Feed: {normalized}\n"
        f"  Price:       ${price_str}\n"
        f"  Confidence:  +/- ${conf_val:,.{abs(expo)}f}\n"
        f"  EMA Price:   ${ema_str}\n"
        f"  Timestamp:   {time_str}\n"
        f"  Feed ID:     {feed_id}"
    )
    return result


def register(reg):
    reg.register("pyth_price", SCHEMA, handle)
