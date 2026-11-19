"""Authenticated MCP tools for Copilot v2; bearer context is never exposed to the model."""
import os
from pathlib import Path
import sys

import requests
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from copilot.math_tool import calculate
from copilot.security import verify
from copilot.store import Store

mcp = FastMCP("research-copilot-v2")


def identity():
    return verify(os.environ.get("COPILOT_PRINCIPAL_TOKEN", ""))


@mcp.tool()
def knowledge_search(query: str, source_id: str | None = None) -> dict:
    """Search authorized documents; source_id narrows the source. No identity arguments."""
    identity()
    headers = {"Authorization": "Bearer " + os.environ["COPILOT_PRINCIPAL_TOKEN"]}
    for attempt in range(2):
        try:
            response = requests.post(os.getenv("RAG_API_URL", "http://127.0.0.1:8011") + "/search",
                                     json={"query": query, "source_id": source_id}, headers=headers, timeout=(5, 40))
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                return {"status": "error", "evidence": [], "message": "RAG unavailable; no source-backed conclusion can be made."}
    raise RuntimeError("Unreachable")


@mcp.tool()
def calculator(expression: str) -> dict:
    """Evaluate bounded arithmetic without executing code."""
    identity()
    return calculate(expression)


@mcp.tool()
def save_report() -> dict:
    """Commit only the exact approved draft bound to this server's trusted run context."""
    principal = identity()
    return Store().save(os.environ["COPILOT_RUN_ID"], principal)


if __name__ == "__main__":
    mcp.run(transport="stdio")
