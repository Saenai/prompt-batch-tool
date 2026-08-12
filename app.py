from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from prompt_batch.config import load_json, resolve_config_paths
from prompt_batch.model_source import (
    ModelGroup,
    ModelTier,
    discover_models,
    group_model_tiers,
    group_models,
    parse_llama_swap_models,
)


APP_DIR = Path(__file__).resolve().parent
RUN_STRATEGY_LABELS = {
    "new": "新运行",
    "resume": "续跑未完成",
    "retry-failed": "仅重试失败",
}
RUN_STRATEGY_KEYS = {label: key for key, label in RUN_STRATEGY_LABELS.items()}


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class BatchApp:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path.resolve()
        self.config_dir = self.config_path.parent
        self.config = load_json(self.config_path)
        self.paths = resolve_config_paths(self.config, self.config_path)
        self.profiles = self._load_profiles(self.paths["profiles"])
        self.state = self._load_state()
        defaults = self.config.get("defaults", {})

        self.process: subprocess.Popen[str] | None = None
        self.temp_manifest: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.model_vars: dict[str, tk.BooleanVar] = {}
        self.model_labels: dict[str, str] = {}
        self.model_groups: list[ModelGroup] = []
        self.model_tiers: dict[str, list[ModelTier]] = {}
        self.group_counter_vars: dict[str, tk.StringVar] = {}
        self.tier_counter_vars: dict[str, tk.StringVar] = {}
        self.collapsed_model_groups = {
            str(value) for value in self.state.get("collapsed_model_groups", [])
        }
        self.collapsed_model_tiers = {
            str(value) for value in self.state.get("collapsed_model_tiers", [])
        }
        self.pending_models = set(self.state.get("selected_models", []))

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
        self.base_url_var = tk.StringVar(value=self.state.get("base_url", self.config["backend"]["base_url"]))
        self.filter_var = tk.StringVar(value=self.state.get("model_filter", ""))
        self.remember_direct_var = tk.BooleanVar(value=bool(self.state.get("remember_direct_input", defaults.get("remember_direct_input", False))))
        strategy_key = str(self.state.get("run_strategy", "new"))
        self.run_strategy_var = tk.StringVar(value=RUN_STRATEGY_LABELS.get(strategy_key, RUN_STRATEGY_LABELS["new"]))
        self.status_var = tk.StringVar(value="就绪")
        self.progress_detail_var = tk.StringVar(value="尚未开始")
        self.model_source_var = tk.StringVar(value="模型：尚未加载")

        self.root.title(self.config.get("app", {}).get("title", "Prompt Batch Generator"))
        self.root.geometry(self.state.get("geometry", "1280x820"))
        self.root.minsize(1050, 680)
        self._build_ui()
        self.root.after(60, self._restore_pane_sash)
        self._restore_inputs()
        self._apply_profile_modes()
        self.filter_var.trace_add("write", lambda *_: self._render_models())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._drain_events)
        self.root.after(150, self.refresh_models)

    @staticmethod
    def _load_profiles(directory: Path) -> dict[str, tuple[Path, dict]]:
        profiles: dict[str, tuple[Path, dict]] = {}
        for path in sorted(directory.glob("*.json")):
            payload = load_json(path)
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
        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.main_paned = paned

        left = ttk.LabelFrame(paned, text="任务与输入", padding=8)
        right = ttk.LabelFrame(paned, text="模型与执行", padding=8)
        paned.add(left, weight=1)
        paned.add(right, weight=1)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(2, weight=2)

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
        ttk.Entry(params, textvariable=self.seed_base_var, width=12).grid(row=1, column=3, sticky="ew", padx=(5, 0), pady=2)
        ttk.Label(params, text="运行策略").grid(row=2, column=0, sticky="w")
        self.run_strategy_combo = ttk.Combobox(
            params,
            textvariable=self.run_strategy_var,
            values=list(RUN_STRATEGY_LABELS.values()),
            state="readonly",
        )
        self.run_strategy_combo.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(5, 0), pady=2)
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

        backend = ttk.LabelFrame(right, text="后端", padding=8)
        backend.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        backend.columnconfigure(1, weight=1)
        ttk.Label(backend, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(backend, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(backend, text="刷新模型", command=self.refresh_models).grid(row=0, column=2, sticky="ew")

        models_area = ttk.LabelFrame(right, text="模型选择", padding=6)
        models_area.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        models_area.columnconfigure(0, weight=1)
        models_area.rowconfigure(1, weight=1)
        model_header = ttk.Frame(models_area)
        model_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        model_header.columnconfigure(1, weight=1)
        ttk.Label(model_header, textvariable=self.model_source_var).grid(row=0, column=0, sticky="w")
        ttk.Entry(model_header, textvariable=self.filter_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(model_header, text="全选", command=lambda: self._set_visible_models(True)).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(model_header, text="清空", command=lambda: self._set_visible_models(False)).grid(row=0, column=3)

        model_box = ttk.Frame(models_area, relief="sunken", borderwidth=1)
        model_box.grid(row=1, column=0, sticky="nsew")
        model_box.rowconfigure(0, weight=1)
        model_box.columnconfigure(0, weight=1)
        self.model_canvas = tk.Canvas(model_box, highlightthickness=0)
        scrollbar = ttk.Scrollbar(model_box, orient="vertical", command=self.model_canvas.yview)
        self.model_canvas.configure(yscrollcommand=scrollbar.set)
        self.model_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.model_inner = ttk.Frame(self.model_canvas)
        self.model_window = self.model_canvas.create_window((0, 0), window=self.model_inner, anchor="nw")
        self.model_inner.bind("<Configure>", lambda _event: self.model_canvas.configure(scrollregion=self.model_canvas.bbox("all")))
        self.model_canvas.bind("<Configure>", lambda event: self.model_canvas.itemconfigure(self.model_window, width=event.width))
        self._bind_model_wheel(self.model_canvas)
        self._bind_model_wheel(self.model_inner)

        run_area = ttk.LabelFrame(right, text="运行状态", padding=8)
        run_area.grid(row=2, column=0, sticky="nsew")
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
        path = filedialog.askdirectory(title="选择目录", initialdir=variable.get() or str(APP_DIR))
        if path:
            variable.set(path)

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

    def _restore_pane_sash(self) -> None:
        try:
            position = int(self.state.get("pane_sash", 0))
            if position > 0:
                self.main_paned.sashpos(0, position)
        except (tk.TclError, TypeError, ValueError):
            pass

    def refresh_models(self) -> None:
        self.model_source_var.set("模型：加载中…")
        base_url = self.base_url_var.get().strip()
        endpoint = self.config["backend"]["models_endpoint"]
        model_config = self.paths["model_config"]
        fallback_format = self.config.get("model_source", {}).get("fallback_format")

        def worker() -> None:
            self.events.put(("models", discover_models(base_url, endpoint, model_config, fallback_format)))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_models(self, models: list[tuple[str, str]], source: str) -> None:
        selected = {mid for mid, var in self.model_vars.items() if var.get()} | self.pending_models
        self.pending_models.clear()
        self.model_labels = dict(models)
        self.model_vars = {mid: tk.BooleanVar(value=mid in selected) for mid, _ in models}
        grouping = self.config.get("model_source", {}).get("grouping", {})
        self.model_groups = group_models(models, grouping)
        tiering = grouping.get("parameter_tiers", {})
        self.model_tiers = {
            group.key: group_model_tiers(list(group.models), tiering)
            for group in self.model_groups
        }
        self.model_source_var.set(f"模型：{len(models)} 个（{source}）")
        self._render_models()

    def _visible_model_ids(self) -> list[str]:
        needle = self.filter_var.get().strip().casefold()
        return [mid for mid, label in self.model_labels.items() if not needle or needle in mid.casefold() or needle in label.casefold()]

    def _render_models(self) -> None:
        for child in self.model_inner.winfo_children():
            child.destroy()
        self.group_counter_vars.clear()
        self.tier_counter_vars.clear()
        visible = set(self._visible_model_ids())
        filtering = bool(self.filter_var.get().strip())
        if not visible:
            empty_label = ttk.Label(self.model_inner, text="没有匹配的模型")
            empty_label.pack(anchor="w", padx=8, pady=8)
            self._bind_model_wheel(empty_label)
            return

        for group in self.model_groups:
            group_visible = [mid for mid, _label in group.models if mid in visible]
            if not group_visible:
                continue
            collapsed = group.key in self.collapsed_model_groups and not filtering
            header = ttk.Frame(self.model_inner)
            header.pack(fill="x", padx=5, pady=(5, 1))
            header.columnconfigure(1, weight=1)
            toggle = ttk.Button(
                header,
                text="▶" if collapsed else "▼",
                width=2,
                command=lambda key=group.key: self._toggle_model_group(key),
            )
            toggle.grid(row=0, column=0, sticky="w")
            counter = tk.StringVar()
            self.group_counter_vars[group.key] = counter
            group_label = ttk.Label(header, textvariable=counter)
            group_label.grid(row=0, column=1, sticky="w", padx=(5, 8))
            select_button = ttk.Button(
                header,
                text="全选",
                width=5,
                command=lambda key=group.key: self._set_group_models(key, True),
            )
            select_button.grid(row=0, column=2, padx=(0, 3))
            clear_button = ttk.Button(
                header,
                text="清空",
                width=5,
                command=lambda key=group.key: self._set_group_models(key, False),
            )
            clear_button.grid(row=0, column=3)
            for widget in (header, toggle, group_label, select_button, clear_button):
                self._bind_model_wheel(widget)

            if not collapsed:
                for tier in self.model_tiers.get(group.key, []):
                    tier_visible = [mid for mid, _label in tier.models if mid in visible]
                    if not tier_visible:
                        continue
                    tier_state_key = self._tier_state_key(group.key, tier.key)
                    tier_collapsed = tier_state_key in self.collapsed_model_tiers and not filtering
                    tier_header = ttk.Frame(self.model_inner)
                    tier_header.pack(fill="x", padx=(28, 5), pady=(2, 0))
                    tier_header.columnconfigure(1, weight=1)
                    tier_toggle = ttk.Button(
                        tier_header,
                        text="▶" if tier_collapsed else "▼",
                        width=2,
                        command=lambda key=tier_state_key: self._toggle_model_tier(key),
                    )
                    tier_toggle.grid(row=0, column=0, sticky="w")
                    tier_counter = tk.StringVar()
                    self.tier_counter_vars[tier_state_key] = tier_counter
                    tier_label = ttk.Label(tier_header, textvariable=tier_counter)
                    tier_label.grid(row=0, column=1, sticky="w", padx=(5, 8))
                    tier_select = ttk.Button(
                        tier_header,
                        text="全选",
                        width=5,
                        command=lambda g=group.key, t=tier.key: self._set_tier_models(g, t, True),
                    )
                    tier_select.grid(row=0, column=2, padx=(0, 3))
                    tier_clear = ttk.Button(
                        tier_header,
                        text="清空",
                        width=5,
                        command=lambda g=group.key, t=tier.key: self._set_tier_models(g, t, False),
                    )
                    tier_clear.grid(row=0, column=3)
                    for widget in (tier_header, tier_toggle, tier_label, tier_select, tier_clear):
                        self._bind_model_wheel(widget)

                    if not tier_collapsed:
                        for mid in tier_visible:
                            label = self.model_labels[mid]
                            text = mid if label == mid else f"{mid}  —  {label}"
                            checkbutton = ttk.Checkbutton(
                                self.model_inner,
                                text=text,
                                variable=self.model_vars[mid],
                                command=self._refresh_model_counters,
                            )
                            checkbutton.pack(anchor="w", fill="x", padx=(52, 8), pady=1)
                            self._bind_model_wheel(checkbutton)
        self._refresh_model_counters()

    def _refresh_model_counters(self) -> None:
        for group in self.model_groups:
            counter = self.group_counter_vars.get(group.key)
            if counter is not None:
                selected = sum(bool(self.model_vars[mid].get()) for mid, _label in group.models)
                counter.set(f"{group.label}（已选 {selected}/{len(group.models)}）")
            for tier in self.model_tiers.get(group.key, []):
                tier_counter = self.tier_counter_vars.get(self._tier_state_key(group.key, tier.key))
                if tier_counter is not None:
                    selected = sum(bool(self.model_vars[mid].get()) for mid, _label in tier.models)
                    tier_counter.set(f"{tier.label}（已选 {selected}/{len(tier.models)}）")

    def _toggle_model_group(self, group_key: str) -> None:
        if group_key in self.collapsed_model_groups:
            self.collapsed_model_groups.remove(group_key)
        else:
            self.collapsed_model_groups.add(group_key)
        self._render_models()

    def _set_group_models(self, group_key: str, value: bool) -> None:
        visible = set(self._visible_model_ids())
        for group in self.model_groups:
            if group.key == group_key:
                for mid, _label in group.models:
                    if mid in visible:
                        self.model_vars[mid].set(value)
                break
        self._refresh_model_counters()

    @staticmethod
    def _tier_state_key(group_key: str, tier_key: str) -> str:
        return f"{group_key}/{tier_key}"

    def _toggle_model_tier(self, tier_state_key: str) -> None:
        if tier_state_key in self.collapsed_model_tiers:
            self.collapsed_model_tiers.remove(tier_state_key)
        else:
            self.collapsed_model_tiers.add(tier_state_key)
        self._render_models()

    def _set_tier_models(self, group_key: str, tier_key: str, value: bool) -> None:
        visible = set(self._visible_model_ids())
        for tier in self.model_tiers.get(group_key, []):
            if tier.key == tier_key:
                for mid, _label in tier.models:
                    if mid in visible:
                        self.model_vars[mid].set(value)
                break
        self._refresh_model_counters()

    def _bind_model_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll_model_list)
        widget.bind("<Button-4>", self._scroll_model_list)
        widget.bind("<Button-5>", self._scroll_model_list)

    def _scroll_model_list(self, event: tk.Event) -> str | None:
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return None
            magnitude = max(1, abs(delta) // 120)
            units = -magnitude if delta > 0 else magnitude
        self.model_canvas.yview_scroll(units, "units")
        return "break"

    def _set_visible_models(self, value: bool) -> None:
        for mid in self._visible_model_ids():
            self.model_vars[mid].set(value)
        self._refresh_model_counters()

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

    def _build_command(self, validate_only: bool) -> list[str]:
        selected = [mid for mid, var in self.model_vars.items() if var.get()]
        if not selected:
            raise ValueError("至少选择一个模型")
        repeats = self._positive_int(self.repeats_var.get().strip(), "Repeats")
        max_tokens = self._positive_int(self.max_tokens_var.get().strip(), "Max tokens")
        seed_base = self._positive_int(self.seed_base_var.get().strip(), "Seed base")
        if seed_base > 2_147_483_647 - repeats:
            raise ValueError("Seed base 超出 Int32 范围")
        self.temp_manifest = self._create_manifest()
        profile_path = self.profiles[self.profile_var.get()][0]
        command = [sys.executable, "-B", str(self.paths["engine"]),
                   "--app-config", str(self.config_path), "--profile", str(profile_path),
                   "--input-manifest", str(self.temp_manifest), "--mode", self.mode_var.get(),
                   "--base-url", self.base_url_var.get().strip(), "--repeats", str(repeats), "--max-tokens", str(max_tokens),
                   "--seed-base", str(seed_base), "--event-format", "jsonl"]
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
        self.cancel_button.configure(state="normal")

        def worker() -> None:
            try:
                self.process = subprocess.Popen(command, cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        system_root = os.environ.get("SystemRoot")
        taskkill = (Path(system_root) / "System32" / "taskkill.exe") if system_root else None
        if taskkill and taskkill.is_file():
            subprocess.run([str(taskkill), "/PID", str(self.process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            self.process.terminate()

    def _save_state(self) -> None:
        direct = self.direct_input.get("1.0", "end-1c") if self.remember_direct_var.get() else ""
        try:
            pane_sash = self.main_paned.sashpos(0)
        except tk.TclError:
            pane_sash = 0
        state = {"schema_version": 1, "geometry": self.root.geometry(), "profile": self.profile_var.get(), "mode": self.mode_var.get(),
                 "pane_sash": pane_sash,
                 "output_root": self.output_root_var.get().strip(), "run_directory": self.run_directory_var.get().strip(),
                 "system_prompt": self.system_prompt_var.get().strip(), "repeats": self._positive_int(self.repeats_var.get(), "Repeats"),
                 "max_tokens": self._positive_int(self.max_tokens_var.get(), "Max tokens"), "seed_base": self._positive_int(self.seed_base_var.get(), "Seed base"),
                 "run_strategy": RUN_STRATEGY_KEYS.get(self.run_strategy_var.get(), "new"),
                 "base_url": self.base_url_var.get().strip(), "input_files": [line.strip() for line in self.input_files.get("1.0", "end-1c").splitlines() if line.strip()],
                 "selected_models": [mid for mid, var in self.model_vars.items() if var.get()], "model_filter": self.filter_var.get(),
                 "collapsed_model_groups": sorted(self.collapsed_model_groups),
                 "collapsed_model_tiers": sorted(self.collapsed_model_tiers),
                 "remember_direct_input": self.remember_direct_var.get(), "direct_input": direct}
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
                    self._apply_models(*value)
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
        self._cleanup_manifest()
        self.root.destroy()


def self_test(config_path: Path) -> int:
    config = load_json(config_path)
    paths = resolve_config_paths(config, config_path)
    profiles = BatchApp._load_profiles(paths["profiles"])
    models = parse_llama_swap_models(paths["model_config"])
    grouping = config.get("model_source", {}).get("grouping", {})
    groups = group_models(list(models.items()), grouping)
    tiering = grouping.get("parameter_tiers", {})
    result = {"config": str(config_path), "engine_exists": paths["engine"].is_file(), "profiles": list(profiles),
              "model_config_exists": paths["model_config"].is_file(), "config_model_count": len(models),
              "model_groups": [{"key": group.key, "label": group.label, "count": len(group.models),
                                "parameter_tiers": [{"key": tier.key, "label": tier.label, "count": len(tier.models)}
                                                    for tier in group_model_tiers(list(group.models), tiering)]}
                               for group in groups],
              "state_path": str(paths["state"]), "python": sys.executable, "tk_version": tk.TkVersion}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["engine_exists"] and profiles and models and groups else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.self_test:
        return self_test(config_path)
    root = tk.Tk()
    BatchApp(root, config_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
