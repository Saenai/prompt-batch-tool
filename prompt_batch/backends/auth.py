from __future__ import annotations

import os
from typing import Any


def request_headers(auth: dict[str, Any], *, content_type: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if auth.get("type", "none") == "environment":
        variable = str(auth["environment_variable"])
        value = os.environ.get(variable)
        if not value:
            raise RuntimeError(f"Backend credential environment variable is not set: {variable}")
        header = str(auth.get("header", "Authorization"))
        prefix = str(auth.get("prefix", "Bearer "))
        headers[header] = prefix + value
    return headers
