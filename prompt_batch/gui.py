from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .config import expand_path, load_app_config, load_json, load_profile, resolve_config_paths
from .gpu_monitor import query_nvidia_gpus
from .gui_gpu import GpuMonitorPanel
from .gui_models import ModelSelector
from .gui_results import RecentResultsPanel
from .model_catalog import (
    discover_models,
    group_model_families,
    group_parameter_tiers,
    parse_llama_swap_models,
)
from .runtime import terminate_process_tree
from .router_control import unload_all_models
from .storage import atomic_write_json


PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
RUN_STRATEGY_LABELS = {
    "new": "新运行",
    "resume": "续跑未完成",
    "retry-failed": "仅重试失败",
}
RUN_STRATEGY_KEYS = {label: key for key, label in RUN_STRATEGY_LABELS.items()}


def engine_command(engine_path: Path) -> list[str]:
    """Return the invocation prefix for a source script or packaged CLI."""
    if engine_path.suffix.casefold() in {".py", ".pyw"}:
        return [sys.executable, "-B", str(engine_path)]
    return [str(engine_path)]


def default_config_path() -> Path:
    local = PROJECT_ROOT / "config" / "app.local.json"
    return local if local.is_file() else PROJECT_ROOT / "config" / "app.json"


class PromptBatchApp:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path.resolve()
        self.config_dir = self.config_path.parent
        self.config = load_app_config(self.config_path)
        self.paths = resolve_config_paths(self.config, self.config_path)
        self.profiles = self._load_profiles(self.paths["profiles"])
        self.state = self._load_state()
        defaults = self.config.get("defaults", {})

        self.process: subprocess.Popen[str] | None = None
        self.temp_manifest: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        initial_profile = self.state.get("profile", defaults.get("profile", next(iter(self.profiles))))
        if initial_profile not in self.profiles:
            initial_profile = next(iter(self.profiles))
        self.profile_var = tk.StringVar(value=initial_profile)
        self.mode_var = tk.StringVar(value=self.state.get("mode", defaults.get("mode", "auto")))
        self.output_root_var = tk.StringVar(value=self.state.get("output_root", str(self.paths["default_output_root"])))
        self.run_directory_var = tk.StringVar(value=self.state.get("run_directory", ""))
        self.system_prompt_var = tk.StringVar(value=self.state.get("system_prompt", ""))
        self.repeats_var = tk.StringVar(value=str(self.state.get("repeats", defaults.get("repeats", 1))))
        self.max_tokens_var = tk.StringVar(value=str(self.state.get("max_tokens", defaults.get("max_tokens", 2048))))
        self.seed_base_var = tk.StringVar(value=str(self.state.get("seed_base", defaults.get("seed_base", 1))))
        self.random_seed_var = tk.BooleanVar(value=bool(self.state.get("random_seed", defaults.get("random_seed", True))))
        self.base_url_var = tk.StringVar(value=self.state.get("base_url", self.config["backend"]["base_url"]))
        self.remember_direct_var = tk.BooleanVar(value=bool(self.state.get("remember_direct_input", defaults.get("remember_direct_input", False))))
        strategy_key = str(self.state.get("run_strategy", "new"))
        self.run_strategy_var = tk.StringVar(value=RUN_STRATEGY_LABELS.get(strategy_key, RUN_STRATEGY_LABELS["new"]))
        self.status_var = tk.StringVar(value="就绪")
        self.progress_detail_var = tk.StringVar(value="尚未开始")
        self.gpu_monitor_config = self.config["gpu_monitor"]
        self.gpu_poll_pending = False
        self.unload_in_progress = False
        self.result_refresh_after: str | None = None
        self.closing = False

        self.root.title(self.config.get("app", {}).get("title", "Prompt Batch Generator"))
        self.root.geometry(self.state.get("geometry", "1280x820"))
        self.root.minsize(1050, 680)
        self._build_ui()
        self._update_seed_controls()
        self._restore_inputs()
        self._apply_profile_modes()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)
        self.root.after(150, self.refresh_models)
        self.root.after(250, self._schedule_gpu_poll)
        self.output_root_var.trace_add("write", lambda *_args: self._schedule_results_refresh())
        self.root.after(350, self._refresh_results)

    @staticmethod
    def _load_profiles(directory: Path) -> dict[str, tuple[Path, dict]]:
        profiles: dict[str, tuple[Path, dict]] = {}
        for path in sorted(directory.glob("*.json")):
            payload = load_profile(path)
            profile_id = str(payload.get("id", "")).strip()
            if profile_id:
                profiles[profile_id] = (path.resolve(), payload)
        if not profiles:
            raise ValueError(f"Profile 目录中没有有效 JSON：{directory}")
        return profiles

    def _load_state(self) -> dict:
        state_path = self.paths["state"]
        if not state_path.is_file():
            return {}
        try:
            state = load_json(state_path)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1, uniform="main-column")
        outer.columnconfigure(1, weight=1, uniform="main-column")
        outer.rowconfigure(0, weight=1)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=2)

        settings = ttk.LabelFrame(left, text="任务设置", padding=8)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        settings.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(settings, text="Profile").grid(row=row, column=0, sticky="w", pady=3)
        profile_values = [f"{pid} — {payload.get('display_name', pid)}" for pid, (_, payload) in self.profiles.items()]
        self.profile_combo = ttk.Combobox(settings, values=profile_values, state="readonly")
        self.profile_combo.grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        self.profile_combo.set(self._profile_display(self.profile_var.get()))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(settings, text="重新读取", command=self._reload_profiles).grid(row=row, column=2, sticky="ew", pady=3)
        row += 1

        row = self._path_row(settings, row, "输出根目录", self.output_root_var, lambda: self._browse_dir(self.output_root_var))
        row = self._path_row(settings, row, "固定运行目录", self.run_directory_var, lambda: self._browse_dir(self.run_directory_var), "续跑时必填")
        row = self._path_row(settings, row, "System Prompt 覆盖", self.system_prompt_var, self._browse_system_prompt, "可选")

        params = ttk.Frame(settings)
        params.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(7, 4))
        for index in (1, 3):
            params.columnconfigure(index, weight=1)
        ttk.Label(params, text="Mode").grid(row=0, column=0, sticky="w")
        self.mode_combo = ttk.Combobox(params, textvariable=self.mode_var, state="readonly", width=12)
        self.mode_combo.grid(row=0, column=1, sticky="ew", padx=(5, 14), pady=2)
        ttk.Label(params, text="Repeats").grid(row=0, column=2, sticky="w")
        ttk.Entry(params, textvariable=self.repeats_var, width=8).grid(row=0, column=3, sticky="ew", padx=(5, 0), pady=2)
        ttk.Label(params, text="Max tokens").grid(row=1, column=0, sticky="w")
        ttk.Entry(params, textvariable=self.max_tokens_var, width=10).grid(row=1, column=1, sticky="ew", padx=(5, 14), pady=2)
        ttk.Label(params, text="Seed base").grid(row=1, column=2, sticky="w")
        self.seed_base_entry = ttk.Entry(params, textvariable=self.seed_base_var, width=12)
        self.seed_base_entry.grid(row=1, column=3, sticky="ew", padx=(5, 0), pady=2)
        ttk.Checkbutton(params, text="新运行使用随机 seed", variable=self.random_seed_var,
                        command=self._update_seed_controls).grid(row=2, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(params, text="运行策略").grid(row=3, column=0, sticky="w")
        self.run_strategy_combo = ttk.Combobox(
            params,
            textvariable=self.run_strategy_var,
            values=list(RUN_STRATEGY_LABELS.values()),
            state="readonly",
        )
        self.run_strategy_combo.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(5, 0), pady=2)
        row += 1

        inputs = ttk.LabelFrame(left, text="输入内容", padding=8)
        inputs.grid(row=1, column=0, sticky="nsew")
        inputs.columnconfigure(0, weight=1)
        inputs.rowconfigure(3, weight=1)
        input_header = ttk.Frame(inputs)
        input_header.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        input_header.columnconfigure(0, weight=1)
        ttk.Label(input_header, text="输入文件（每行一个）").grid(row=0, column=0, sticky="w")
        ttk.Button(input_header, text="添加文件…", command=self._add_input_files).grid(row=0, column=1, padx=(4, 4))
        ttk.Button(input_header, text="清空", command=lambda: self.input_files.delete("1.0", "end")).grid(row=0, column=2)
        self.input_files = scrolledtext.ScrolledText(inputs, height=4, wrap="none", font=("Consolas", 9))
        self.input_files.grid(row=1, column=0, sticky="ew")

        direct_header = ttk.Frame(inputs)
        direct_header.grid(row=2, column=0, sticky="ew", pady=(8, 3))
        direct_header.columnconfigure(0, weight=1)
        ttk.Label(direct_header, text="直接输入（可作为批次中的另一条 prompt）").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(direct_header, text="记住正文", variable=self.remember_direct_var).grid(row=0, column=1, sticky="e")
        self.direct_input = scrolledtext.ScrolledText(inputs, height=12, wrap="word", undo=True)
        self.direct_input.grid(row=3, column=0, sticky="nsew")

        self.results_panel = RecentResultsPanel(
            left,
            max_entries=int(self.config["result_browser"]["max_entries"]),
        )
        self.results_panel.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        backend = ttk.LabelFrame(right, text="后端", padding=8)
        backend.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        backend.columnconfigure(1, weight=1)
        ttk.Label(backend, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(backend, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(backend, text="刷新模型", command=self.refresh_models).grid(row=0, column=2, sticky="ew")
        self.unload_button = ttk.Button(backend, text="卸载全部模型", command=self.unload_all)
        self.unload_button.grid(row=0, column=3, sticky="ew", padx=(6, 0))
        if not self.config["router"].get("control_enabled", True):
            self.unload_button.configure(state="disabled")

        models_area = ttk.LabelFrame(right, text="模型选择", padding=6)
        models_area.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        models_area.columnconfigure(0, weight=1)
        models_area.rowconfigure(0, weight=1)
        grouping = self.config.get("model_source", {}).get("grouping", {})
        self.model_selector = ModelSelector(
            models_area,
            grouping,
            selected_models=self.state.get("selected_models", []),
            filter_text=str(self.state.get("model_filter", "")),
            collapsed_families=self.state.get("collapsed_model_groups", []),
            collapsed_tiers=self.state.get("collapsed_model_tiers", []),
        )
        self.model_selector.grid(row=0, column=0, sticky="nsew")

        selected_gpu = self.state.get("selected_gpu_index")
        self.gpu_panel = GpuMonitorPanel(
            right,
            history_samples=int(self.gpu_monitor_config["history_samples"]),
            selected_index=int(selected_gpu) if isinstance(selected_gpu, int) and not isinstance(selected_gpu, bool) else None,
        )
        self.gpu_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        if not self.gpu_monitor_config["enabled"]:
            self.gpu_panel.set_disabled()

        run_area = ttk.LabelFrame(right, text="运行状态", padding=8)
        run_area.grid(row=3, column=0, sticky="nsew")
        run_area.columnconfigure(0, weight=1)
        run_area.rowconfigure(3, weight=1)
        actions = ttk.Frame(run_area)
        actions.grid(row=0, column=0, sticky="ew")
        actions.columnconfigure(3, weight=1)
        self.start_button = ttk.Button(actions, text="开始生成", command=lambda: self.start_run(False))
        self.start_button.grid(row=0, column=0, padx=(0, 5))
        self.validate_button = ttk.Button(actions, text="仅验证", command=lambda: self.start_run(True))
        self.validate_button.grid(row=0, column=1, padx=(0, 5))
        self.cancel_button = ttk.Button(actions, text="取消", command=self.cancel_run, state="disabled")
        self.cancel_button.grid(row=0, column=2)
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=3, sticky="e")
        self.progress = ttk.Progressbar(run_area, mode="determinate", maximum=1, value=0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(run_area, textvariable=self.progress_detail_var).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.log = scrolledtext.ScrolledText(run_area, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=3, column=0, sticky="nsew")

    def _profile_display(self, profile_id: str) -> str:
        payload = self.profiles.get(profile_id, next(iter(self.profiles.values())))[1]
        actual_id = str(payload["id"])
        return f"{actual_id} — {payload.get('display_name', actual_id)}"

    def _on_profile_selected(self, _event=None) -> None:
        profile_id = self.profile_combo.get().split(" — ", 1)[0]
        if profile_id in self.profiles:
            self.profile_var.set(profile_id)
            self._apply_profile_modes()

    def _reload_profiles(self) -> None:
        try:
            self.profiles = self._load_profiles(self.paths["profiles"])
            self.profile_combo.configure(values=[self._profile_display(pid) for pid in self.profiles])
            if self.profile_var.get() not in self.profiles:
                self.profile_var.set(next(iter(self.profiles)))
            self.profile_combo.set(self._profile_display(self.profile_var.get()))
            self._apply_profile_modes()
            self._append_log("> Profile 已重新读取。\n")
        except Exception as exc:
            messagebox.showerror("Profile 错误", str(exc), parent=self.root)

    def _apply_profile_modes(self) -> None:
        _, profile = self.profiles[self.profile_var.get()]
        modes = list(profile["modes"].keys())
        values = (["auto"] if profile.get("allow_auto_mode", False) else []) + modes
        self.mode_combo.configure(values=values)
        if self.mode_var.get() not in values:
            self.mode_var.set("auto" if "auto" in values else str(profile.get("default_mode", modes[0])))

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar, command, suffix: str = "") -> int:
        ttk.Label(parent, text=f"{label}（{suffix}）" if suffix else label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(parent, text="浏览…", command=command).grid(row=row, column=2, sticky="ew", pady=3)
        return row + 1

    def _browse_system_prompt(self) -> None:
        path = filedialog.askopenfilename(title="选择 System Prompt", filetypes=(("Text", "*.md *.txt"), ("All files", "*.*")))
        if path:
            self.system_prompt_var.set(path)

    def _browse_dir(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory(title="选择目录", initialdir=variable.get() or str(PROJECT_ROOT))
        if path:
            variable.set(path)

    def _current_output_root(self) -> Path:
        value = self.output_root_var.get().strip()
        return expand_path(value, PROJECT_ROOT) if value else self.paths["default_output_root"]

    def _schedule_results_refresh(self) -> None:
        if self.result_refresh_after is not None:
            self.root.after_cancel(self.result_refresh_after)
        self.result_refresh_after = self.root.after(500, self._refresh_results)

    def _refresh_results(self) -> None:
        self.result_refresh_after = None
        self.results_panel.refresh(self._current_output_root())

    def _add_input_files(self) -> None:
        paths = filedialog.askopenfilenames(title="添加输入文件", filetypes=(("Text", "*.txt *.md"), ("All files", "*.*")))
        existing = [line.strip() for line in self.input_files.get("1.0", "end-1c").splitlines() if line.strip()]
        for path in paths:
            if path not in existing:
                existing.append(path)
        self.input_files.delete("1.0", "end")
        self.input_files.insert("1.0", "\n".join(existing))

    def _restore_inputs(self) -> None:
        self.input_files.insert("1.0", "\n".join(self.state.get("input_files", [])))
        if self.remember_direct_var.get():
            self.direct_input.insert("1.0", self.state.get("direct_input", ""))

    def refresh_models(self) -> None:
        self.model_selector.set_loading()
        base_url = self.base_url_var.get().strip()
        model_config = self.paths["model_config"]
        fallback_format = self.config.get("model_source", {}).get("fallback_format")

        def worker() -> None:
            self.events.put(("models", discover_models(base_url, self.config["backend"], model_config, fallback_format)))
        threading.Thread(target=worker, daemon=True).start()

    def unload_all(self) -> None:
        if self.process is not None or self.unload_in_progress or not self.config["router"].get("control_enabled", True):
            return
        if not messagebox.askyesno(
            "卸载全部模型",
            f"将通过 {self.config['router']['control_base_url']} 的 llama-swap 卸载全部模型。继续？",
            parent=self.root,
        ):
            return
        self.unload_in_progress = True
        self.start_button.configure(state="disabled")
        self.validate_button.configure(state="disabled")
        self.unload_button.configure(state="disabled")
        self.status_var.set("正在卸载模型")
        self._append_log("\n> 请求 llama-swap 卸载全部模型。\n")

        def worker() -> None:
            try:
                result = unload_all_models(self.config["router"], self.config["router"].get("auth", {"type": "none"}))
            except Exception as exc:
                self.events.put(("unload_error", str(exc)))
            else:
                self.events.put(("unload_finished", result))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_gpu_poll(self) -> None:
        if self.closing or self.gpu_poll_pending or not self.gpu_monitor_config["enabled"]:
            return
        self.gpu_poll_pending = True

        def worker() -> None:
            try:
                snapshots = query_nvidia_gpus(
                    str(self.gpu_monitor_config["command"]),
                    float(self.gpu_monitor_config["query_timeout_seconds"]),
                )
            except Exception as exc:
                self.events.put(("gpu_error", str(exc)))
            else:
                self.events.put(("gpu_snapshots", snapshots))

        threading.Thread(target=worker, daemon=True).start()

    def _queue_next_gpu_poll(self, *, after_error: bool = False) -> None:
        self.gpu_poll_pending = False
        interval = int(self.gpu_monitor_config["poll_interval_ms"])
        if after_error:
            interval = max(interval, 5000)
        if not self.closing:
            self.root.after(interval, self._schedule_gpu_poll)

    @staticmethod
    def _positive_int(value: str, label: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{label} 必须是整数") from exc
        if parsed < 1:
            raise ValueError(f"{label} 必须大于 0")
        return parsed

    def _create_manifest(self) -> Path:
        inputs: list[dict[str, str]] = []
        seen: set[Path] = set()
        for line in self.input_files.get("1.0", "end-1c").splitlines():
            value = line.strip().strip('"')
            if not value:
                continue
            path = Path(value).resolve()
            if not path.is_file():
                raise ValueError(f"输入文件不存在：{path}")
            if path not in seen:
                inputs.append({"id": path.stem, "path": str(path)})
                seen.add(path)
        direct = self.direct_input.get("1.0", "end-1c")
        if direct.strip():
            inputs.append({"id": "direct-input", "content": direct})
        if not inputs:
            raise ValueError("至少添加一个输入文件，或填写直接输入")
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", prefix="prompt-batch-", delete=False)
        try:
            json.dump({"inputs": inputs}, handle, ensure_ascii=False, indent=2)
            return Path(handle.name)
        finally:
            handle.close()

    def _update_seed_controls(self) -> None:
        self.seed_base_entry.configure(state="disabled" if self.random_seed_var.get() else "normal")

    def _build_command(self, validate_only: bool) -> list[str]:
        selected = self.model_selector.selected_ids()
        if not selected:
            raise ValueError("至少选择一个模型")
        repeats = self._positive_int(self.repeats_var.get().strip(), "Repeats")
        max_tokens = self._positive_int(self.max_tokens_var.get().strip(), "Max tokens")
        seed_base: int | None = None
        if not self.random_seed_var.get():
            seed_base = self._positive_int(self.seed_base_var.get().strip(), "Seed base")
            if seed_base > 2_147_483_647 - repeats:
                raise ValueError("Seed base 超出 Int32 范围")
        self.temp_manifest = self._create_manifest()
        profile_path = self.profiles[self.profile_var.get()][0]
        command = [*engine_command(self.paths["engine"]),
                   "--app-config", str(self.config_path), "--profile", str(profile_path),
                   "--input-manifest", str(self.temp_manifest), "--mode", self.mode_var.get(),
                   "--base-url", self.base_url_var.get().strip(), "--repeats", str(repeats), "--max-tokens", str(max_tokens),
                   "--event-format", "jsonl"]
        if self.random_seed_var.get():
            command.append("--random-seed")
        else:
            command.extend(("--no-random-seed", "--seed-base", str(seed_base)))
        for model_id in selected:
            command.extend(("--model", model_id))
        for flag, value in (("--output-root", self.output_root_var.get().strip()), ("--run-directory", self.run_directory_var.get().strip()),
                            ("--system-prompt", self.system_prompt_var.get().strip())):
            if value:
                command.extend((flag, value))
        if validate_only:
            command.append("--validate-only")
        else:
            strategy = RUN_STRATEGY_KEYS.get(self.run_strategy_var.get(), "new")
            if strategy != "new" and not self.run_directory_var.get().strip():
                raise ValueError("续跑或仅重试失败时必须指定固定运行目录")
            if strategy == "resume":
                command.append("--resume")
            elif strategy == "retry-failed":
                command.append("--retry-failed")
        return command

    def start_run(self, validate_only: bool) -> None:
        if self.process is not None:
            return
        try:
            command = self._build_command(validate_only)
            self._save_state()
        except Exception as exc:
            self._cleanup_manifest()
            messagebox.showerror("参数错误", str(exc), parent=self.root)
            return
        self._append_log("\n> " + ("开始验证。\n" if validate_only else "开始生成；顺序为 model → repeat → input。\n"))
        self.status_var.set("运行中")
        self.progress.configure(maximum=1, value=0)
        self.progress_detail_var.set("正在准备批次")
        self.start_button.configure(state="disabled")
        self.validate_button.configure(state="disabled")
        self.unload_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        def worker() -> None:
            try:
                self.process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        self.events.put(("log", line))
                    else:
                        if isinstance(payload, dict) and payload.get("type"):
                            self.events.put(("engine", payload))
                        else:
                            self.events.put(("log", line))
                self.events.put(("finished", self.process.wait()))
            except Exception as exc:
                self.events.put(("error", f"启动失败：{exc}"))
                self.events.put(("finished", -1))
        threading.Thread(target=worker, daemon=True).start()

    def cancel_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._terminate_tree()
            self.status_var.set("正在取消")
            self.progress_detail_var.set("正在终止当前进程；已完成结果会保留")

    def _terminate_tree(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        terminate_process_tree(self.process)

    def _save_state(self) -> None:
        direct = self.direct_input.get("1.0", "end-1c") if self.remember_direct_var.get() else ""
        state = {"schema_version": 1, "geometry": self.root.geometry(), "profile": self.profile_var.get(), "mode": self.mode_var.get(),
                 "output_root": self.output_root_var.get().strip(), "run_directory": self.run_directory_var.get().strip(),
                 "system_prompt": self.system_prompt_var.get().strip(), "repeats": self._positive_int(self.repeats_var.get(), "Repeats"),
                 "max_tokens": self._positive_int(self.max_tokens_var.get(), "Max tokens"), "seed_base": self._positive_int(self.seed_base_var.get(), "Seed base"),
                 "random_seed": self.random_seed_var.get(),
                 "run_strategy": RUN_STRATEGY_KEYS.get(self.run_strategy_var.get(), "new"),
                 "base_url": self.base_url_var.get().strip(), "input_files": [line.strip() for line in self.input_files.get("1.0", "end-1c").splitlines() if line.strip()],
                 "remember_direct_input": self.remember_direct_var.get(), "direct_input": direct,
                 "selected_gpu_index": self.gpu_panel.selected_index()}
        state.update(self.model_selector.state_payload())
        atomic_write_json(self.paths["state"], state)

    def _cleanup_manifest(self) -> None:
        if self.temp_manifest:
            try:
                self.temp_manifest.unlink(missing_ok=True)
            except OSError:
                pass
            self.temp_manifest = None

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _handle_engine_event(self, payload: dict) -> None:
        event_type = str(payload.get("type", ""))
        if event_type == "log":
            self._append_log(str(payload.get("message", "")) + "\n")
        elif event_type == "batch_started":
            total = max(1, int(payload.get("total", 1)))
            planned = int(payload.get("planned", total))
            self.progress.configure(maximum=total, value=0)
            self.progress_detail_var.set(f"共 {total} 项，本次需要请求 {planned} 项")
        elif event_type == "model_started":
            self.status_var.set(f"模型 {payload.get('index')}/{payload.get('total_models')}")
        elif event_type == "item_started":
            self.progress_detail_var.set(
                f"正在生成：{payload.get('model')} / {payload.get('input')} / 第 {payload.get('repeat')} 次"
            )
        elif event_type == "item_finished":
            completed = int(payload.get("completed", 0))
            total = max(1, int(payload.get("total", 1)))
            self.progress.configure(maximum=total, value=completed)
            status_labels = {"success": "完成", "failed": "失败", "skipped": "已跳过"}
            status = status_labels.get(str(payload.get("status")), str(payload.get("status", "")))
            self.progress_detail_var.set(
                f"{completed}/{total} · {status} · {payload.get('model')} / {payload.get('input')} / 第 {payload.get('repeat')} 次"
            )
        elif event_type == "batch_finished":
            total = max(1, int(payload.get("total", 1)))
            self.progress.configure(maximum=total, value=int(payload.get("completed", total)))
            self.progress_detail_var.set(
                f"批次结束：执行 {payload.get('executed', 0)}，跳过 {payload.get('skipped', 0)}，失败 {payload.get('failures', 0)}"
            )
            self.root.after(50, self._refresh_results)
        elif event_type == "validation_finished":
            self.progress.configure(maximum=1, value=1)
            self.progress_detail_var.set(
                f"验证通过：{payload.get('models', 0)} 个模型，{payload.get('inputs', 0)} 条输入"
            )
        elif event_type in {"batch_failed", "error"}:
            message = str(payload.get("error") or payload.get("message") or "未知错误")
            self.progress_detail_var.set(f"失败：{message}")
            self._append_log(f"\n! {message}\n")

    def _drain_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "models":
                    self.model_selector.load_models(*value)
                elif event == "gpu_snapshots":
                    self.gpu_panel.update_snapshots(value)
                    self._queue_next_gpu_poll()
                elif event == "gpu_error":
                    self.gpu_panel.show_error(str(value))
                    self._queue_next_gpu_poll(after_error=True)
                elif event == "unload_finished":
                    self.unload_in_progress = False
                    self.start_button.configure(state="normal")
                    self.validate_button.configure(state="normal")
                    self.unload_button.configure(state="normal" if self.config["router"].get("control_enabled", True) else "disabled")
                    self.status_var.set("模型已卸载")
                    response_text = getattr(value, "response_text", "")
                    suffix = f"：{response_text}" if response_text else ""
                    self._append_log(f"> llama-swap 已完成卸载{suffix}\n")
                elif event == "unload_error":
                    self.unload_in_progress = False
                    self.start_button.configure(state="normal")
                    self.validate_button.configure(state="normal")
                    self.unload_button.configure(state="normal" if self.config["router"].get("control_enabled", True) else "disabled")
                    self.status_var.set("卸载失败")
                    self._append_log(f"! {value}\n")
                    messagebox.showerror("卸载失败", str(value), parent=self.root)
                elif event == "log":
                    self._append_log(str(value))
                elif event == "engine":
                    self._handle_engine_event(value)
                elif event == "error":
                    self._append_log(f"\n! {value}\n")
                elif event == "finished":
                    code = int(value)
                    self.process = None
                    self._cleanup_manifest()
                    self.start_button.configure(state="normal")
                    self.validate_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.unload_button.configure(state="normal" if self.config["router"].get("control_enabled", True) else "disabled")
                    self.status_var.set("完成" if code == 0 else f"失败（exit {code}）")
                    self._append_log(f"\n> 进程结束，exit code {code}\n")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _on_close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno("仍在运行", "任务仍在运行。终止并关闭？", parent=self.root):
                return
            self._terminate_tree()
        try:
            self._save_state()
        except Exception as exc:
            if not messagebox.askyesno("状态保存失败", f"{exc}\n\n仍然关闭？", parent=self.root):
                return
        self.closing = True
        self._cleanup_manifest()
        self.root.destroy()


def self_test(config_path: Path) -> int:
    config = load_app_config(config_path)
    paths = resolve_config_paths(config, config_path)
    profiles = PromptBatchApp._load_profiles(paths["profiles"])
    models = parse_llama_swap_models(paths["model_config"])
    grouping = config.get("model_source", {}).get("grouping", {})
    groups = group_model_families(list(models.items()), grouping)
    tiering = grouping.get("parameter_tiers", {})
    result = {"config": str(config_path), "engine_exists": paths["engine"].is_file(), "profiles": list(profiles),
              "app_schema_version": config["schema_version"], "backend_adapter": config["backend"]["adapter"],
              "profile_schema_versions": {profile_id: payload["schema_version"] for profile_id, (_path, payload) in profiles.items()},
              "model_config_exists": paths["model_config"].exists(), "config_model_count": len(models),
              "model_groups": [{"key": group.key, "label": group.label, "count": len(group.models),
                                "parameter_tiers": [{"key": tier.key, "label": tier.label, "count": len(tier.models)}
                                                    for tier in group_parameter_tiers(list(group.models), tiering)]}
                               for group in groups],
              "gpu_monitor_enabled": config["gpu_monitor"]["enabled"],
              "state_path": str(paths["state"]), "python": sys.executable, "tk_version": tk.TkVersion}
    if sys.stdout is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    # A local model registry is optional for API-only deployments.
    registry_ok = not result["model_config_exists"] or bool(models and groups)
    return 0 if result["engine_exists"] and profiles and registry_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.self_test:
        return self_test(config_path)
    root = tk.Tk()
    PromptBatchApp(root, config_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
