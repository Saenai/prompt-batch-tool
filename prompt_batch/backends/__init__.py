from __future__ import annotations

from typing import Any, Protocol

from .openai_compatible import BackendResponseError, OpenAICompatibleBackend


class ChatBackend(Protocol):
    @property
    def models_uri(self) -> str: ...

    def list_model_ids(self, timeout: float = 10) -> list[str]: ...

    def ready(self, timeout: float = 5) -> bool: ...

    def chat_completions(self, payload: dict[str, Any], timeout: int) -> tuple[str, dict[str, Any]]: ...


def backend_identity(config: dict[str, Any], base_url: str) -> dict[str, Any]:
    auth = config.get("auth", {"type": "none"})
    safe_auth = {
        key: auth[key]
        for key in ("type", "environment_variable", "header", "prefix")
        if key in auth
    }
    return {
        "adapter": config.get("adapter"),
        "base_url": base_url,
        "models_endpoint": config.get("models_endpoint"),
        "chat_endpoint": config.get("chat_endpoint"),
        "request_body": config.get("request_body", {}),
        "auth": safe_auth,
    }


def create_backend(config: dict[str, Any], base_url: str) -> ChatBackend:
    adapter = str(config.get("adapter", ""))
    if adapter == "openai-chat-completions":
        return OpenAICompatibleBackend(config, base_url)
    raise ValueError(f"Unsupported backend adapter: {adapter}")


__all__ = [
    "BackendResponseError", "ChatBackend", "OpenAICompatibleBackend",
    "backend_identity", "create_backend",
]
