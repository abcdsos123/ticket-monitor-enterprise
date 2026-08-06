from __future__ import annotations

from urllib.parse import urlparse


def detect_provider(url: str, configured: str = "auto") -> str:
    configured = (configured or "auto").strip().lower()
    if configured not in {"", "auto"}:
        return configured
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    if host in {"kktix.com", "kktix.cc"} or host.endswith(".kktix.com") or host.endswith(".kktix.cc"):
        return "kktix"
    if host == "tixcraft.com" or host.endswith(".tixcraft.com"):
        return "tixcraft"
    return "unknown"
