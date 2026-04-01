"""Shared MCP client for Pyth Network tools."""

import json
import urllib.request

MCP_URL = "https://mcp.pyth.network/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "Ouroboros/1.0",
}

_initialized = False


def _ensure_init():
    """Initialize MCP session if not already done."""
    global _initialized
    if _initialized:
        return
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ouroboros", "version": "1.0"},
        },
    }).encode()
    req = urllib.request.Request(MCP_URL, data=payload, headers=HEADERS, method="POST")
    urllib.request.urlopen(req, timeout=10).read()
    _initialized = True


def call_tool(name: str, arguments: dict) -> dict:
    """Call a tool on the Pyth MCP server. Returns parsed result or raises."""
    _ensure_init()
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(MCP_URL, data=payload, headers=HEADERS, method="POST")
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode())
    result = data.get("result", {})
    content = result.get("content", [{}])
    text = content[0].get("text", "") if content else ""
    if result.get("isError"):
        raise RuntimeError(text)
    return json.loads(text) if text.startswith(("{", "[")) else text
