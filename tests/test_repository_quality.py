from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

import prompt_batch
from prompt_batch import engine
from prompt_batch import model_catalog, model_source
from prompt_batch.storage import atomic_write_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class RepositoryQualityTests(unittest.TestCase):
    def test_compatibility_modules_forward_to_public_implementations(self) -> None:
        self.assertIs(engine.BatchOptions, prompt_batch.BatchOptions)
        self.assertIs(engine.run_batch, prompt_batch.run_batch)
        self.assertIs(model_source.ModelGroup, model_catalog.ModelFamily)
        self.assertIs(model_source.ModelTier, model_catalog.ParameterTier)
        self.assertIs(model_source.group_models, model_catalog.group_model_families)
        self.assertIs(model_source.group_model_tiers, model_catalog.group_parameter_tiers)

    def test_compatibility_layers_remain_thin(self) -> None:
        limits = {
            PROJECT_ROOT / "app.py": 12,
            PROJECT_ROOT / "batch_cli.py": 12,
            PROJECT_ROOT / "prompt_batch" / "engine.py": 24,
            PROJECT_ROOT / "prompt_batch" / "model_source.py": 36,
        }
        for path, maximum in limits.items():
            with self.subTest(path=path.name):
                self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), maximum)

    def test_core_modules_do_not_depend_on_user_interfaces(self) -> None:
        core_paths = [
            PROJECT_ROOT / "prompt_batch" / name
            for name in (
                "config.py", "domain.py", "model_catalog.py", "preparation.py",
                "reporting.py", "runner.py", "runtime.py", "storage.py",
            )
        ]
        core_paths.extend((PROJECT_ROOT / "prompt_batch" / "backends").glob("*.py"))
        forbidden = {"prompt_batch.gui", "prompt_batch.cli"}
        for path in core_paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            imports.update(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            with self.subTest(path=path.name):
                self.assertTrue(forbidden.isdisjoint(imports))

    def test_local_markdown_links_exist(self) -> None:
        markdown_files = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "CHANGELOG.md"]
        markdown_files.extend((PROJECT_ROOT / "docs").glob("*.md"))
        link_pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
        for document in markdown_files:
            for target in link_pattern.findall(document.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#")):
                    continue
                relative_target = target.split("#", 1)[0]
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / relative_target).resolve().exists())

    def test_atomic_json_write_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "state.json"
            atomic_write_json(path, {"ready": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ready": True})

    def test_ci_covers_supported_windows_python_versions(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('python-version: ["3.11", "3.14"]', workflow)
        self.assertIn("python -B -m unittest discover -s tests -v", workflow)
        self.assertIn("runs-on: windows-latest", workflow)


if __name__ == "__main__":
    unittest.main()
