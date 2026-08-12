from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import join_endpoint


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
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = "application/json; charset=utf-8"
        auth = self.config.get("auth", {"type": "none"})
        if auth.get("type", "none") == "environment":
            variable = str(auth["environment_variable"])
            value = os.environ.get(variable)
            if not value:
                raise RuntimeError(f"Backend credential environment variable is not set: {variable}")
            header = str(auth.get("header", "Authorization"))
            prefix = str(auth.get("prefix", "Bearer "))
            headers[header] = prefix + value
        return headers

    def get_models(self, timeout: float = 10) -> dict[str, Any]:
        request = urllib.request.Request(self.models_uri, headers=self._headers())
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8-sig"))

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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8-sig")
        return raw_response, json.loads(raw_response)
