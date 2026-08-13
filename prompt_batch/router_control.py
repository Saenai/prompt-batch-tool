from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .backends.auth import request_headers
from .config import join_endpoint


class RouterControlError(RuntimeError):
    """Raised when a llama-swap control endpoint cannot complete."""


@dataclass(frozen=True, slots=True)
class RouterControlResult:
    uri: str
    status_code: int
    response_text: str


def unload_all_models(
    router_config: dict[str, Any],
    auth_config: dict[str, Any],
) -> RouterControlResult:
    uri = join_endpoint(
        str(router_config["control_base_url"]),
        str(router_config["unload_all_endpoint"]),
    )
    request = urllib.request.Request(
        uri,
        data=b"",
        method="POST",
        headers=request_headers(auth_config, content_type=True),
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=float(router_config["control_timeout_seconds"]),
        ) as response:
            body = response.read().decode("utf-8-sig", errors="replace").strip()
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8-sig", errors="replace").strip()
        finally:
            exc.close()
        detail = body or str(exc.reason) or f"HTTP {exc.code}"
        raise RouterControlError(f"llama-swap unload failed ({exc.code}): {detail}") from exc
    except (OSError, TimeoutError) as exc:
        raise RouterControlError(f"Cannot reach llama-swap control API at {uri}: {exc}") from exc
    if not 200 <= status < 300:
        raise RouterControlError(f"llama-swap unload returned HTTP {status}: {body}")
    return RouterControlResult(uri=uri, status_code=status, response_text=body)
