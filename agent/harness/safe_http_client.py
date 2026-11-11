"""Safe HTTP client for Agent web tools.

This module is the only allowed network path for web MCP tools. It performs
scheme/domain/IP checks before connecting, validates every redirect, connects to
the resolved IP directly, and sends the original host as Host/SNI.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit


class SafeHttpError(ValueError):
    """Raised when a URL or response violates web tool guardrails."""


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    ip: str


@dataclass(frozen=True)
class SafeHttpResponse:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


Resolver = Callable[..., list]


def _normalize_domains(domains: Iterable[str] | None) -> list[str]:
    result = []
    for domain in domains or []:
        value = (domain or "").strip().lower().lstrip(".")
        if value:
            result.append(value)
    return result


def is_safe_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _domain_matches(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def _check_domain_policy(host: str, allowed_domains: Iterable[str] | None,
                         blocked_domains: Iterable[str] | None) -> None:
    blocked = _normalize_domains(blocked_domains)
    if any(_domain_matches(host, item) for item in blocked):
        raise SafeHttpError(f"blocked domain: {host}")

    allowed = _normalize_domains(allowed_domains)
    if allowed and not any(_domain_matches(host, item) for item in allowed):
        raise SafeHttpError(f"domain is not allowed: {host}")


def safe_resolve(url: str, resolver: Resolver | None = None,
                 allowed_domains: Iterable[str] | None = None,
                 blocked_domains: Iterable[str] | None = None) -> ResolvedTarget:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise SafeHttpError("only http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise SafeHttpError("URL credentials are not allowed")
    if not parsed.hostname:
        raise SafeHttpError("URL host is required")

    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _check_domain_policy(host, allowed_domains, blocked_domains)

    resolve = resolver or socket.getaddrinfo
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SafeHttpError(f"DNS resolution failed: {host}") from exc

    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise SafeHttpError(f"DNS returned no addresses: {host}")
    unsafe = [ip for ip in ips if not is_safe_ip(ip)]
    if unsafe:
        raise SafeHttpError(f"unsafe resolved IP for {host}: {unsafe[0]}")

    return ResolvedTarget(url=url, scheme=parsed.scheme, host=host, port=port, ip=ips[0])


def _request_target(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _host_header(target: ResolvedTarget) -> str:
    if (target.scheme == "https" and target.port == 443) or (target.scheme == "http" and target.port == 80):
        return target.host
    return f"{target.host}:{target.port}"


async def _read_until_headers(reader: asyncio.StreamReader, timeout: int) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            raise SafeHttpError("response headers are too large")
    return data


async def _read_body(reader: asyncio.StreamReader, initial: bytes, max_bytes: int, timeout: int) -> bytes:
    body = initial
    if len(body) > max_bytes:
        raise SafeHttpError("response body is too large")
    while len(body) <= max_bytes:
        chunk = await asyncio.wait_for(reader.read(8192), timeout=timeout)
        if not chunk:
            return body
        body += chunk
    raise SafeHttpError("response body is too large")


def _parse_headers(raw: bytes) -> tuple[int, dict[str, str], bytes]:
    header_bytes, _, body = raw.partition(b"\r\n\r\n")
    lines = header_bytes.decode("iso-8859-1", errors="replace").split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        raise SafeHttpError("invalid HTTP response")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise SafeHttpError("invalid HTTP status line")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return int(parts[1]), headers, body


async def _safe_connect_get(target: ResolvedTarget, max_bytes: int, timeout: int) -> tuple[int, dict[str, str], bytes]:
    ssl_context = None
    server_hostname = None
    if target.scheme == "https":
        ssl_context = ssl.create_default_context()
        server_hostname = target.host

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host=target.ip,
            port=target.port,
            ssl=ssl_context,
            server_hostname=server_hostname,
        ),
        timeout=timeout,
    )
    try:
        request = (
            f"GET {_request_target(target.url)} HTTP/1.1\r\n"
            f"Host: {_host_header(target)}\r\n"
            "User-Agent: toutiao-agent-web-mcp/0.1\r\n"
            "Accept: text/html,text/plain,application/json;q=0.8,*/*;q=0.1\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        raw = await _read_until_headers(reader, timeout)
        status, headers, initial_body = _parse_headers(raw)
        body = await _read_body(reader, initial_body, max_bytes, timeout)
        return status, headers, body
    finally:
        writer.close()
        await writer.wait_closed()


async def safe_fetch(url: str, max_bytes: int, timeout: int, max_redirects: int,
                     allowed_domains: Iterable[str] | None = None,
                     blocked_domains: Iterable[str] | None = None,
                     resolver: Resolver | None = None) -> SafeHttpResponse:
    current = url
    redirects = 0
    while True:
        target = safe_resolve(
            current,
            resolver=resolver,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
        status, headers, body = await _safe_connect_get(target, max_bytes=max_bytes, timeout=timeout)
        location = headers.get("location")
        if status in {301, 302, 303, 307, 308} and location:
            redirects += 1
            if redirects > max_redirects:
                raise SafeHttpError("too many redirects")
            current = urljoin(current, location)
            continue
        return SafeHttpResponse(url=url, final_url=current, status_code=status, headers=headers, body=body)
