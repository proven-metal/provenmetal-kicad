"""Supabase login for a desktop process, via loopback PKCE.

Flow:
  1. Fetch { supabaseUrl, supabaseAnonKey } from the server config.
  2. Generate a PKCE verifier/challenge.
  3. Spin up a localhost HTTP server on a known port, open the browser to
     Supabase's OAuth authorize endpoint with redirect_to = the loopback URL.
  4. Supabase (after the provider login) redirects back to the loopback with
     ?code=..., which we exchange for an access + refresh token.
  5. Cache the tokens; refresh transparently until the refresh token expires.

The exact loopback URLs (see config.LOOPBACK_PORTS) must be on the Supabase Auth
redirect allow-list.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Dict, Optional

import requests

from .config import LOOPBACK_PORTS, Settings
from .api import ServerConfig


class AuthError(Exception):
    pass


class NotAuthenticated(AuthError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# Shown once we have credentials.
_DONE_HTML = (
    "<html><body style='font-family:sans-serif;padding:2rem'>"
    "<h2>ProvenMetal</h2><p>You're signed in. You can close this tab and return "
    "to KiCad.</p></body></html>"
)
# Supabase OAuth often returns the session in the URL fragment (#access_token=...),
# which the server never sees. This page runs in the browser, reads the fragment,
# and relays it to /store so the local server can capture it.
_RELAY_HTML = (
    "<html><body style='font-family:sans-serif;padding:2rem'>"
    "<p>Completing sign-in...</p><script>"
    "var h=window.location.hash?window.location.hash.substring(1):'';"
    "if(h){window.location.replace('/store?'+h);}"
    "else{document.body.innerHTML='<p>No sign-in data found. You can close this tab.</p>';}"
    "</script></body></html>"
)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def _respond(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        server = self.server  # type: ignore[attr-defined]

        def first(key):
            return (params.get(key) or [None])[0]

        # Tokens relayed from the URL fragment (implicit flow).
        if parsed.path == "/store":
            server.auth_result = {  # type: ignore[attr-defined]
                "code": None,
                "access_token": first("access_token"),
                "refresh_token": first("refresh_token"),
                "expires_at": first("expires_at"),
                "expires_in": first("expires_in"),
                "error": first("error"),
                "error_description": first("error_description"),
            }
            self._respond(_DONE_HTML)
            return

        # PKCE code or an error came back in the query.
        if first("code") or first("error"):
            server.auth_result = {  # type: ignore[attr-defined]
                "code": first("code"),
                "error": first("error"),
                "error_description": first("error_description"),
            }
            self._respond(_DONE_HTML)
            return

        # No query params: the session may be in the fragment - relay it via JS.
        self._respond(_RELAY_HTML)

    def log_message(self, *args):  # silence the default stderr logging
        return


def _bind_loopback() -> tuple[http.server.HTTPServer, int]:
    for port in LOOPBACK_PORTS:
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
            server.auth_result = None  # type: ignore[attr-defined]
            return server, port
        except OSError:
            continue
    raise AuthError(
        "Couldn't bind any loopback port for login "
        f"({', '.join(str(p) for p in LOOPBACK_PORTS)} all in use)."
    )


class Authenticator:
    def __init__(self, base_url: str, settings_dir: Path, provider: str = "google"):
        self.base_url = base_url.rstrip("/")
        self.settings_dir = settings_dir
        self.provider = provider

    # -- token cache ---------------------------------------------------------

    def _store_path(self) -> Path:
        digest = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:12]
        return self.settings_dir / f"auth-{digest}.json"

    def _load_tokens(self) -> Optional[Dict]:
        path = self._store_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_tokens(self, tokens: Dict) -> None:
        path = self._store_path()
        path.write_text(json.dumps(tokens), "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def logout(self) -> None:
        path = self._store_path()
        if path.exists():
            path.unlink()

    def is_logged_in(self) -> bool:
        return self._load_tokens() is not None

    # -- public entrypoint ---------------------------------------------------

    def get_access_token(self, config: ServerConfig, interactive: bool = True) -> str:
        tokens = self._load_tokens()
        now = time.time()

        if tokens and tokens.get("access_token") and float(tokens.get("expires_at", 0)) > now + 60:
            return tokens["access_token"]

        if tokens and tokens.get("refresh_token"):
            refreshed = self._refresh(config, tokens["refresh_token"])
            if refreshed:
                return refreshed["access_token"]

        if not interactive:
            raise NotAuthenticated("Not signed in. Run the login flow first.")

        logged_in = self._login(config)
        return logged_in["access_token"]

    # -- flows ---------------------------------------------------------------

    def _normalize_and_store(self, data: Dict) -> Dict:
        if not data.get("access_token"):
            raise AuthError("Auth server returned no access token.")
        expires_at = data.get("expires_at")
        if not expires_at:
            expires_at = time.time() + float(data.get("expires_in", 3600))
        tokens = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": float(expires_at),
        }
        self._save_tokens(tokens)
        return tokens

    def _refresh(self, config: ServerConfig, refresh_token: str) -> Optional[Dict]:
        url = f"{config.supabase_url}/auth/v1/token?grant_type=refresh_token"
        try:
            resp = requests.post(
                url,
                headers={"apikey": config.supabase_anon_key, "content-type": "application/json"},
                json={"refresh_token": refresh_token},
                timeout=30,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        try:
            return self._normalize_and_store(resp.json())
        except (ValueError, AuthError):
            return None

    def _exchange_code(self, config: ServerConfig, code: str, verifier: str) -> Dict:
        url = f"{config.supabase_url}/auth/v1/token?grant_type=pkce"
        resp = requests.post(
            url,
            headers={"apikey": config.supabase_anon_key, "content-type": "application/json"},
            json={"auth_code": code, "code_verifier": verifier},
            timeout=30,
        )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error_description") or resp.json().get("msg") or ""
            except ValueError:
                detail = resp.text[:200]
            raise AuthError(f"Token exchange failed ({resp.status_code}). {detail}".strip())
        return self._normalize_and_store(resp.json())

    def _login(self, config: ServerConfig, timeout: int = 300) -> Dict:
        verifier, challenge = _pkce_pair()
        server, port = _bind_loopback()
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        authorize = (
            f"{config.supabase_url}/auth/v1/authorize?"
            + urllib.parse.urlencode(
                {
                    "provider": self.provider,
                    "redirect_to": redirect_uri,
                    "code_challenge": challenge,
                    "code_challenge_method": "s256",
                }
            )
        )

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opened = webbrowser.open(authorize)
            if not opened:
                print(f"Open this URL to sign in:\n{authorize}")

            deadline = time.time() + timeout
            while time.time() < deadline:
                result = getattr(server, "auth_result", None)
                if result is not None:
                    break
                time.sleep(0.25)
            else:
                raise AuthError("Login timed out. Please try again.")
        finally:
            server.shutdown()
            server.server_close()

        if result.get("error"):
            raise AuthError(f"Login failed: {result.get('error_description') or result['error']}")

        # Implicit flow: tokens came back in the fragment and were relayed to /store.
        if result.get("access_token"):
            return self._normalize_and_store(
                {
                    "access_token": result.get("access_token"),
                    "refresh_token": result.get("refresh_token", ""),
                    "expires_at": result.get("expires_at"),
                    "expires_in": result.get("expires_in") or 3600,
                }
            )

        # PKCE flow: exchange the code for a session.
        code = result.get("code")
        if not code:
            raise AuthError("Login did not return credentials. Please try again.")
        return self._exchange_code(config, code, verifier)


def build_authenticator(settings: Settings, settings_dir: Path) -> Authenticator:
    return Authenticator(settings.base_url, settings_dir, provider=settings.oauth_provider)


# Silence "socket imported but unused" while keeping it available for callers that
# want to probe port availability in future.
_ = socket
