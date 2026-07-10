#!/usr/bin/env python3
"""Small, dependency-free client for the kitchen audio-button daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

SOCKET_PATH = "/run/kuche-pi-audio/control.sock"


async def send(request: dict[str, str]) -> dict[str, object]:
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    writer.write((json.dumps(request) + "\n").encode("utf-8"))
    await writer.drain()
    response = json.loads((await reader.readline()).decode("utf-8"))
    writer.close()
    await writer.wait_closed()
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the kitchen audio daemon")
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("stop")
    subcommands.add_parser("status")
    subcommands.add_parser("labels")
    for command in ("play", "remote-start", "remote-stop"):
        child = subcommands.add_parser(command)
        child.add_argument("source")
    arguments = parser.parse_args()
    request = {"action": arguments.action}
    if hasattr(arguments, "source"):
        request["source"] = arguments.source
    try:
        response = asyncio.run(send(request))
    except (ConnectionError, FileNotFoundError) as error:
        print(f"audioctl: daemon unavailable: {error}", file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps(response, indent=2, sort_keys=True))
    raise SystemExit(0 if response.get("ok") else 1)


if __name__ == "__main__":
    main()
