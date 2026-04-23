#!/usr/bin/env python3
"""IPv6 [::1]:PORT → IPv4 127.0.0.1:PORT loopback proxy.

Workaround for cloudflared 2026.3.x: its WebSocket proxy path resolves
``localhost`` to IPv6 ``[::1]`` first and doesn't fall back to IPv4, while
our uvicorn server only binds the IPv4 all-interfaces socket. HTTP proxy
path happy-eyeballs to IPv4 fine, so only WS upgrades break.

This listens on ``[::1]:<PORT>`` and proxies raw bytes to
``127.0.0.1:<PORT>``. Bytes-level passthrough preserves the Upgrade header
and all X-Forwarded-* headers that cloudflared already injected.
"""
import argparse
import asyncio
import logging
import signal
import sys

logger = logging.getLogger("ipv6-loopback-proxy")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            target_host, target_port
        )
    except OSError as exc:
        logger.warning("upstream connect failed: %s", exc)
        client_writer.close()
        await client_writer.wait_closed()
        return
    await asyncio.gather(
        _pipe(client_reader, upstream_writer),
        _pipe(upstream_reader, client_writer),
        return_exceptions=True,
    )


async def main(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    async def handle(r, w):
        await _handle_client(r, w, target_host, target_port)

    server = await asyncio.start_server(handle, host=listen_host, port=listen_port, family=0)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("listening on %s → %s:%d", addrs, target_host, target_port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async with server:
        await stop.wait()
        logger.info("shutting down")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="::1")
    parser.add_argument("--listen-port", type=int, default=8767)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=8767)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(main(args.listen_host, args.listen_port, args.target_host, args.target_port))
    except KeyboardInterrupt:
        pass
