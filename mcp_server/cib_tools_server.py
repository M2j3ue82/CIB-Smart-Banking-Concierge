"""
cib_tools_server.py
===================
A small MCP (Model Context Protocol) server that gives the CIB assistant one extra tool:

    get_exchange_rate(from_currency, to_currency, amount)

It runs locally over "Streamable HTTP" and is consumed by the n8n *MCP Client Tool* node.

Run (from the project folder, with the virtual environment active):
    python mcp_server\\cib_tools_server.py

Default endpoint:  http://127.0.0.1:8765/mcp
Environment variables (optional): CIB_MCP_HOST, CIB_MCP_PORT
"""

from __future__ import annotations

import json
import logging
import os

from mcp.server.fastmcp import FastMCP

from fx_logic import ExchangeRateService

HOST = os.getenv("CIB_MCP_HOST", "127.0.0.1")  # keep 127.0.0.1 unless n8n runs in Docker
PORT = int(os.getenv("CIB_MCP_PORT", "8765"))

# stateless_http: the tool keeps no per-client state, so no session handling is needed.
# json_response: plain JSON replies, which are simpler for clients such as n8n.
mcp = FastMCP("cib-tools", host=HOST, port=PORT, stateless_http=True, json_response=True)

service = ExchangeRateService()


@mcp.tool()
def get_exchange_rate(from_currency: str, to_currency: str, amount: float = 1.0) -> str:
    """Get an INDICATIVE exchange rate and convert an amount between two currencies.

    Use this tool only when the customer asks about a currency exchange rate or a
    currency conversion. The rate comes from a free public source and is NOT the
    CIB rate. Always tell the customer that, and mention the last update time.

    Args:
        from_currency: 3-letter code of the source currency, for example "USD".
        to_currency: 3-letter code of the target currency, for example "EGP".
        amount: amount in the source currency (default 1).

    Returns:
        A JSON string with status, pair, rate, converted_amount, last_update_utc,
        source, attribution and disclaimer_ar. On failure status is "error".
    """
    return json.dumps(service.get_rate(from_currency, to_currency, amount), ensure_ascii=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger(__name__).info("CIB tools MCP server on http://%s:%s/mcp", HOST, PORT)
    mcp.run(transport="streamable-http")
