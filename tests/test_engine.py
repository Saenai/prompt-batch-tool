from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prompt_batch import BatchOptions, run_batch, validate_batch


class MockApiHandler(BaseHTTPRequestHandler):
    models = ["model-a", "model-b"]
    requests: list[dict] = []

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            self._send({"data": [{"id": model_id} for model_id in self.models]})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        self.requests.append(request)
        user_content = request["messages"][-1]["content"]
        marker = '"TOKEN"' if '"TOKEN"' in user_content else "plain"
        content = f"result: {marker}\nmodel={request['model']} seed={request['seed']}"
        self._send({
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "timings": {"predicted_ms": 250, "predicted_per_second": 20.0},
        })


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockApiHandler)
        MockApiHandler.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

        (self.root / "profiles").mkdir()
        (self.root / "output").mkdir()
        self.config_path = self.root / "app.json"
        self.profile_path = self.root / "profiles" / "test.json"
        self.manifest_path = self.root / "inputs.json"
        self.config_path.write_text(json.dumps({
            "paths": {
                "default_output_root": "output",
                "router_executable": "missing-router.exe",
                "router_working_directory": ".",
                "runtime_executable": "missing-runtime.exe",
                "model_config": "missing-model-config.yaml",
            },
            "backend": {
                "type": "openai-chat-completions",
                "base_url": self.base_url,
                "models_endpoint": "/models",
                "chat_endpoint": "/chat/completions",
                "request_timeout_seconds": 5,
                "readiness_timeout_seconds": 1,
                "request_body": {"temperature": 0.4},
            },
            "router": {"arguments": [], "managed_process_names": []},
            "runtime": {"version_arguments": ["--version"]},
        }), encoding="utf-8")
        self.profile_path.write_text(json.dumps({
            "id": "test",
            "display_name": "Test Profile",
            "default_mode": "alpha",
            "allow_auto_mode": True,
            "mode_detection": {"type": "first_nonempty_line", "case_sensitive": False},
            "modes": {
                "alpha": {
                    "system_prompt_text": "Test system",
                    "validation": {"required_patterns": ["(?m)^result:"]},
                    "request_body": {"top_p": 0.8},
                }
            },
            "validation": {"required_patterns": [], "forbidden_patterns": []},
            "observations": [{
                "id": "token",
                "input_pattern": "\"([^\"]+)\"",
                "text_group": 1,
                "marker_group": 0,
                "remove_marker_in_final": True,
            }],
            "output": {
                "run_prefix": "test",
                "aggregate_title": "Test Outputs",
                "summary_title": "Test Summary",
                "all_outputs_file": "ALL.md",
                "raw_outputs_file": "RAW.md",
                "records_file": "RECORDS.csv",
                "observations_file": "OBSERVATIONS.csv",
                "summary_file": "SUMMARY.md",
            },
        }), encoding="utf-8")
        self.manifest_path.write_text(json.dumps({"inputs": [
            {"id": "one", "content": 'alpha\nfirst "TOKEN"'},
            {"id": "two", "content": "ALPHA\nsecond"},
        ]}), encoding="utf-8")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def options(self) -> BatchOptions:
        return BatchOptions(
            app_config_path=self.config_path,
            profile_path=self.profile_path,
            input_manifest_path=self.manifest_path,
            mode="auto",
            repeats=2,
            max_tokens=100,
            seed_base=40,
            model_ids=["model-a", "model-b"],
            run_directory=self.root / "run",
        )

    def test_validate_multi_input_auto_mode(self) -> None:
        report = validate_batch(self.options())
        self.assertEqual(report.profile_id, "test")
        self.assertEqual([case.mode for case in report.cases], ["alpha", "alpha"])
        self.assertEqual(report.model_count, 2)

    def test_full_run_preserves_order_and_writes_outputs(self) -> None:
        run_dir = run_batch(self.options(), log=lambda _message: None)
        self.assertEqual(len(MockApiHandler.requests), 8)
        order = [
            (request["model"], request["seed"], request["messages"][-1]["content"].splitlines()[1])
            for request in MockApiHandler.requests
        ]
        self.assertEqual(order, [
            ("model-a", 41, 'first "TOKEN"'), ("model-a", 41, "second"),
            ("model-a", 42, 'first "TOKEN"'), ("model-a", 42, "second"),
            ("model-b", 41, 'first "TOKEN"'), ("model-b", 41, "second"),
            ("model-b", 42, 'first "TOKEN"'), ("model-b", 42, "second"),
        ])
        self.assertEqual(MockApiHandler.requests[0]["temperature"], 0.4)
        self.assertEqual(MockApiHandler.requests[0]["top_p"], 0.8)
        raw = (run_dir / "results" / "model-a" / "one" / "run-01.md").read_text(encoding="utf-8")
        final = (run_dir / "final-results" / "model-a" / "one" / "run-01.md").read_text(encoding="utf-8")
        self.assertIn('"TOKEN"', raw)
        self.assertNotIn('"TOKEN"', final)
        self.assertIn("TOKEN", final)
        for name in ("ALL.md", "RAW.md", "RECORDS.csv", "OBSERVATIONS.csv", "SUMMARY.md", "manifest.json"):
            self.assertTrue((run_dir / name).is_file(), name)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["request_order"], "model -> repeat -> input")
        self.assertEqual(manifest["failures"], [])


if __name__ == "__main__":
    unittest.main()
