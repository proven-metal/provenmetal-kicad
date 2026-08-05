"""HTTP client for the ProvenMetal Central /api/kicad/* surface (stdlib only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import __version__
from ._http import request_json, HttpError


class ApiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class ServerConfig:
    supabase_url: str
    supabase_anon_key: str
    app_url: str
    api_version: int


class ProvenMetalClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- public bootstrap ----------------------------------------------------

    def get_config(self) -> ServerConfig:
        url = f"{self.base_url}/api/kicad/config"
        try:
            status, data, _ = request_json("GET", url, timeout=self.timeout)
        except HttpError as e:
            raise ApiError(f"Couldn't reach ProvenMetal Central at {self.base_url}: {e}") from e
        if status != 200 or not isinstance(data, dict):
            raise ApiError(f"Config request failed ({status}).", status=status)
        if not data.get("supabaseUrl") or not data.get("supabaseAnonKey"):
            raise ApiError("Server did not return Supabase configuration.")
        return ServerConfig(
            supabase_url=data["supabaseUrl"].rstrip("/"),
            supabase_anon_key=data["supabaseAnonKey"],
            app_url=(data.get("appUrl") or self.base_url).rstrip("/"),
            api_version=int(data.get("apiVersion") or 1),
        )

    # -- authed endpoints ----------------------------------------------------

    def push_bom(
        self,
        token: str,
        *,
        name: str,
        board_count: int,
        lines: List[Dict[str, Any]],
        project_id: Optional[str] = None,
        client_version: Optional[str] = None,
        timeout: int = 130,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/kicad/bom"
        body: Dict[str, Any] = {
            "name": name,
            "boardCount": board_count,
            "lines": lines,
            "clientVersion": client_version or __version__,
        }
        if project_id:
            body["projectId"] = project_id
        return self._authed_json("POST", url, token, json_body=body, timeout=timeout)

    def get_latest(self, token: str, project_id: str, timeout: int = 30) -> Dict[str, Any]:
        url = f"{self.base_url}/api/kicad/bom/{project_id}"
        return self._authed_json("GET", url, token, timeout=timeout)

    # -- internals -----------------------------------------------------------

    def _authed_json(
        self,
        method: str,
        url: str,
        token: str,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        headers = {"authorization": f"Bearer {token}"}
        try:
            status, data, _ = request_json(method, url, headers=headers, body=json_body, timeout=timeout)
        except HttpError as e:
            raise ApiError(f"Request to {url} failed: {e}") from e

        if not isinstance(data, dict):
            data = {}
        if status >= 400 or data.get("ok") is False:
            message = data.get("error") or f"Request failed ({status})."
            raise ApiError(message, status=status, code=data.get("code"))
        return data
