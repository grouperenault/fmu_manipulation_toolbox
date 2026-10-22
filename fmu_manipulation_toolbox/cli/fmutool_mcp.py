"""Standalone MCP server for the FMU Manipulation Toolbox (``fmutool-mcp``).

Until now the assistant only existed while the Container Builder GUI was
running, which ruled out every MCP client that expects to *launch* its server
(Claude Desktop, Cline, a plain ``mcp.json`` with a ``command``). This entry
point serves the very same tools over **stdio** — the transport those clients
speak — on top of the headless bridge, so no display and no Qt are involved.

The HTTP transport is kept available for clients that prefer to attach to an
already-running server.
"""

import argparse
import logging
import secrets
import sys
from pathlib import Path

from .utils import close_logger, make_wide
from ..assistant import DEFAULT_HOST, McpUnavailableError, build_server, resolve_port
from ..assistant.auth import (
    GENERATE, TOKEN_ENV_VAR, build_auth_middleware, resolve_token,
)
from ..assistant.headless import DEFAULT_CONTAINER_NAME, HeadlessAssemblyBridge
from ..assistant.paths import PathPolicy, PathValidationError
from ..version import __version__ as version


def _resolve_cli_token(requested: str | None) -> str | None:
    """Resolve the bearer token from the command line, then the environment.

    ``--token generate`` is handled the same way as the environment value, so
    both entry points agree on what "generate" means.
    """
    if requested is None:
        return resolve_token()
    if requested == GENERATE:
        return secrets.token_urlsafe(32)
    if len(requested) < 16:
        raise ValueError(
            f"--token must be at least 16 characters long (or '{GENERATE}' to "
            f"let the server pick one)."
        )
    return requested


def _setup_logger(debug: bool) -> logging.Logger:
    """Send the toolbox logs to **stderr**.

    This is not a detail: with the stdio transport, stdout *is* the JSON-RPC
    channel. A single log line written there corrupts the stream and the
    client disconnects, so the usual ``cli.utils.setup_logger`` (which logs to
    stdout) cannot be used here.
    """
    logger = logging.getLogger("fmu_manipulation_toolbox")
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    return logger


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="fmutool-mcp",
        description="Expose FMU Container assembly to an AI agent through an MCP server.",
        formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
        add_help=False,
        epilog="see: https://grouperenault.github.io/fmu_manipulation_toolbox/"
               "user-guide/fmucontainer/ai-assistant/")

    parser.add_argument("-h", "-help", "--help", action="help")

    parser.add_argument("-transport", "--transport", action="store", dest="transport",
                        choices=("stdio", "http"), default="stdio",
                        help="Transport to serve. 'stdio' is what a client that "
                             "launches the server expects; 'http' lets clients "
                             "attach to an already-running server.")

    parser.add_argument("-host", "--host", action="store", dest="host", default=DEFAULT_HOST,
                        help="Interface to bind to (http transport only).")

    parser.add_argument("-port", "--port", action="store", dest="port", type=int, default=None,
                        help="TCP port to listen on (http transport only). Defaults to "
                             "FMUCONTAINER_MCP_PORT, or 8765.")

    parser.add_argument("-root", "--root", action="store", dest="root", default=None,
                        help="Confine the assistant to this directory. Recommended when "
                             "the server is driven by an agent. Defaults to "
                             "FMUCONTAINER_MCP_ROOT, or no restriction.")

    parser.add_argument("-name", "--name", action="store", dest="name",
                        default=DEFAULT_CONTAINER_NAME,
                        help="Name of the container being assembled.")

    parser.add_argument("-token", "--token", action="store", dest="token", default=None,
                        metavar="TOKEN|generate",
                        help="Require this bearer token from HTTP clients (http transport "
                             "only). 'generate' makes one up and prints it. Without it, any "
                             "local process can drive the server. Defaults to "
                             "FMUCONTAINER_MCP_TOKEN.")

    parser.add_argument("-debug", "--debug", action="store_true", dest="debug",
                        help="Add lot of useful log during the process.")

    return parser.parse_args(argv)


def fmutool_mcp(argv=None) -> int:
    """Entry point of the ``fmutool-mcp`` console script."""
    options = _parse_args(argv)
    logger = _setup_logger(options.debug)
    logger.info(f"FMU Manipulation Toolbox MCP server version {version}")

    try:
        policy = (PathPolicy(Path(options.root)) if options.root
                  else PathPolicy.from_environment())
        bridge = HeadlessAssemblyBridge(options.name)
        mcp = build_server(bridge, policy=policy)

        if options.transport == "stdio":
            logger.info("Serving MCP over stdio.")
            mcp.run(transport="stdio")
        else:
            port = options.port if options.port is not None else resolve_port()
            # The loopback interface keeps remote machines out, but not the
            # other processes of this machine: see `assistant.auth`.
            token = _resolve_cli_token(options.token)
            if token:
                logger.info(f"Bearer token required: {token}")
            else:
                logger.warning(
                    f"No authentication: any local process can drive this server "
                    f"and read/write files through it. Use --token generate (or "
                    f"{TOKEN_ENV_VAR}) to require one."
                )
            logger.info(f"Serving MCP over http://{options.host}:{port}/mcp")
            middleware = None
            if token:
                # Starlette's wrapper, which is what FastMCP expects here.
                from starlette.middleware import Middleware

                middleware = [Middleware(build_auth_middleware(token))]
            mcp.run(transport="http", host=options.host, port=port, path="/mcp",
                    middleware=middleware)
    except McpUnavailableError as exc:
        logger.critical(str(exc))
        return 1
    except (PathValidationError, ValueError) as exc:
        logger.critical(str(exc))
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    except OSError as exc:
        logger.critical(f"Cannot serve: {exc}")
        return 1
    finally:
        close_logger(logger)

    return 0


def main():  # pragma: no cover - console script shim
    sys.exit(fmutool_mcp())


if __name__ == "__main__":  # pragma: no cover
    main()

