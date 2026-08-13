from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest.mock import patch

from prompt_batch.router_control import RouterControlError, unload_all_models


class FakeResponse:
    status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return b'{"unloaded":true}'


def router_config() -> dict:
    return {
        "control_base_url": "http://127.0.0.1:8081",
        "unload_all_endpoint": "/api/models/unload",
        "control_timeout_seconds": 30,
    }


class RouterControlTests(unittest.TestCase):
    def test_posts_to_configured_unload_endpoint(self) -> None:
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = unload_all_models(router_config(), {"type": "none"})

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8081/api/models/unload")
        self.assertEqual(request.method, "POST")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30.0)
        self.assertEqual(result.status_code, 200)

    def test_reuses_environment_auth_without_persisting_secret(self) -> None:
        auth = {"type": "environment", "environment_variable": "ROUTER_TEST_KEY", "prefix": "Bearer "}
        with patch.dict(os.environ, {"ROUTER_TEST_KEY": "secret-value"}), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ) as urlopen:
            unload_all_models(router_config(), auth)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer secret-value")

    def test_http_error_includes_body_and_closes_response(self) -> None:
        body = io.BytesIO(b"cannot unload")
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8081/api/models/unload", 500, "failed", {}, body
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RouterControlError, "cannot unload"):
                unload_all_models(router_config(), {"type": "none"})
        self.assertTrue(body.closed)


if __name__ == "__main__":
    unittest.main()
