from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass


NVIDIA_QUERY_FIELDS = (
    "index",
    "name",
    "memory.total",
    "memory.used",
    "memory.free",
    "utilization.gpu",
    "temperature.gpu",
)


class GpuMonitorError(RuntimeError):
    """Raised when local GPU telemetry cannot be collected or parsed."""


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    index: int
    name: str
    memory_total_mib: int
    memory_used_mib: int
    memory_free_mib: int
    utilization_percent: int
    temperature_celsius: int

    @property
    def memory_percent(self) -> float:
        if self.memory_total_mib <= 0:
            return 0.0
        return min(100.0, max(0.0, self.memory_used_mib * 100.0 / self.memory_total_mib))


def _integer(value: str, field: str) -> int:
    try:
        return int(float(value.strip()))
    except ValueError as exc:
        raise GpuMonitorError(f"Invalid {field} value from nvidia-smi: {value!r}") from exc


def parse_nvidia_smi_csv(text: str) -> list[GpuSnapshot]:
    snapshots: list[GpuSnapshot] = []
    for row in csv.reader(io.StringIO(text)):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != len(NVIDIA_QUERY_FIELDS):
            raise GpuMonitorError(
                f"Unexpected nvidia-smi column count: expected {len(NVIDIA_QUERY_FIELDS)}, got {len(row)}"
            )
        snapshots.append(
            GpuSnapshot(
                index=_integer(row[0], "index"),
                name=row[1].strip(),
                memory_total_mib=_integer(row[2], "memory.total"),
                memory_used_mib=_integer(row[3], "memory.used"),
                memory_free_mib=_integer(row[4], "memory.free"),
                utilization_percent=_integer(row[5], "utilization.gpu"),
                temperature_celsius=_integer(row[6], "temperature.gpu"),
            )
        )
    if not snapshots:
        raise GpuMonitorError("nvidia-smi returned no GPU rows")
    return snapshots


def query_nvidia_gpus(command: str, timeout_seconds: float) -> list[GpuSnapshot]:
    arguments = [
        command,
        "--query-gpu=" + ",".join(NVIDIA_QUERY_FIELDS),
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise GpuMonitorError(f"GPU monitor command was not found: {command}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GpuMonitorError(f"GPU monitor timed out after {timeout_seconds:g} seconds") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise GpuMonitorError(f"nvidia-smi failed: {detail}")
    return parse_nvidia_smi_csv(completed.stdout)
