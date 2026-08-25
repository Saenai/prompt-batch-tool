from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from prompt_batch import BatchOptions, run_batch, validate_batch


class MockApiHandler(BaseHTTPRequestHandler):
    models = ["model-a", "model-b"]
    requests: list[dict] = []
    failed_requests: set[tuple[str, int, str]] = set()
    invalid_json_requests: set[tuple[str, int, str]] = set()

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
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
        request["_authorization"] = self.headers.get("Authorization")
        self.requests.append(request)
        user_content = request["messages"][-1]["content"]
        input_name = user_content.splitlines()[-1].split()[0]
        request_key = (request["model"], request["seed"], input_name)
        if request_key in self.failed_requests:
            self.send_error(503, "simulated model failure")
            return
        if request_key in self.invalid_json_requests:
            self._send_raw(b"{invalid-json")
            return
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
        MockApiHandler.models = ["model-a", "model-b"]
        MockApiHandler.failed_requests = set()
        MockApiHandler.invalid_json_requests = set()
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
                "engine": "batch_cli.py",
                "profiles": "profiles",
                "state": "state.json",
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
                "structured_outputs_file": "PROMPTS.jsonl",
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
            random_seed=False,
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
        for name in ("ALL.md", "RAW.md", "RECORDS.csv", "OBSERVATIONS.csv", "PROMPTS.jsonl", "SUMMARY.md", "manifest.json"):
            self.assertTrue((run_dir / name).is_file(), name)
        prompt_rows = [json.loads(line) for line in (run_dir / "PROMPTS.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(prompt_rows), 8)
        self.assertEqual(
            list(prompt_rows[0]), ["sequence", "model", "repeat", "input", "mode", "prompt"]
        )
        self.assertEqual(prompt_rows[0]["model"], "model-a")
        self.assertEqual(prompt_rows[0]["repeat"], 1)
        self.assertIn("result: TOKEN", prompt_rows[0]["prompt"])
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["request_order"], "model -> repeat -> input")
        self.assertEqual(manifest["failures"], [])
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(list((run_dir / "raw").rglob("*.record.json"))), 8)

    def test_random_seed_is_generated_once_and_saved_for_resume(self) -> None:
        options = self.options()
        options.random_seed = True
        with patch("prompt_batch.runner.secrets.randbelow", return_value=1233) as random_seed:
            run_dir = run_batch(options, log=lambda _message: None)

        random_seed.assert_called_once()
        self.assertEqual(sorted({request["seed"] for request in MockApiHandler.requests}), [1235, 1236])
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["random_seed"])
        self.assertEqual(manifest["seed_base"], 1234)

        options.resume = True
        with patch("prompt_batch.runner.secrets.randbelow", side_effect=AssertionError("resume must not randomize")):
            run_batch(options, log=lambda _message: None)
        self.assertEqual(sorted({request["seed"] for request in MockApiHandler.requests}), [1235, 1236])

    def test_model_ids_with_windows_special_characters_use_safe_output_directories(self) -> None:
        MockApiHandler.models = ["model:off"]
        options = self.options()
        options.model_ids = ["model:off"]
        run_dir = run_batch(options, log=lambda _message: None)

        output = run_dir / "results" / "model~003Aoff" / "one" / "run-01.md"
        self.assertTrue(output.is_file())
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["models"], ["model:off"])
        self.assertIn("# Model: model:off", (run_dir / "ALL.md").read_text(encoding="utf-8"))

    def test_html_aggregate_is_multiline_and_optional_reports_are_omitted(self) -> None:
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        profile["output"] = {
            "aggregate_title": "HTML Outputs",
            "all_outputs_file": "ALL-PROMPTS.html",
        }
        self.profile_path.write_text(json.dumps(profile), encoding="utf-8")
        run_dir = run_batch(self.options(), log=lambda _message: None)

        html = (run_dir / "ALL-PROMPTS.html").read_text(encoding="utf-8")
        self.assertIn("<th>#</th><th>Model</th><th>Repeat</th><th>Prompt</th>", html)
        self.assertIn('<td class="sequence">1</td>', html)
        self.assertIn('<td class="sequence">2</td>', html)
        self.assertIn("<pre>result: TOKEN\nmodel=model-a seed=41</pre>", html)
        self.assertFalse((run_dir / "RAW.md").exists())
        self.assertFalse((run_dir / "RECORDS.csv").exists())
        self.assertFalse((run_dir / "SUMMARY.md").exists())
        self.assertFalse((run_dir / "PROMPTS.jsonl").exists())

    def test_resume_skips_successful_items(self) -> None:
        run_batch(self.options(), log=lambda _message: None)
        events: list[dict] = []
        options = self.options()
        options.resume = True
        run_batch(options, log=lambda _message: None, event=events.append)

        self.assertEqual(len(MockApiHandler.requests), 8)
        skipped = [event for event in events if event["type"] == "item_finished"]
        self.assertEqual(len(skipped), 8)
        self.assertTrue(all(event["status"] == "skipped" for event in skipped))
        finished = next(event for event in events if event["type"] == "batch_finished")
        self.assertEqual((finished["executed"], finished["skipped"]), (0, 8))

    def test_resume_accepts_previous_backend_identity_fields(self) -> None:
        run_dir = run_batch(self.options(), log=lambda _message: None)
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest.pop("backend")
        manifest["endpoint"] = backend["base_url"]
        manifest["backend_request_body"] = backend["request_body"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        options = self.options()
        options.resume = True
        run_batch(options, log=lambda _message: None)
        self.assertEqual(len(MockApiHandler.requests), 8)

    def test_resume_runs_only_missing_items(self) -> None:
        run_dir = run_batch(self.options(), log=lambda _message: None)
        (run_dir / "raw" / "model-a" / "one" / "run-01.record.json").unlink()
        options = self.options()
        options.resume = True
        run_batch(options, log=lambda _message: None)

        self.assertEqual(len(MockApiHandler.requests), 9)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["planned_requests_this_run"], 1)
        self.assertEqual(manifest["executed_items_this_run"], 1)
        self.assertEqual(manifest["skipped_items_this_run"], 7)

    def test_retry_failed_runs_only_recorded_failures(self) -> None:
        run_dir = run_batch(self.options(), log=lambda _message: None)
        record_path = run_dir / "raw" / "model-b" / "two" / "run-02.record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record.update({"success": False, "valid_output": False, "error": "simulated failure"})
        record_path.write_text(json.dumps(record), encoding="utf-8")
        options = self.options()
        options.retry_failed_only = True
        run_batch(options, log=lambda _message: None)

        self.assertEqual(len(MockApiHandler.requests), 9)
        repaired = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertTrue(repaired["success"])

    def test_resume_rejects_changed_batch_identity(self) -> None:
        run_batch(self.options(), log=lambda _message: None)
        options = self.options()
        options.resume = True
        options.max_tokens = 101
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            run_batch(options, log=lambda _message: None)

    def test_retry_failed_rejects_missing_records(self) -> None:
        run_dir = run_batch(self.options(), log=lambda _message: None)
        (run_dir / "raw" / "model-a" / "one" / "run-01.record.json").unlink()
        options = self.options()
        options.retry_failed_only = True
        with self.assertRaisesRegex(ValueError, "complete set"):
            run_batch(options, log=lambda _message: None)

    def test_endpoint_failure_leaves_resumable_manifest(self) -> None:
        options = self.options()
        options.base_url = "http://127.0.0.1:1/v1"
        with self.assertRaisesRegex(RuntimeError, "Endpoint is unavailable"):
            run_batch(options, log=lambda _message: None)

        manifest_path = options.run_directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "interrupted")
        self.assertEqual(manifest["planned_requests_this_run"], 8)

    def test_environment_auth_is_sent_without_entering_manifest(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["backend"]["auth"] = {
            "type": "environment",
            "environment_variable": "PROMPT_BATCH_TEST_KEY",
        }
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        with patch.dict("os.environ", {"PROMPT_BATCH_TEST_KEY": "secret-value"}):
            run_dir = run_batch(self.options(), log=lambda _message: None)

        self.assertTrue(all(request["_authorization"] == "Bearer secret-value" for request in MockApiHandler.requests))
        manifest_text = (run_dir / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-value", manifest_text)
        self.assertIn("PROMPT_BATCH_TEST_KEY", manifest_text)

    def test_missing_model_interrupts_before_any_generation_request(self) -> None:
        MockApiHandler.models = ["model-a"]
        options = self.options()
        with self.assertRaisesRegex(RuntimeError, "model-b"):
            run_batch(options, log=lambda _message: None)

        self.assertEqual(MockApiHandler.requests, [])
        manifest = json.loads((options.run_directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "interrupted")
        self.assertIn("model-b", manifest["error"])

    def test_partial_http_failure_is_recorded_and_reports_are_still_written(self) -> None:
        MockApiHandler.failed_requests = {("model-a", 41, "second")}
        options = self.options()
        options.model_ids = ["model-a"]
        options.repeats = 1
        events: list[dict] = []

        with self.assertRaisesRegex(RuntimeError, "Failures: 1"):
            run_batch(options, log=lambda _message: None, event=events.append)

        run_dir = options.run_directory
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed_with_failures")
        self.assertEqual(len(manifest["failures"]), 1)
        success_record = json.loads(
            (run_dir / "raw" / "model-a" / "one" / "run-01.record.json").read_text(encoding="utf-8")
        )
        failure_record = json.loads(
            (run_dir / "raw" / "model-a" / "two" / "run-01.record.json").read_text(encoding="utf-8")
        )
        self.assertTrue(success_record["success"])
        self.assertFalse(failure_record["success"])
        self.assertEqual(failure_record["finish_reason"], "request_error")
        for name in ("ALL.md", "RAW.md", "RECORDS.csv", "OBSERVATIONS.csv", "SUMMARY.md"):
            self.assertTrue((run_dir / name).is_file(), name)
        finished = next(event for event in events if event["type"] == "batch_finished")
        self.assertEqual((finished["completed"], finished["failures"]), (2, 1))

    def test_invalid_json_failure_does_not_prevent_later_items(self) -> None:
        MockApiHandler.invalid_json_requests = {("model-a", 41, "first")}
        options = self.options()
        options.model_ids = ["model-a"]
        options.repeats = 1

        with self.assertRaisesRegex(RuntimeError, "Failures: 1"):
            run_batch(options, log=lambda _message: None)

        self.assertEqual(len(MockApiHandler.requests), 2)
        failed_record = json.loads(
            (options.run_directory / "raw" / "model-a" / "one" / "run-01.record.json").read_text(encoding="utf-8")
        )
        later_record = json.loads(
            (options.run_directory / "raw" / "model-a" / "two" / "run-01.record.json").read_text(encoding="utf-8")
        )
        self.assertFalse(failed_record["success"])
        self.assertIn("invalid JSON", failed_record["error"])
        self.assertTrue(later_record["success"])


if __name__ == "__main__":
    unittest.main()
