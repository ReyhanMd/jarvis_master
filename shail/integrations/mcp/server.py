"""Simple entrypoint to run the SHAIL MCP server."""

import argparse
import logging
from typing import Optional

from shail.integrations.mcp.provider import get_provider
from shail.integrations.register_all import register_all_tools

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SHAIL MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "http", "sse"],
        help="Transport for MCP server (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP/SSE transports (ignored for stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8005,
        help="Port for HTTP/SSE transports (ignored for stdio)",
    )
    return parser.parse_args()


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8005) -> None:
    """Start the MCP server using the global provider."""
    provider = get_provider()
    # Register available tools before starting the server
    register_all_tools(provider)
    try:
        if transport == "stdio":
            provider.run(transport="stdio")
        else:
            provider.run(transport=transport, host=host, port=port)
    except RuntimeError as exc:
        logger.error(str(exc))
        raise


def main(args: Optional[argparse.Namespace] = None) -> None:
    parsed = args or parse_args()
    logging.basicConfig(level=logging.INFO)
    run_server(
        transport=parsed.transport,
        host=parsed.host,
        port=parsed.port,
    )


if __name__ == "__main__":
    main()
