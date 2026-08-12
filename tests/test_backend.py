from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from prompt_batch.backend import create_backend


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


if __name__ == "__main__":
    unittest.main()
