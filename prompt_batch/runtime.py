from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .domain import PreparedBatch


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", "")) / "System32" / "taskkill.exe"
        if taskkill.is_file():
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def start_router(prepared: PreparedBatch, log_dir: Path) -> subprocess.Popen[Any]:
    app = prepared.app_config
    executable = prepared.paths["router_executable"]
    working_directory = prepared.paths["router_working_directory"]
    if not executable.is_file():
        raise FileNotFoundError(f"Configured router executable not found: {executable}")
    stdout_file = (log_dir / "router.stdout.log").open("w", encoding="utf-8")
    stderr_file = (log_dir / "router.stderr.log").open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            [str(executable), *[str(arg) for arg in app["router"]["arguments"]]],
            cwd=working_directory,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        stdout_file.close()
        stderr_file.close()


def runtime_version(prepared: PreparedBatch) -> str | None:
    app = prepared.app_config
    if (not app['router'].get('auto_start', True)
            or prepared.base_url.rstrip('/') != str(app['backend']['base_url']).rstrip('/')):
        return None
    executable = prepared.paths.get("runtime_executable")
    if not executable or not executable.is_file():
        return None
    try:
        result = subprocess.run(
            [str(executable), *[str(arg) for arg in app.get("runtime", {}).get("version_arguments", [])]],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout + result.stderr).strip() or None if result.returncode == 0 else None
