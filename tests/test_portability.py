import json
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from prompt_batch import BatchOptions, run_batch
from prompt_batch.config import ConfigValidationError, load_app_config

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_cli_errors_support_unicode_paths_with_legacy_code_page(self):
        env = dict(os.environ, PYTHONIOENCODING='cp932')
        result = subprocess.run([sys.executable, str(ROOT/'batch_cli.py'),
            '--app-config', str(ROOT/'config/app.json'), '--profile', str(ROOT/'profiles/plain.json'),
            '--input-manifest', str(ROOT/'不存在的输入.json'), '--mode', 'default',
            '--repeats', '1', '--max-tokens', '16', '--model', 'example-model', '--validate-only'],
            env=env, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertIn('不存在的输入', result.stderr)
        self.assertNotIn('UnicodeEncodeError', result.stderr)

    def test_gui_self_test_accepts_api_only_public_config(self):
        from prompt_batch.gui import self_test
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self_test(ROOT / 'config/app.json'), 0)

    def test_public_example_runs_in_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'standalone'
            root.mkdir()
            for name in ('prompt_batch', 'config', 'profiles', 'examples'):
                shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('*.local.json', '__pycache__', 'h3-system-prompts'))
            shutil.copy2(ROOT / 'batch_cli.py', root / 'batch_cli.py')
            result = subprocess.run([sys.executable, '-B', 'batch_cli.py', '--app-config', 'config/app.json', '--profile', 'profiles/plain.json', '--input-manifest', 'examples/plain-input.json', '--mode', 'default', '--repeats', '1', '--max-tokens', '64', '--model', 'example-model', '--validate-only'], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Validation OK', result.stdout)
            self.assertFalse((root / 'config/app.local.json').exists())
            self.assertFalse((root / 'output').exists())

    def test_disabled_auto_start_never_launches_router(self):
        with tempfile.TemporaryDirectory() as directory:
            options = BatchOptions(app_config_path=ROOT/'config/app.json', profile_path=ROOT/'profiles/plain.json', input_manifest_path=ROOT/'examples/plain-input.json', mode='default', repeats=1, max_tokens=64, seed_base=1, model_ids=['example-model'], output_root=Path(directory))
            backend = Mock()
            backend.ready.return_value = False
            backend.models_uri = 'http://example.invalid/v1/models'
            with patch('prompt_batch.runner.create_backend', return_value=backend), patch('prompt_batch.runner.start_router') as start:
                with self.assertRaisesRegex(RuntimeError, 'auto-start is disabled'):
                    run_batch(options, log=lambda _: None)
                start.assert_not_called()

    def test_legacy_default_and_boolean_validation(self):
        payload = json.loads((ROOT/'config/app.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.json'
            payload['router'].pop('auto_start')
            path.write_text(json.dumps(payload), encoding='utf-8')
            self.assertTrue(load_app_config(path)['router'].get('auto_start', True))
            payload['router']['auto_start'] = 'false'
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaises(ConfigValidationError):
                load_app_config(path)
