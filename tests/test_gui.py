from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from prompt_batch.gui import default_config_path, engine_command


class GuiCommandTests(unittest.TestCase):
    def test_python_engine_uses_current_interpreter(self) -> None:
        with patch("prompt_batch.gui.sys.executable", "python-test.exe"):
            command = engine_command(Path("batch_cli.py"))
        self.assertEqual(command, ["python-test.exe", "-B", "batch_cli.py"])

    def test_packaged_engine_runs_directly(self) -> None:
        command = engine_command(Path("PromptBatchCLI.exe"))
        self.assertEqual(command, ["PromptBatchCLI.exe"])

    def test_default_config_is_relative_to_application_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("prompt_batch.gui.PROJECT_ROOT", Path(directory)):
            expected = Path(directory) / "config" / "app.json"
            self.assertEqual(default_config_path(), expected)
            expected.parent.mkdir()
            local = expected.with_name("app.local.json")
            local.write_text("{}", encoding="utf-8")
            self.assertEqual(default_config_path(), local)


if __name__ == "__main__":
    unittest.main()
