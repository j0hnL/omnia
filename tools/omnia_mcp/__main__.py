"""
Entry point for running the Omnia MCP server.

Usage:
    python -m omnia_mcp                     # stdio transport (default)
    python -m omnia_mcp --sse --port 8080   # SSE transport for HTTP clients
    OMNIA_ROOT=/path/to/omnia python -m omnia_mcp
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Omnia MCP Configuration Assistant Server"
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Use SSE (Server-Sent Events) transport instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for SSE transport (default: 8080)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if args.sse:
        _run_sse(args.host, args.port)
    else:
        _run_stdio()


def _run_stdio():
    """Run the server over stdin/stdout (default MCP transport)."""
    from omnia_mcp.server import main as server_main
    asyncio.run(server_main())


def _run_sse(host: str, port: int):
    """Run the server over SSE for HTTP-based MCP clients."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn
    except ImportError:
        print(
            "SSE transport requires additional dependencies: "
            "pip install 'mcp[sse]' starlette uvicorn",
            file=sys.stderr,
        )
        sys.exit(1)

    from omnia_mcp.server import create_server

    server, registry = create_server()
    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
        ],
    )

    logging.getLogger("omnia_mcp").info(
        "Starting Omnia MCP server (SSE) on %s:%d — root=%s",
        host, port, registry.omnia_root,
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
