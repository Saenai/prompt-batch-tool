from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from prompt_batch.result_catalog import scan_recent_runs


class ResultCatalogTests(unittest.TestCase):
    def _write_run(
        self,
        root: Path,
        name: str,
        aggregate_name: str,
        *,
        timestamp: float,
        use_manifest_files: bool = True,
    ) -> Path:
        run = root / name
        (run / "input").mkdir(parents=True)
        aggregate = run / aggregate_name
        aggregate.write_text("# results", encoding="utf-8")
        summary = run / "SUMMARY.md"
        summary.write_text("# summary", encoding="utf-8")
        manifest = {"status": "completed"}
        if use_manifest_files:
            manifest["output_files"] = {"all": aggregate_name, "summary": "SUMMARY.md"}
        else:
            (run / "input" / "profile.json").write_text(
                json.dumps({"output": {"all_outputs_file": aggregate_name, "summary_file": "SUMMARY.md"}}),
                encoding="utf-8",
            )
        manifest_path = run / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        os.utime(aggregate, (timestamp, timestamp))
        os.utime(manifest_path, (timestamp, timestamp))
        return run

    def test_scans_only_direct_runs_and_orders_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = self._write_run(root, "older", "ALL-PROMPTS.md", timestamp=1000)
            newer = self._write_run(root, "newer", "ALL-OUTPUTS.md", timestamp=2000)
            (root / "not-a-run").mkdir()
            entries = scan_recent_runs(root, 10)

        self.assertEqual([entry.run_directory.name for entry in entries], [newer.name, older.name])
        self.assertEqual(entries[0].aggregate_path.name, "ALL-OUTPUTS.md")
        self.assertEqual(entries[0].summary_path.name, "SUMMARY.md")

    def test_uses_frozen_profile_for_older_manifest_and_honors_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_run(root, "first", "CUSTOM-ALL.md", timestamp=1000, use_manifest_files=False)
            self._write_run(root, "second", "ALL-PROMPTS.md", timestamp=2000)
            entries = scan_recent_runs(root, 1)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].run_directory.name, "second")

    def test_missing_or_escaping_aggregate_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "unsafe"
            run.mkdir()
            (run / "manifest.json").write_text(
                json.dumps({"status": "completed", "output_files": {"all": "../outside.md"}}),
                encoding="utf-8",
            )
            (root / "outside.md").write_text("outside", encoding="utf-8")
            self.assertEqual(scan_recent_runs(root, 10), [])


if __name__ == "__main__":
    unittest.main()
