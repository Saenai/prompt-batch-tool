from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from .result_catalog import RecentRun, scan_recent_runs


STATUS_LABELS = {
    "completed": "完成",
    "completed_with_failures": "部分失败",
    "interrupted": "中断",
}


def open_local_path(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"路径不存在：{resolved}")
    if hasattr(os, "startfile"):
        os.startfile(str(resolved))  # type: ignore[attr-defined]
        return
    command = ["open", str(resolved)] if sys.platform == "darwin" else ["xdg-open", str(resolved)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class RecentResultsPanel(ttk.LabelFrame):
    def __init__(self, parent, max_entries: int) -> None:
        super().__init__(parent, text="近期结果", padding=8)
        self.max_entries = max_entries
        self.entries: list[RecentRun] = []
        self.status_var = tk.StringVar(value="尚未扫描输出目录")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        columns = ("time", "status", "run")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=4, selectmode="browse")
        self.tree.heading("time", text="时间")
        self.tree.heading("status", text="状态")
        self.tree.heading("run", text="任务目录")
        self.tree.column("time", width=126, stretch=False)
        self.tree.column("status", width=72, stretch=False)
        self.tree.column("run", width=300, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", lambda _event: self.open_aggregate())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_buttons())

        footer = ttk.Frame(self)
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.open_button = ttk.Button(footer, text="打开聚合结果", command=self.open_aggregate, state="disabled")
        self.open_button.grid(row=0, column=1, padx=(6, 0))
        self.summary_button = ttk.Button(footer, text="打开摘要", command=self.open_summary, state="disabled")
        self.summary_button.grid(row=0, column=2, padx=(6, 0))
        self.directory_button = ttk.Button(footer, text="打开目录", command=self.open_directory, state="disabled")
        self.directory_button.grid(row=0, column=3, padx=(6, 0))
        self.refresh_button = ttk.Button(footer, text="刷新", command=self._repeat_refresh)
        self.refresh_button.grid(row=0, column=4, padx=(6, 0))
        self.output_root: Path | None = None

    def refresh(self, output_root: Path) -> None:
        self.output_root = output_root
        self.entries = scan_recent_runs(output_root, self.max_entries)
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.entries):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    entry.display_time,
                    STATUS_LABELS.get(entry.status, entry.status),
                    entry.run_directory.name,
                ),
            )
        if self.entries:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self.status_var.set(f"{len(self.entries)} 个最近任务 · {output_root}")
        else:
            self.status_var.set(f"未找到可打开的聚合结果 · {output_root}")
        self._update_buttons()

    def _repeat_refresh(self) -> None:
        if self.output_root is not None:
            self.refresh(self.output_root)

    def _selected(self) -> RecentRun | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return self.entries[int(selected[0])]
        except (ValueError, IndexError):
            return None

    def _update_buttons(self) -> None:
        entry = self._selected()
        state = "normal" if entry else "disabled"
        self.open_button.configure(state=state)
        self.directory_button.configure(state=state)
        self.summary_button.configure(state="normal" if entry and entry.summary_path else "disabled")

    def _open(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            open_local_path(path)
        except Exception as exc:
            messagebox.showerror("无法打开结果", str(exc), parent=self)

    def open_aggregate(self) -> None:
        entry = self._selected()
        self._open(entry.aggregate_path if entry else None)

    def open_summary(self) -> None:
        entry = self._selected()
        self._open(entry.summary_path if entry else None)

    def open_directory(self) -> None:
        entry = self._selected()
        self._open(entry.run_directory if entry else None)
