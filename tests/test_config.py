from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prompt_batch.config import ConfigValidationError, load_app_config, validate_profile


def app_config_v1() -> dict:
    return {
        "schema_version": 1,
        "paths": {
            "engine": "batch_cli.py",
            "profiles": "profiles",
            "state": "state.json",
            "default_output_root": "output",
            "model_config": "models.yaml",
            "router_executable": "router.exe",
            "router_working_directory": ".",
            "runtime_executable": "server.exe",
        },
        "backend": {
            "type": "openai-chat-completions",
            "base_url": "http://127.0.0.1:8081/v1",
            "models_endpoint": "/models",
            "chat_endpoint": "/chat/completions",
            "request_timeout_seconds": 10,
            "readiness_timeout_seconds": 5,
            "request_body": {},
        },
        "router": {"arguments": [], "managed_process_names": []},
        "runtime": {"version_arguments": ["--version"]},
    }


class ConfigTests(unittest.TestCase):
    def test_v1_app_config_migrates_to_v2_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.json"
            path.write_text(json.dumps(app_config_v1()), encoding="utf-8")
            config = load_app_config(path)

        self.assertEqual(config["schema_version"], 2)
        self.assertEqual(config["backend"]["adapter"], "openai-chat-completions")
        self.assertNotIn("type", config["backend"])
        self.assertEqual(config["backend"]["auth"], {"type": "none"})

    def test_future_app_config_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.json"
            payload = app_config_v1()
            payload["schema_version"] = 99
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigValidationError, "schema_version 99"):
                load_app_config(path)

    def test_profile_default_mode_must_exist(self) -> None:
        profile = {
            "schema_version": 1,
            "id": "test",
            "default_mode": "missing",
            "modes": {"default": {"system_prompt_text": ""}},
        }
        with self.assertRaisesRegex(ConfigValidationError, "default_mode"):
            validate_profile(profile)

    def test_distributed_schema_documents_are_valid_json(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        for name in ("app-config.schema.json", "profile.schema.json"):
            payload = json.loads((schema_root / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
