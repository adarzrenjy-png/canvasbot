from __future__ import annotations

import argparse
import ipaddress

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .config import settings
from .mcp_tools import get_week_plan, list_assignments, list_courses, planner_status, recent_changes, request_canvas_scan


server = MCPServer(
    name="adaptive-academic-os",
    title="Adaptive Academic OS",
    version="0.2.0",
    description="A privacy-preserving interface to the local academic planner.",
)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


server.tool(description="List active courses known to the planner.", annotations=READ_ONLY, structured_output=True)(list_courses)
server.tool(description="List upcoming assignments without exposing credentials or raw private page data.", annotations=READ_ONLY, structured_output=True)(list_assignments)
server.tool(description="Return the deterministic study plan for the next several days.", annotations=READ_ONLY, structured_output=True)(get_week_plan)
server.tool(description="Return planner, Canvas session, and background-job health.", annotations=READ_ONLY, structured_output=True)(planner_status)
server.tool(description="Return recent normalized academic changes.", annotations=READ_ONLY, structured_output=True)(recent_changes)
server.tool(description="Queue a Canvas browser scan. Requires the local write token configured by the user.", annotations=WRITE, structured_output=True)(request_canvas_scan)


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive Academic OS MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if args.transport == "streamable-http":
        if not _loopback(args.host) and not settings.mcp_remote_enabled:
            parser.error("Remote MCP is disabled. Bind to localhost or explicitly configure authenticated remote access.")
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )
        return

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
