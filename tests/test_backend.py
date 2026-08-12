from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from prompt_batch.backends import BackendResponseError, create_backend


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def backend_config() -> dict:
    return {
        "adapter": "openai-chat-completions",
        "models_endpoint": "/models",
        "chat_endpoint": "/chat/completions",
        "auth": {"type": "none"},
    }


class BackendTests(unittest.TestCase):
    def test_missing_environment_credential_is_not_reported_as_endpoint_failure(self) -> None:
        config = {
            "adapter": "openai-chat-completions",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "auth": {
                "type": "environment",
                "environment_variable": "PROMPT_BATCH_MISSING_TEST_KEY",
            },
        }
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMPT_BATCH_MISSING_TEST_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "PROMPT_BATCH_MISSING_TEST_KEY"):
                create_backend(config, "http://127.0.0.1:1/v1").ready()

    def test_models_are_sorted_deduplicated_and_missing_ids_are_ignored(self) -> None:
        response = FakeResponse('{"data":[{"id":"zeta"},{"id":"Alpha"},{"id":"zeta"},{}]}')
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            models = create_backend(backend_config(), "http://example.test/v1").list_model_ids(2.5)

        self.assertEqual(models, ["Alpha", "zeta"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 2.5)

    def test_invalid_json_has_endpoint_context(self) -> None:
        backend = create_backend(backend_config(), "http://example.test/v1")
        with patch("urllib.request.urlopen", return_value=FakeResponse("not-json")):
            with self.assertRaisesRegex(BackendResponseError, r"invalid JSON.*chat/completions"):
                backend.chat_completions({"model": "test", "messages": []}, 7)

    def test_non_object_json_is_rejected(self) -> None:
        backend = create_backend(backend_config(), "http://example.test/v1")
        with patch("urllib.request.urlopen", return_value=FakeResponse("[]")):
            with self.assertRaisesRegex(BackendResponseError, "non-object JSON"):
                backend.get_models()

    def test_readiness_converts_transport_timeout_to_false(self) -> None:
        backend = create_backend(backend_config(), "http://example.test/v1")
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            self.assertFalse(backend.ready(timeout=0.1))

    def test_chat_transport_timeout_is_not_swallowed(self) -> None:
        backend = create_backend(backend_config(), "http://example.test/v1")
        urlopen = MagicMock(side_effect=TimeoutError("timed out"))
        with patch("urllib.request.urlopen", urlopen):
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                backend.chat_completions({"model": "test", "messages": []}, 11)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 11)

    def test_http_error_response_is_closed(self) -> None:
        body = io.BytesIO(b"service unavailable")
        error = urllib.error.HTTPError(
            "http://example.test/v1/models", 503, "unavailable", {}, body
        )
        backend = create_backend(backend_config(), "http://example.test/v1")
        with patch("urllib.request.urlopen", side_effect=error):
            self.assertFalse(backend.ready())
        self.assertTrue(body.closed)


if __name__ == "__main__":
    unittest.main()
