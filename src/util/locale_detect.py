"""根据请求 IP / CDN 头 / 域名推断 UI 语言（zh | en）。"""

from __future__ import annotations

from fastapi import Request

_ZH_COUNTRIES = frozenset({"CN", "HK", "MO", "TW"})


def detect_ui_locale(request: Request) -> tuple[str, str]:
    for header in ("CF-IPCountry", "X-Geo-Country", "X-Country-Code"):
        code = (request.headers.get(header) or "").strip().upper()
        if code in _ZH_COUNTRIES:
            return "zh", header.lower()
        if len(code) == 2 and code.isalpha() and code not in ("XX", "T1"):
            return "en", header.lower()

    accept = (request.headers.get("accept-language") or "").lower()
    if accept.startswith("zh"):
        return "zh", "accept-language"

    host = (request.headers.get("host") or request.url.hostname or "").lower()
    if host.endswith(".vidau.info"):
        return "zh", "host"
    if host.endswith(".vidau.ai"):
        return "en", "host"

    return "en", "default"
