"""Thin async httpx client for forwarding to api.anthropic.com.

Kept isolated so tests can substitute a MockTransport.

In strict-mode, the OS hosts file redirects api.anthropic.com → 127.0.0.1.
To break that loop we resolve the real IP via a direct DNS query to 8.8.8.8,
bypassing the local hosts file, then route all TCP connections to that IP.
The TLS handshake still uses "api.anthropic.com" as the SNI hostname so cert
verification and certificate pinning work correctly.
"""
from __future__ import annotations

import socket
import struct
from typing import Any

import httpcore
import httpx


# ---------------------------------------------------------------------------
# DNS bypass helpers
# ---------------------------------------------------------------------------

def _resolve_real_ip(hostname: str, dns_server: str = "8.8.8.8") -> str | None:
    """Return the first A-record for *hostname* from *dns_server*, or None.

    Sends a raw UDP DNS query directly to *dns_server*, skipping the OS
    resolver (and therefore /etc/hosts / the Windows hosts file).
    """
    try:
        qid = 0x1A2B
        header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
        name = (
            b"".join(bytes([len(p)]) + p.encode() for p in hostname.split("."))
            + b"\x00"
        )
        question = name + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        try:
            sock.sendto(header + question, (dns_server, 53))
            response = sock.recv(4096)
        finally:
            sock.close()

        # Skip fixed 12-byte header + question section
        pos = 12
        while pos < len(response):
            b = response[pos]
            if b == 0:
                pos += 1
                break
            if b >= 0xC0:  # compressed DNS name pointer
                pos += 2
                break
            pos += b + 1
        pos += 4  # QTYPE (2) + QCLASS (2)

        answer_count = struct.unpack_from(">H", response, 6)[0]
        for _ in range(answer_count):
            if pos >= len(response):
                break
            b = response[pos]
            if b >= 0xC0:
                pos += 2
            else:
                while pos < len(response) and response[pos] != 0:
                    pos += response[pos] + 1
                pos += 1
            if pos + 10 > len(response):
                break
            rtype, _rclass, _ttl, rdlen = struct.unpack_from(">HHIH", response, pos)
            pos += 10
            if rtype == 1 and rdlen == 4:  # A record
                return ".".join(str(b) for b in response[pos : pos + 4])
            pos += rdlen
    except Exception:
        pass
    return None


def _make_default_backend() -> httpcore.AsyncNetworkBackend:
    """Return httpcore's default async network backend."""
    try:
        from httpcore._backends.anyio import AnyIOBackend  # type: ignore[import]
        return AnyIOBackend()
    except Exception:
        pass
    try:
        from httpcore._backends.asyncio import AsyncIOBackend  # type: ignore[import]
        return AsyncIOBackend()
    except Exception:
        pass
    raise RuntimeError("No supported httpcore async backend found")


class _BypassHostsBackend(httpcore.AsyncNetworkBackend):
    """Routes TCP connections to a fixed IP, bypassing the OS hosts file.

    httpcore still passes the original hostname to start_tls() so TLS SNI
    and certificate verification continue to use "api.anthropic.com".
    """

    def __init__(self, real_ip: str) -> None:
        self._real_ip = real_ip
        self._inner = _make_default_backend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: list[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._inner.connect_tcp(
            self._real_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: list[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._inner.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


# ---------------------------------------------------------------------------
# Public upstream client
# ---------------------------------------------------------------------------

class AnthropicUpstream:
    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 600.0,
    ) -> None:
        if transport is None:
            # Extract the hostname from base_url and resolve its real IP,
            # bypassing the local hosts file (strict-mode redirects it to 127.0.0.1).
            target_host = base_url.split("//", 1)[-1].split("/")[0].split(":")[0]
            real_ip = _resolve_real_ip(target_host)
            if real_ip is not None:
                transport = httpx.AsyncHTTPTransport(
                    network_backend=_BypassHostsBackend(real_ip)
                )

        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
        )

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        req = self._client.build_request("POST", path, json=json, headers=headers)
        return await self._client.send(req, stream=True)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: str | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = path + (f"?{params}" if params else "")
        req = self._client.build_request(method, url, content=content, headers=headers)
        return await self._client.send(req, stream=True)

    async def aclose(self) -> None:
        await self._client.aclose()
