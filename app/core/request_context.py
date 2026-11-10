"""Resolve: per-request context (the caller's IP address), set by middleware in
main.py so services can record it in the access log without knowing about HTTP."""
from contextvars import ContextVar

_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def set_client_ip(ip: str | None) -> None:
    _client_ip.set(ip)


def get_client_ip() -> str | None:
    return _client_ip.get()