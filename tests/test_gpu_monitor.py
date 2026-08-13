from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from prompt_batch.gpu_monitor import GpuMonitorError, parse_nvidia_smi_csv, query_nvidia_gpus


class GpuMonitorTests(unittest.TestCase):
    def test_parses_multiple_gpu_rows_and_memory_percentage(self) -> None:
        snapshots = parse_nvidia_smi_csv(
            "0, NVIDIA GeForce RTX 4090, 24564, 12282, 12282, 88, 67\n"
            "1, NVIDIA RTX A4000, 16376, 4094, 12282, 25, 54\n"
        )

        self.assertEqual([snapshot.index for snapshot in snapshots], [0, 1])
        self.assertEqual(snapshots[0].name, "NVIDIA GeForce RTX 4090")
        self.assertAlmostEqual(snapshots[0].memory_percent, 50.0)
        self.assertEqual(snapshots[1].temperature_celsius, 54)

    def test_rejects_unexpected_columns(self) -> None:
        with self.assertRaisesRegex(GpuMonitorError, "column count"):
            parse_nvidia_smi_csv("0, RTX 4090, 24564\n")

    @patch("prompt_batch.gpu_monitor.subprocess.run")
    def test_query_uses_configured_command_and_no_units_csv(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0, RTX 4090, 24564, 1024, 23540, 12, 40\n", stderr=""
        )

        snapshots = query_nvidia_gpus("custom-nvidia-smi", 3.5)

        self.assertEqual(len(snapshots), 1)
        arguments = run_mock.call_args.args[0]
        self.assertEqual(arguments[0], "custom-nvidia-smi")
        self.assertIn("--format=csv,noheader,nounits", arguments)
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 3.5)

    @patch("prompt_batch.gpu_monitor.subprocess.run")
    def test_query_reports_driver_error(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=9, stdout="", stderr="driver unavailable"
        )
        with self.assertRaisesRegex(GpuMonitorError, "driver unavailable"):
            query_nvidia_gpus("nvidia-smi", 5)


if __name__ == "__main__":
    unittest.main()
