"""Tiny JSON-over-HTTP helper built on the standard library.

The plugin runs inside a KiCad-managed virtualenv, and every extra dependency is
one more thing that can fail to install there. Using only `urllib` means the
plugin needs no third-party HTTP package at all.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from . import __version__

USER_AGENT = f"provenmetal-kicad/{__version__}"


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context with a working CA bundle.

    KiCad's bundled Python (macOS especially) often ships without a usable CA
    store, so plain HTTPS verification fails with "unable to get local issuer
    certificate". We look for a CA bundle in order: an explicit override, the
    bundle vendored alongside this file, certifi if installed, then the system
    default. Verification stays ON.
    """
    candidates = []
    override = os.environ.get("PROVENMETAL_CA_BUNDLE")
    if override:
        candidates.append(override)
    candidates.append(os.path.join(os.path.dirname(__file__), "cacert.pem"))
    try:
        import certifi  # type: ignore

        candidates.append(certifi.where())
    except Exception:
        pass
    for ca in candidates:
        if ca and os.path.exists(ca):
            try:
                return ssl.create_default_context(cafile=ca)
            except Exception:
                continue
    return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()


class HttpError(Exception):
    """Transport-level failure (could not reach the server)."""


def request_json(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, Any, str]:
    """Make a request and return (status_code, parsed_json_or_None, raw_text).

    Raises HttpError only when the server can't be reached; HTTP error statuses
    (4xx/5xx) are returned normally so callers can read the error body.
    """
    h = {"user-agent": USER_AGENT, "accept": "application/json"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("content-type", "application/json")

    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise HttpError(str(reason)) from e

    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = None
    return status, parsed, raw
