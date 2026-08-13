from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import join_endpoint
from .auth import request_headers


class BackendResponseError(RuntimeError):
    """Raised when an endpoint responds but violates the adapter contract."""


def _decode_object(raw_response: str, uri: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise BackendResponseError(f"Backend returned invalid JSON from {uri}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise BackendResponseError(f"Backend returned a non-object JSON response from {uri}")
    return payload


def _open(request: urllib.request.Request, timeout: float):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise


@dataclass(frozen=True)
class OpenAICompatibleBackend:
    config: dict[str, Any]
    base_url: str

    @property
    def models_uri(self) -> str:
        return join_endpoint(self.base_url, str(self.config["models_endpoint"]))

    @property
    def chat_uri(self) -> str:
        return join_endpoint(self.base_url, str(self.config["chat_endpoint"]))

    def _headers(self, content_type: bool = False) -> dict[str, str]:
        return request_headers(self.config.get("auth", {"type": "none"}), content_type=content_type)

    def get_models(self, timeout: float = 10) -> dict[str, Any]:
        request = urllib.request.Request(self.models_uri, headers=self._headers())
        with _open(request, timeout) as response:
            raw_response = response.read().decode("utf-8-sig")
        return _decode_object(raw_response, self.models_uri)

    def list_model_ids(self, timeout: float = 10) -> list[str]:
        payload = self.get_models(timeout)
        return sorted(
            {str(item["id"]) for item in payload.get("data", []) if item.get("id")},
            key=str.casefold,
        )

    def ready(self, timeout: float = 5) -> bool:
        self._headers()
        try:
            self.get_models(timeout)
            return True
        except Exception:
            return False

    def chat_completions(self, payload: dict[str, Any], timeout: int) -> tuple[str, dict[str, Any]]:
        raw_request = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.chat_uri,
            data=raw_request,
            method="POST",
            headers=self._headers(content_type=True),
        )
        with _open(request, timeout) as response:
            raw_response = response.read().decode("utf-8-sig")
        return raw_response, _decode_object(raw_response, self.chat_uri)
