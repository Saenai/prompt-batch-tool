from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from prompt_batch.runtime import terminate_process_tree, runtime_version


def process(*, running: bool = True) -> MagicMock:
    value = MagicMock()
    value.pid = 4321
    value.poll.return_value = None if running else 0
    return value


class RuntimeTests(unittest.TestCase):
    def test_optional_version_probe_is_bounded_and_failure_tolerant(self):
        prepared = MagicMock()
        prepared.app_config = {'router': {'auto_start': True}, 'backend': {'base_url': 'http://localhost/v1'}}
        prepared.base_url = 'http://localhost/v1'
        for error in (OSError('missing DLL'), subprocess.TimeoutExpired('version', 10)):
            with self.subTest(error=error), patch('prompt_batch.runtime.subprocess.run', side_effect=error) as run:
                self.assertIsNone(runtime_version(prepared))
                self.assertEqual(run.call_args.kwargs['timeout'], 10)

    def test_external_backend_does_not_probe_local_executable(self):
        prepared = MagicMock()
        prepared.app_config = {'router': {'auto_start': True}, 'backend': {'base_url': 'http://localhost/v1'}}
        prepared.base_url = 'https://remote.invalid/v1'
        with patch('prompt_batch.runtime.subprocess.run') as run:
            self.assertIsNone(runtime_version(prepared))
            prepared.base_url = 'http://localhost/v1'
            prepared.app_config['router']['auto_start'] = False
            self.assertIsNone(runtime_version(prepared))
            run.assert_not_called()

    def test_finished_process_is_left_untouched(self) -> None:
        value = process(running=False)
        terminate_process_tree(value)
        value.terminate.assert_not_called()
        value.kill.assert_not_called()

    def test_non_windows_process_is_terminated_gracefully(self) -> None:
        value = process()
        with patch("prompt_batch.runtime.os.name", "posix"):
            terminate_process_tree(value)
        value.terminate.assert_called_once_with()
        value.wait.assert_called_once_with(timeout=5)
        value.kill.assert_not_called()

    def test_non_windows_stubborn_process_is_killed(self) -> None:
        value = process()
        value.wait.side_effect = subprocess.TimeoutExpired("router", 5)
        with patch("prompt_batch.runtime.os.name", "posix"):
            terminate_process_tree(value)
        value.terminate.assert_called_once_with()
        value.kill.assert_called_once_with()

    def test_windows_uses_taskkill_for_the_process_tree(self) -> None:
        value = process()
        with (
            patch("prompt_batch.runtime.os.name", "nt"),
            patch("prompt_batch.runtime.Path.is_file", return_value=True),
            patch("prompt_batch.runtime.subprocess.run") as run,
        ):
            terminate_process_tree(value)

        command = run.call_args.args[0]
        self.assertEqual(command[-4:], ["/PID", "4321", "/T", "/F"])
        value.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
