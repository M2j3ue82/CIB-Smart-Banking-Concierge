# MCP server: exchange-rate tool

A small MCP (Model Context Protocol) server that adds one tool to the CIB assistant:

| Tool | Purpose |
|---|---|
| `get_exchange_rate(from_currency, to_currency, amount)` | Indicative exchange rate and conversion for a short list of currencies |

The rate is a market reference rate from a free public API (updated once a day). It is **not** a CIB rate, and every reply says so.

## Files

- `fx_logic.py`: validation, cache, and conversion (standard library only, unit-tested).
- `cib_tools_server.py`: the MCP wrapper (needs the `mcp` package).

## Run

```bat
cd /d D:\cib-banking-rag-assistant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python mcp_server\cib_tools_server.py
```

Endpoint: `http://127.0.0.1:8765/mcp` (change with `CIB_MCP_HOST` and `CIB_MCP_PORT`).

## Connect from n8n

Add an **MCP Client Tool** node to the AI Agent's Tool port:

| Setting | Value |
|---|---|
| Endpoint | `http://localhost:8765/mcp` |
| Server Transport | HTTP Streamable |
| Authentication | None (local only) |
| Tools to Include | Selected, then `get_exchange_rate` |

If n8n runs in Docker, use `http://host.docker.internal:8765/mcp` and start the server with `CIB_MCP_HOST=0.0.0.0`. Do that only on a trusted machine, because it exposes the port to the local network.

Then use `prompts/system_message_v3.md` so the agent knows when to call the tool.

## Tests

```bat
python -m unittest discover -s tests -v
```

## Attribution

Rates By Exchange Rate API (https://www.exchangerate-api.com).
